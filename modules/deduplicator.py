import logging
import os
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")


# ─────────────────────────────────────────────
# PostgreSQL Connection
# ─────────────────────────────────────────────

def _get_connection():
    conn = psycopg2.connect(DATABASE_URL)

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                published_at TEXT,
                seen_at TEXT NOT NULL,
                score INTEGER,
                category TEXT,
                summary TEXT
            )
            """
        )

        conn.commit()

    return conn


# ─────────────────────────────────────────────
# Filter already-seen articles
# ─────────────────────────────────────────────

def filter_new(articles: list[dict]) -> list[dict]:
    """
    Return only unseen articles.
    """

    if not articles:
        return []

    conn = _get_connection()

    try:
        urls = [a["url"] for a in articles]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT url
                FROM seen_urls
                WHERE url = ANY(%s)
                """,
                (urls,),
            )

            rows = cur.fetchall()

        already_seen = {row[0] for row in rows}

        new_articles = [
            a for a in articles
            if a["url"] not in already_seen
        ]

        logger.info(
            f"Deduplicator: {len(articles)} total | "
            f"{len(already_seen)} already seen | "
            f"{len(new_articles)} new"
        )

        return new_articles

    finally:
        conn.close()


# ─────────────────────────────────────────────
# Mark articles as seen
# ─────────────────────────────────────────────

def mark_as_seen(articles: list[dict]) -> int:
    """
    Store ranked articles in PostgreSQL.
    """

    if not articles:
        return 0

    conn = _get_connection()

    try:
        now = datetime.now(timezone.utc).isoformat()

        rows = [
            (
                a["url"],
                a["title"],
                a["source"],
                a.get("published"),
                now,
                a.get("score"),
                a.get("category"),
                a.get("ai_summary"),
            )
            for a in articles
        ]

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO seen_urls (
                    url,
                    title,
                    source,
                    published_at,
                    seen_at,
                    score,
                    category,
                    summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
                """,
                rows,
            )

        conn.commit()

        inserted = len(rows)

        logger.info(
            f"Deduplicator: marked {inserted} URLs as seen"
        )

        return inserted

    finally:
        conn.close()


# ─────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────

def get_stats() -> dict:
    """
    Return DB statistics.
    """

    conn = _get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM seen_urls
                """
            )

            total = cur.fetchone()[0]

            cur.execute(
                """
                SELECT seen_at
                FROM seen_urls
                ORDER BY seen_at ASC
                LIMIT 1
                """
            )

            oldest = cur.fetchone()

        return {
            "total_seen": total,
            "tracking_since": oldest[0] if oldest else None,
        }

    finally:
        conn.close()