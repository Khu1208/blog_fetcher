"""
main.py  (replaces test_run.py)
--------------------------------
Pipeline orchestrator. Runs all steps in order, logs everything,
handles partial failures gracefully.

Run:
    python main.py
    python main.py --dry-run     # skips email, shows console preview
    python main.py --days 3      # only fetch articles from last 3 days
    python main.py --top 10      # send only top 10 articles
"""

import argparse
import sys
import time
from pathlib import Path

# ── Add modules/ to path so imports work ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent / "modules"))

from logger_setup import setup_logging, get_logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import print as rprint

# Pipeline modules
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# We import lazily inside steps so import errors surface with clear messages
console = Console()
logger = get_logger("main")

TOP_N_DEFAULT = 12     # articles to include in the final email
SHORTLIST_LIMIT = 50   # articles to send to LLM for ranking (after heuristic filter)


# ── Step runners ──────────────────────────────────────────────────────────────

def step_fetch(feeds, max_age_days: int) -> list[dict]:
    from fetcher import fetch_all
    logger.info(f"Fetcher: starting | feeds={len(feeds)} | max_age_days={max_age_days}")
    t = time.time()
    articles = fetch_all(feeds, max_age_days=max_age_days)
    logger.info(f"Fetcher: done in {time.time()-t:.1f}s | articles={len(articles)}")
    return articles


def step_deduplicate(articles: list[dict]) -> list[dict]:
    from deduplicator import filter_new
    logger.info(f"Deduplicator: checking {len(articles)} articles against SQLite")
    t = time.time()
    new_articles = filter_new(articles)
    logger.info(
        f"Deduplicator: done in {time.time()-t:.1f}s | "
        f"new={len(new_articles)} dropped={len(articles)-len(new_articles)}"
    )
    return new_articles


def step_shortlist(articles: list[dict], limit: int) -> list[dict]:
    from filters import shortlist_articles
    logger.info(f"Shortlister: scoring {len(articles)} articles | limit={limit}")
    t = time.time()
    shortlisted = shortlist_articles(articles, limit=limit)
    logger.info(
        f"Shortlister: done in {time.time()-t:.1f}s | shortlisted={len(shortlisted)}"
    )
    return shortlisted


def step_rank(articles: list[dict]) -> list[dict]:
    from ranker import rank_articles
    logger.info(f"Ranker: sending {len(articles)} articles to Ollama in one batch")
    t = time.time()
    ranked = rank_articles(articles)
    llm_count = sum(1 for a in ranked if a.get("ranked_by") == "llm")
    logger.info(
        f"Ranker: done in {time.time()-t:.1f}s | "
        f"llm={llm_count} heuristic={len(ranked)-llm_count}"
    )
    return ranked


def step_send(articles: list[dict], stats: dict, dry_run: bool) -> bool:
    from mailer import send_email, _preview_console
    if dry_run:
        logger.info("Mailer: dry-run mode — showing console preview, no email sent")
        _preview_console(articles)
        return True
    return send_email(articles, stats)


def step_mark_seen(articles: list[dict]) -> int:
    from deduplicator import mark_as_seen
    count = mark_as_seen(articles)
    logger.info(f"Deduplicator: marked {count} URLs as seen in SQLite")
    return count


# ── Summary table ─────────────────────────────────────────────────────────────

def print_pipeline_summary(steps: list[tuple[str, str, float]]) -> None:
    """Print a table of step name | status | time taken."""
    table = Table(title="Pipeline Summary", show_lines=False, header_style="bold cyan")
    table.add_column("Step", style="white", width=22)
    table.add_column("Status", width=10)
    table.add_column("Time", justify="right", style="dim")

    for name, status, elapsed in steps:
        icon = "✅" if status == "ok" else "❌" if status == "error" else "⏭"
        table.add_row(name, f"{icon} {status}", f"{elapsed:.1f}s")

    console.print(table)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dev Digest pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Print email preview, don't send")
    parser.add_argument("--days", type=int, default=7, help="Fetch articles from last N days")
    parser.add_argument("--top", type=int, default=TOP_N_DEFAULT, help="Number of articles in email")
    args = parser.parse_args()

    setup_logging()
    pipeline_start = time.time()
    steps: list[tuple[str, str, float]] = []

    # ── Header ────────────────────────────────────────────────────────────────
    console.print(Panel.fit(
        f"[bold white]Dev Digest Pipeline[/]\n"
        f"[dim]days={args.days}  top={args.top}  dry_run={args.dry_run}[/]",
        border_style="bold blue"
    ))

    from feeds import FEEDS
    logger.info(f"Pipeline: starting | feeds={len(FEEDS)} | days={args.days} | top={args.top}")

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(),
                  console=console, transient=True) as prog:
        prog.add_task("Fetching RSS feeds...")
        t0 = time.time()
        try:
            articles = step_fetch(FEEDS, max_age_days=args.days)
            steps.append(("1. Fetch", "ok", time.time() - t0))
            rprint(f"  [green]Fetched[/] [bold]{len(articles)}[/] articles from {len(FEEDS)} feeds")
        except Exception as e:
            logger.exception("Fetch step crashed")
            steps.append(("1. Fetch", "error", time.time() - t0))
            console.print("[red]Fetch failed — cannot continue[/]")
            print_pipeline_summary(steps)
            sys.exit(1)

    # ── Step 2: Deduplicate ───────────────────────────────────────────────────
    t0 = time.time()
    try:
        new_articles = step_deduplicate(articles)
        steps.append(("2. Deduplicate", "ok", time.time() - t0))
        dropped = len(articles) - len(new_articles)
        rprint(f"  [green]New:[/] [bold]{len(new_articles)}[/]  [dim]({dropped} already seen)[/]")

        if not new_articles:
            logger.info("Pipeline: no new articles — nothing to send today")
            console.print("[yellow]No new articles today. Check back tomorrow![/]")
            sys.exit(0)
    except Exception as e:
        logger.exception("Dedup step crashed")
        steps.append(("2. Deduplicate", "error", time.time() - t0))
        new_articles = articles   # proceed without dedup rather than abort
        rprint("[yellow]  Dedup failed — using all articles[/]")

    # ── Step 3: Shortlist ─────────────────────────────────────────────────────
    t0 = time.time()
    try:
        shortlisted = step_shortlist(new_articles, limit=SHORTLIST_LIMIT)
        steps.append(("3. Shortlist", "ok", time.time() - t0))
        rprint(f"  [green]Shortlisted[/] [bold]{len(shortlisted)}[/] for LLM ranking")
    except Exception as e:
        logger.exception("Shortlist step crashed")
        steps.append(("3. Shortlist", "error", time.time() - t0))
        shortlisted = new_articles[:SHORTLIST_LIMIT]

    # ── Step 4: LLM Rank ──────────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(),
                  console=console, transient=True) as prog:
        prog.add_task(f"Ranking {len(shortlisted)} articles via Ollama (1 batch call)...")
        t0 = time.time()
        try:
            ranked = step_rank(shortlisted)
            steps.append(("4. LLM Rank", "ok", time.time() - t0))
            llm_count = sum(1 for a in ranked if a.get("ranked_by") == "llm")
            rprint(
                f"  [green]Ranked[/] [bold]{len(ranked)}[/] articles "
                f"([cyan]{llm_count} by LLM[/], {len(ranked)-llm_count} heuristic)"
            )
        except Exception as e:
            logger.exception("Rank step crashed")
            steps.append(("4. LLM Rank", "error", time.time() - t0))
            ranked = shortlisted   # unranked but pipeline continues

    # ── Top N selection ───────────────────────────────────────────────────────
    top_articles = ranked[:args.top]
    rprint(f"  [dim]Selected top {len(top_articles)} for email[/]")

    # ── Build stats dict for email + logging ──────────────────────────────────
    from deduplicator import get_stats
    db_stats = get_stats()
    stats = {
        "total_fetched": len(articles),
        "total_new": len(new_articles),
        "shortlisted": len(shortlisted),
        "llm_ranked": sum(1 for a in ranked if a.get("ranked_by") == "llm"),
        "top_n": len(top_articles),
        "total_seen": db_stats["total_seen"],
    }
    logger.info(f"Pipeline stats: {stats}")

    # ── Step 5: Send email ────────────────────────────────────────────────────
    t0 = time.time()
    try:
        sent = step_send(top_articles, stats, dry_run=args.dry_run)
        status = "ok" if sent else "skipped"
        steps.append(("5. Send Email", status, time.time() - t0))
    except Exception as e:
        logger.exception("Send step crashed")
        steps.append(("5. Send Email", "error", time.time() - t0))

    # ── Step 6: Mark seen — ONLY after successful send ────────────────────────
    t0 = time.time()
    if not args.dry_run:
        try:
            count = step_mark_seen(top_articles)
            steps.append(("6. Mark Seen", "ok", time.time() - t0))
            rprint(f"  [green]Marked[/] [bold]{count}[/] URLs as seen in SQLite")
        except Exception as e:
            logger.exception("Mark-seen step crashed")
            steps.append(("6. Mark Seen", "error", time.time() - t0))
    else:
        steps.append(("6. Mark Seen", "skipped", 0.0))
        rprint("  [dim]Mark-seen skipped (dry run)[/]")

    # ── Final summary ─────────────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    console.print()
    print_pipeline_summary(steps)
    logger.info(f"Pipeline: finished in {total_time:.1f}s")
    rprint(f"\n[bold green]Done![/] Total time: [bold]{total_time:.1f}s[/]")


if __name__ == "__main__":
    main()
