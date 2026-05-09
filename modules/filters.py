from collections import defaultdict

TOPICS = [
    "ai", "llm", "agents", "rag", "mlops",
    "machine learning", "system design",
    "distributed", "backend", "infrastructure"
]

PRIORITY = ["llm", "agents", "rag","system design"]

SOURCE_WEIGHTS = {
    "OpenAI Blog": 5,
    "Google DeepMind": 5,
    "Hugging Face": 4,
    "Cloudflare": 4,
    "Stripe": 4,
    "freeCodeCamp": 2,
    "Dev.to AI": 1
}
def is_relevant(article: dict) -> bool:
    text = (article["title"] + " " + article["summary"]).lower()
    return any(kw in text for kw in TOPICS)

def score_article(article: dict) -> int:
    text = (article["title"] + " " + article["summary"]).lower()

    score = 0

    # keyword score
    for kw in TOPICS:
        if kw in text:
            score += 1

    # priority boost
    for kw in PRIORITY:
        if kw in text:
            score += 3

    # source weight
    score += SOURCE_WEIGHTS.get(article["source"], 0)

    return score


def ensure_min_per_source(scored_articles):
    picked = []
    seen_sources = set()

    for article, score in scored_articles:
        if article["source"] not in seen_sources:
            picked.append((article, score))
            seen_sources.add(article["source"])

    return picked


def fill_remaining(scored_articles, already_picked, limit=50):
    picked_urls = {a["url"] for a, _ in already_picked}

    remaining = [
        (a, s) for a, s in scored_articles
        if a["url"] not in picked_urls
    ]

    needed = limit - len(already_picked)

    return already_picked + remaining[:needed]


def shortlist_articles(new_articles, limit=50):
    scored = [(a, score_article(a)) for a in new_articles]

    # sort by score DESC
    scored.sort(key=lambda x: x[1], reverse=True)

    # step 1 → ensure 1 per source
    base = ensure_min_per_source(scored)

    # step 2 → fill remaining
    final_scored = fill_remaining(scored, base, limit)

    return [a for a, s in final_scored]