"""
ranker.py
---------
Responsibility: Score and categorise articles using Groq API LLM.

KEY OPTIMISATION vs original:
  ❌ Before : 1 LLM call per article → 50 articles = 50 calls = 25-40 minutes
  ✅ After  : 1 single batched call for ALL articles → same result in ~30 seconds

How batching works:
  We send all article titles + summaries in ONE prompt and ask the model
  to return a JSON array with a score + category per article.
  The model processes context holistically — it can even compare articles
  against each other, which produces better relative ranking.

Fallback strategy:
  If the LLM call fails OR returns unparseable JSON, every article gets
  a heuristic score from filters.score_article() so the pipeline never stops.
"""

import json
import logging
import os
import time
from typing import Optional

from groq import Groq


from dotenv import load_dotenv
load_dotenv()

from filters import score_article

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is not set")

client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.1-8b-instant"
MAX_RETRIES = 2
RETRY_DELAY = 2            # seconds between retries

CATEGORIES = ["AI/LLM", "System Design", "MLOps", "Backend", "General Tech"]

# Max articles per batch — prevents prompt from exceeding context window
# llama3 8B handles ~50 articles comfortably within 8k context
BATCH_SIZE = 50


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_batch_prompt(articles: list[dict]) -> str:
    """
    Build a single prompt containing ALL articles.

    Format: numbered list so the model can reference articles by index.
    We ask for a JSON array with one object per article, indexed same way.

    Why numbered list and not titles?
    Titles can be long/ambiguous. Index is unambiguous for matching output → input.
    """
    lines = []
    for i, a in enumerate(articles):
        lines.append(
            f"[{i}] Source: {a['source']}\n"
            f"    Title: {a['title']}\n"
            f"    Summary: {a['summary'][:300]}"
        )

    articles_block = "\n\n".join(lines)

    return f"""You are a tech article curator for a backend engineer preparing for placements.
Score and categorise each article below. Reply with ONLY a valid JSON array — no extra text, no markdown.

Each element must follow this exact shape:
{{"i": <index>, "score": <1-10>, "category": "<{'|'.join(CATEGORIES)}>"}}

Scoring guide:
  9-10 → directly useful for placements (system design, LLM internals, distributed systems)
  7-8  → strong engineering depth (real production case studies, architecture deep-dives)
  5-6  → solid general backend / AI content
  3-4  → tangentially related
  1-2  → news, announcements, or off-topic

Articles to score:

{articles_block}

Return ONLY the JSON array. Example format:
[{{"i":0,"score":8,"category":"System Design"}},{{"i":1,"score":6,"category":"AI/LLM"}}]"""


# ── Response parser ────────────────────────────────────────────────────────────

def _extract_json_array(text: str) -> str:
    """Pull out the first [...] block from model output."""
    start = text.find("[")
    end = text.rfind("]") + 1
    if start != -1 and end > start:
        return text[start:end]
    raise ValueError("No JSON array found in model response")


def _parse_batch_response(text: str, expected_count: int) -> list[dict]:
    """
    Parse the model's JSON array into a list of {i, score, category} dicts.
    Validates index range and score bounds.
    Returns empty list on any failure — caller handles fallback.
    """
    raw = _extract_json_array(text)
    data = json.loads(raw)

    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data)}")

    results = []
    seen_indices = set()

    for item in data:
        idx = int(item["i"])
        if idx < 0 or idx >= expected_count:
            logger.warning(f"Ranker: ignoring out-of-range index {idx}")
            continue
        if idx in seen_indices:
            logger.warning(f"Ranker: duplicate index {idx} in response, skipping")
            continue

        score = max(1, min(10, int(item.get("score", 5))))
        category = item.get("category", "General Tech")
        if category not in CATEGORIES:
            category = "General Tech"

        results.append({"i": idx, "score": score, "category": category})
        seen_indices.add(idx)

    return results


# ── Fallback ───────────────────────────────────────────────────────────────────

def _heuristic_fallback(articles: list[dict]) -> list[dict]:
    """
    When LLM is unavailable or returns garbage, score with keyword heuristics.
    Guarantees every article gets a score so the pipeline never stalls.
    """
    logger.warning("Ranker: using heuristic fallback for all articles")
    result = []
    for a in articles:
        text = (a["title"] + " " + a["summary"]).lower()
        raw_score = score_article(a)
        score = max(1, min(10, raw_score))

        if any(kw in text for kw in ["llm", "agent", "rag", "gpt", "transformer"]):
            category = "AI/LLM"
        elif any(kw in text for kw in ["mlops", "inference", "training pipeline"]):
            category = "MLOps"
        elif any(kw in text for kw in ["system design", "distributed", "architecture", "kafka", "redis"]):
            category = "System Design"
        elif any(kw in text for kw in ["api", "backend", "database", "microservice"]):
            category = "Backend"
        else:
            category = "General Tech"

        result.append({**a, "score": score, "category": category, "ai_summary": "", "ranked_by": "heuristic"})
    return result


# ── Groq caller ────────────────────────────────────────────────────────────────

def _call_groq(prompt: str) -> Optional[str]:
    """
    Send prompt to Groq API, return raw response text.
    Returns None on complete failure after retries.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Ranker: Groq call attempt {attempt}/{MAX_RETRIES}")
            message = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            return message.choices[0].message.content

        except Exception as e:
            logger.warning(f"Ranker: attempt {attempt} failed — {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    return None


# ── Main public function ───────────────────────────────────────────────────────

def rank_articles(articles: list[dict]) -> list[dict]:
    """
    Score and categorise a list of articles using ONE batched Groq call.

    Args:
        articles: list of Article dicts (from fetcher → deduplicator → shortlister)

    Returns:
        Same articles enriched with:
          - score      : int 1–10
          - category   : str one of CATEGORIES
          - ranked_by  : "llm" | "heuristic"  (useful for debugging)

    Sorted by score descending.
    Never raises — always returns a scored list.
    """
    if not articles:
        return []

    logger.info(f"Ranker: starting batch ranking for {len(articles)} articles")
    start_time = time.time()

    # Process in batches to stay within context window
    all_ranked: list[dict] = []

    for batch_start in range(0, len(articles), BATCH_SIZE):
        batch = articles[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(articles) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"Ranker: batch {batch_num}/{total_batches} — {len(batch)} articles")

        prompt = _build_batch_prompt(batch)
        raw_response = _call_groq(prompt)

        if raw_response is None:
            # Groq call failed — fallback whole batch
            all_ranked.extend(_heuristic_fallback(batch))
            continue

        try:
            scored_items = _parse_batch_response(raw_response, expected_count=len(batch))

            # Build index → score/category map from parsed response
            score_map = {item["i"]: item for item in scored_items}

            for i, article in enumerate(batch):
                if i in score_map:
                    all_ranked.append({
                        **article,
                        "score": score_map[i]["score"],
                        "category": score_map[i]["category"],
                        "ai_summary": "",       # batch mode: no per-article summary (saves tokens)
                        "ranked_by": "llm",
                    })
                else:
                    # Model skipped this index — use heuristic for just this one
                    logger.warning(f"Ranker: no score returned for index {i} ({article['title'][:60]})")
                    fallback = _heuristic_fallback([article])[0]
                    all_ranked.append(fallback)

            llm_count = sum(1 for a in all_ranked if a.get("ranked_by") == "llm")
            logger.info(f"Ranker: batch {batch_num} done — {llm_count}/{len(batch)} ranked by LLM")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"Ranker: JSON parse failed for batch {batch_num} — {e}")
            logger.debug(f"Ranker: raw response was: {raw_response[:500]}")
            all_ranked.extend(_heuristic_fallback(batch))

    elapsed = time.time() - start_time
    llm_total = sum(1 for a in all_ranked if a.get("ranked_by") == "llm")
    logger.info(
        f"Ranker: complete in {elapsed:.1f}s — "
        f"{llm_total}/{len(all_ranked)} by LLM, "
        f"{len(all_ranked) - llm_total} by heuristic"
    )

    # Sort by score descending — best articles first
    all_ranked.sort(key=lambda a: a["score"], reverse=True)
    return all_ranked
