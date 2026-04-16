"""
search_engine.py — TF-IDF based search with BM25-inspired scoring.

How it works:
  1. Tokenise and normalise the query string.
  2. Look up matching words in the SQLite word_index table.
  3. Compute IDF = log( (N + 1) / (df + 1) ) per word  (smoothed).
  4. Final score = sum(TF * IDF) per page, with bonuses for exact matches
     and shallow depth.
  5. Results are deduplicated by URL and sorted by score.

Live search: because SQLite is in WAL mode, reads never block concurrent
crawler writes, so search always reflects the latest indexed pages.
"""

import math
import re
from typing import Optional

from core.db import search_word_index, get_total_pages, get_pages_with_word


def _tokenise(query: str) -> list[str]:
    """Lower-case, split on non-alpha, return unique words ≥ 2 chars."""
    tokens = re.findall(r"[a-zA-Z]{2,}", query.lower())
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def search(query: str, page_limit: int = 10, page_offset: int = 0,
           sort_by: str = "relevance") -> dict:
    """
    Search the index and return paginated results.

    Args:
        query       : Free-text search query.
        page_limit  : Max results to return.
        page_offset : Skip this many top results (pagination).
        sort_by     : "relevance" | "depth" | "frequency"

    Returns dict with:
        results         — list of result dicts, each containing
                          (relevant_url, origin_url, depth, score, title)
        total_results   — total count before pagination
        query_words     — tokenised query terms
    """
    words = _tokenise(query)
    if not words:
        return {"results": [], "total_results": 0, "query_words": []}

    # ── Fetch raw rows for all query words ────────────────────────────────
    rows = search_word_index(words, limit=5000)

    if not rows:
        return {"results": [], "total_results": 0, "query_words": words}

    # ── Compute IDF per word ──────────────────────────────────────────────
    total_pages = max(get_total_pages(), 1)
    idf: dict[str, float] = {}
    for word in words:
        df = get_pages_with_word(word)
        idf[word] = math.log((total_pages + 1) / (df + 1)) + 1.0

    # ── Aggregate scores per page URL ─────────────────────────────────────
    # key = (page_url, crawler_id)
    page_scores: dict[tuple, dict] = {}

    for row in rows:
        key = (row["page_url"], row["crawler_id"])
        if key not in page_scores:
            page_scores[key] = {
                "relevant_url": row["page_url"],
                "origin_url": row["origin_url"],
                "depth": row["depth"],
                "crawler_id": row["crawler_id"],
                "title": row.get("title") or "",
                "score": 0.0,
                "frequency": 0,
            }

        entry = page_scores[key]
        word = row["word"]
        tf = row["tf"]
        freq = row["frequency"]

        word_idf = idf.get(word, 1.0)
        tfidf = tf * word_idf

        # Exact-word bonus
        if word in words:
            tfidf *= 1.5

        entry["score"] += tfidf
        entry["frequency"] += freq

    # ── Depth bonus: shallower pages get a slight lift ────────────────────
    results = list(page_scores.values())
    for r in results:
        depth_factor = 1.0 / (1 + r["depth"] * 0.1)
        r["score"] *= depth_factor

    # ── Sort ──────────────────────────────────────────────────────────────
    if sort_by == "depth":
        results.sort(key=lambda x: x["depth"])
    elif sort_by == "frequency":
        results.sort(key=lambda x: x["frequency"], reverse=True)
    else:
        results.sort(key=lambda x: x["score"], reverse=True)

    # ── Pagination ────────────────────────────────────────────────────────
    total = len(results)
    paginated = results[page_offset: page_offset + page_limit]

    # Round scores for cleaner API output
    for r in paginated:
        r["score"] = round(r["score"], 4)

    return {
        "results": paginated,
        "total_results": total,
        "query_words": words,
    }
