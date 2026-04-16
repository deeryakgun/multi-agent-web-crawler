"""
search_routes.py — Flask blueprint for search endpoints.

Endpoints:
  GET /search          — Full TF-IDF search with pagination
  GET /search/suggest  — Simple autocomplete suggestions
"""

from flask import Blueprint, request, jsonify
from core.search_engine import search as do_search

bp = Blueprint("search", __name__)


@bp.route("/search", methods=["GET"])
def search():
    """
    Search the index.

    Query params:
      query       (str, required)
      page_limit  (int, default=10)
      page_offset (int, default=0)
      sort_by     (str, default="relevance")  — relevance|depth|frequency
    """
    query = (request.args.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query parameter is required"}), 400

    try:
        page_limit  = max(1, int(request.args.get("page_limit",  10)))
        page_offset = max(0, int(request.args.get("page_offset",  0)))
    except (TypeError, ValueError):
        return jsonify({"error": "page_limit and page_offset must be integers"}), 400

    sort_by = request.args.get("sort_by", "relevance")
    if sort_by not in ("relevance", "depth", "frequency"):
        sort_by = "relevance"

    result = do_search(query, page_limit, page_offset, sort_by)
    result["query"] = query
    result["sort_by"] = sort_by
    return jsonify(result), 200


@bp.route("/search/suggest", methods=["GET"])
def suggest():
    """Return up to 8 word suggestions based on a prefix."""
    prefix = (request.args.get("q") or "").strip().lower()
    if len(prefix) < 2:
        return jsonify({"suggestions": []}), 200

    from core.db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT word FROM word_index WHERE word LIKE ? LIMIT 8",
        (prefix + "%",)
    ).fetchall()
    return jsonify({"suggestions": [r["word"] for r in rows]}), 200
