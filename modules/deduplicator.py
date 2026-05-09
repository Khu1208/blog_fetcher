"""
deduplicator.py
---------------
Responsibility: Filter out articles we have already seen.

This module does TWO things (tightly related, so kept together):
  1. READ  — check which articles from the fetcher are new
  2. WRITE — after sending, mark those URLs as seen

It does NOT fetch, rank, or send anything.
Storage: SQLite — a single file, no server needed.

Table schema:
    seen_urls (
        url       TEXT PRIMARY KEY,
        source    TEXT,
        seen_at   TEXT   -- ISO datetime
    )
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Default DB path — sits in the data/ folder next to modules/
DEFAULT_DB_PATH = Path("data/digest.db")


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """
    Open a SQLite connection and ensure the schema exists.

    Why check_same_thread=False?
    Not needed here (single-threaded script), but good habit
    for when this gets tested or extended.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)

    # Create table if it doesn't exist yet — idempotent, safe to call every run
    conn.execute("""
        
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                score INTEGER,
                category TEXT,
                summary TEXT
            )
        """)
        
    conn.commit()
    return conn


def filter_new(articles: list[dict], db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    """
    Given a list of articles from the fetcher, return only the ones
    we have NOT seen before.

    Args:
        articles : list of Article dicts from fetcher.fetch_all()
        db_path  : path to the SQLite DB file

    Returns:
        Subset of articles where url is NOT in seen_urls table.

    Design: we do ONE bulk query using SQL IN clause instead of
    querying per article — much faster for 200+ articles.
    """
    if not articles:
        return []

    conn = _get_connection(db_path)

    try:
        urls = [a["url"] for a in articles]

        # Build placeholders: (?, ?, ?, ...) for the IN clause
        placeholders = ",".join("?" * len(urls))
        query = f"SELECT url FROM seen_urls WHERE url IN ({placeholders})"
        rows = conn.execute(query, urls).fetchall()

        already_seen = {row[0] for row in rows}  # set for O(1) lookup

        new_articles = [a for a in articles if a["url"] not in already_seen]

        logger.info(
            f"Deduplicator: {len(articles)} total, "
            f"{len(already_seen)} already seen, "
            f"{len(new_articles)} new"
        )
        return new_articles

    finally:
        conn.close()


def mark_as_seen(articles: list[dict], db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    Mark a list of articles as seen in SQLite.
    Call this AFTER the email has been sent successfully.

    Args:
        articles : list of Article dicts that were included in the email
        db_path  : path to the SQLite DB file

    Returns:
        Number of URLs inserted.

    Design: INSERT OR IGNORE — if a URL somehow already exists,
    we skip it silently instead of crashing.
    """
    if not articles:
        return 0

    conn = _get_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()

    try:
        rows = [
            (
                a["url"],
                a["source"],
                now,
                a.get("score"),
                a.get("category"),
                a.get("ai_summary")
            )
            for a in articles
        ]
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_urls
            (url, source, seen_at, score, category, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows
        )
        conn.commit()
        inserted = conn.total_changes
        logger.info(f"Deduplicator: marked {inserted} URLs as seen")
        return inserted

    finally:
        conn.close()


def get_stats(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """
    Return basic stats about the seen_urls table.
    Useful for debugging and for the email footer ("X articles tracked so far").
    """
    conn = _get_connection(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
        oldest = conn.execute(
            "SELECT seen_at FROM seen_urls ORDER BY seen_at ASC LIMIT 1"
        ).fetchone()
        return {
            "total_seen": total,
            "tracking_since": oldest[0] if oldest else None,
        }
    finally:
        conn.close()