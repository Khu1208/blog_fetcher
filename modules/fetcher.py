"""
fetcher.py
----------
Responsibility: Read all RSS feeds and return a clean list of articles.

This module does ONE thing only:
  - Takes a list of feed configs (source name + RSS URL)
  - Returns a list of Article dicts

It does NOT deduplicate, rank, or send anything.
That is the next module's job.
"""

import feedparser
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from modules.filters import is_relevant

# ── Logging setup ──────────────────────────────────────────────────────────────
# Each module gets its own named logger so you can trace exactly which
# module printed what in the logs.
logger = logging.getLogger(__name__)

import ssl
ssl._create_default_https_context = ssl._create_unverified_context


# ── Data shape ─────────────────────────────────────────────────────────────────
# A dataclass makes the shape explicit and self-documenting.
# Every downstream module (deduplicator, ranker) knows exactly what fields exist.
@dataclass
class Article:
    title: str
    url: str
    summary: str       # first ~300 chars of content — enough for AI ranking
    source: str        # e.g. "Netflix Tech Blog"
    published: str     # ISO format string — easier to store/log than datetime object


def _is_recent(published_iso: str, cutoff_dt: datetime | None) -> bool:
    """
    Return True when article date is newer than cutoff.
    If cutoff is None, no date filtering is applied.
    """
    if cutoff_dt is None:
        return True

    try:
        published_dt = datetime.fromisoformat(published_iso)
        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        return published_dt >= cutoff_dt
    except Exception:
        # Bad/unknown date format should not crash the pipeline.
        return False


def _parse_entry(entry, source_name: str) -> Article | None:
    """
    Convert a single feedparser entry into our Article dataclass.
    Returns None if the entry is missing critical fields.

    Why a private helper?
    So fetch_all() stays readable — it just loops and calls this.
    All the messy field-extraction lives here.
    """
    # feedparser uses .get() style access but also supports attribute access.
    # We use .get() with fallbacks so missing fields never crash us.

    url = entry.get("link", "").strip()
    title = entry.get("title", "").strip()

    # Both url and title are required — no point keeping an article without them
    if not url or not title:
        return None

    # Extract summary — try 'summary' first, fall back to 'content', then empty
    summary_raw = ""
    if entry.get("summary"):
        summary_raw = entry.summary
    elif entry.get("content"):
        # 'content' is a list of content objects in some feeds
        summary_raw = entry.content[0].get("value", "")

    # Strip HTML tags crudely — we just need plain text for the AI prompt
    import re
    summary_clean = re.sub(r"<[^>]+>", " ", summary_raw)
    summary_clean = " ".join(summary_clean.split())  # collapse whitespace
    summary = summary_clean[:400]                    # cap at 400 chars

    # Parse published date — feedparser gives us a time.struct_time in .published_parsed
    if getattr(entry, "published_parsed", None):
        published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        published = published_dt.isoformat()
    else:
        # Fallback: use right now — better than crashing
        published = datetime.now(timezone.utc).isoformat()

    return Article(
        title=title,
        url=url,
        summary=summary,
        source=source_name,
        published=published,
    )


def fetch_all(
    feeds: list[dict],
    timeout: int = 10,
    max_age_days: int | None = 7,
) -> list[dict]:
    """
    Main public function of this module.

    Args:
        feeds   : list of {"source": str, "url": str} dicts — from feeds.py
        timeout : seconds to wait per feed before giving up (default 10s)

    Returns:
        List of Article dicts — sorted newest first.
        Empty list if everything fails (never raises).

    Design decision: this function NEVER raises an exception.
    If one feed is down, we log it and move on. The other 31 feeds
    should still work. Fail gracefully, not loudly.
    """
    all_articles: list[dict] = []
    success_count = 0
    fail_count = 0
    cutoff_dt = None
    if max_age_days is not None:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        logger.info(
            f"Fetcher: keeping only articles from last {max_age_days} days "
            f"(cutoff={cutoff_dt.isoformat()})"
        )

    for feed_config in feeds:
        source = feed_config["source"]
        feed_url = feed_config["url"]

        try:
            # feedparser.parse() does the HTTP request + XML parsing in one call.
            # It does not raise on HTTP errors — instead sets feed.bozo = True
            # and feed.bozo_exception with the error.
            parsed = feedparser.parse(feed_url, request_headers={
                "User-Agent": "DevDigest/1.0 (personal RSS reader)"
            })

            # bozo = True means the feed had a parse error (malformed XML, etc.)
            # We still try to extract entries — partial data is better than none.
            if parsed.bozo:
                logger.warning(
                    f"[{source}] Feed has parse issues: {parsed.bozo_exception}"
                )

            entries = parsed.get("entries", [])

            if not entries:
                logger.warning(f"[{source}] No entries found in feed")
                fail_count += 1
                continue

            feed_articles = []
            for entry in entries:
                article = _parse_entry(entry, source_name=source)
                if article:
                    article_dict = asdict(article)

                    if not _is_recent(article_dict["published"], cutoff_dt):
                        continue

                    if is_relevant(article_dict):
                        feed_articles.append(article_dict)
            logger.info(f"[{source}] Fetched {len(feed_articles)} articles")
            all_articles.extend(feed_articles)
            success_count += 1

        except Exception as e:
            # Catches network errors, timeouts, any unexpected crash
            logger.error(f"[{source}] Failed to fetch: {type(e).__name__}: {e}")
            fail_count += 1
            continue  # never stop the loop — try next feed

    logger.info(
        f"Fetcher done. {success_count} feeds OK, {fail_count} failed. "
        f"Total articles: {len(all_articles)}"
    )

    # Sort newest first — so the ranker sees fresh content at the top
    all_articles.sort(key=lambda a: a["published"], reverse=True)

    return all_articles
