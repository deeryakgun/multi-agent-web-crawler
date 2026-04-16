"""
crawler_routes.py — Flask blueprint for indexing (crawl) endpoints.

Endpoints:
  POST /index                    — Start a new crawl job
  GET  /index/<id>/status        — Get job status + logs
  POST /index/<id>/pause         — Pause
  POST /index/<id>/resume        — Resume
  POST /index/<id>/stop          — Stop
  GET  /index/list               — List all jobs
  GET  /index/stats              — Global stats
  POST /index/clear              — Wipe DB and restart
"""

import time
import threading
from flask import Blueprint, request, jsonify

from core.db import (
    init_db, insert_crawler, get_crawler, list_crawlers,
    get_logs, get_stats, get_connection
)
from core.crawler_engine import (
    CrawlerEngine, register, get_engine, remove_engine, all_engines
)

bp = Blueprint("crawler", __name__)


def _make_id() -> str:
    return f"{int(time.time())}_{threading.get_ident()}"


@bp.route("/index", methods=["POST"])
def start_index():
    """Start a new crawl (index) job."""
    data = request.get_json(silent=True) or {}

    origin = data.get("origin", "").strip()
    if not origin or not origin.startswith(("http://", "https://")):
        return jsonify({"error": "origin must be a valid http/https URL"}), 400

    try:
        max_depth = int(data.get("k", data.get("max_depth", 2)))
        assert 1 <= max_depth <= 500
    except (TypeError, ValueError, AssertionError):
        return jsonify({"error": "k (max_depth) must be an integer between 1 and 500"}), 400

    hit_rate   = float(data.get("hit_rate", 2.0))
    queue_cap  = int(data.get("queue_cap", 10_000))
    max_urls   = int(data.get("max_urls", 500))
    resume     = bool(data.get("resume", False))

    crawler_id = _make_id()
    now = time.time()

    init_db()
    insert_crawler(crawler_id, origin, max_depth, hit_rate, queue_cap, max_urls, now)

    engine = CrawlerEngine(
        crawler_id=crawler_id,
        origin=origin,
        max_depth=max_depth,
        hit_rate=hit_rate,
        queue_cap=queue_cap,
        max_urls=max_urls,
        resume=resume,
    )
    register(engine)
    engine.start()

    return jsonify({
        "crawler_id": crawler_id,
        "status": "Active",
        "origin": origin,
        "max_depth": max_depth,
        "hit_rate": hit_rate,
        "queue_cap": queue_cap,
        "max_urls": max_urls,
    }), 201


@bp.route("/index/<crawler_id>/status", methods=["GET"])
def index_status(crawler_id):
    row = get_crawler(crawler_id)
    if not row:
        return jsonify({"error": "Crawler not found"}), 404

    engine = get_engine(crawler_id)
    if engine:
        if engine.is_paused():
            row["status"] = "Paused"
        elif engine.is_alive():
            row["status"] = "Active"
        row["queue_depth"]   = engine.queue_depth()
        row["visited_count"] = engine.visited_count()
        # Back-pressure flag
        ratio = engine.queue_depth() / max(row["queue_cap"], 1)
        row["back_pressure"] = ratio > 0.8
        row["queue_ratio"]   = round(ratio, 3)
    else:
        row["back_pressure"] = False
        row["queue_ratio"]   = 0.0

    logs = get_logs(crawler_id, limit=60)
    row["logs"] = [l["message"] for l in logs]
    return jsonify(row), 200


@bp.route("/index/<crawler_id>/pause", methods=["POST"])
def pause_index(crawler_id):
    engine = get_engine(crawler_id)
    if not engine or not engine.is_alive():
        return jsonify({"error": "Crawler not active"}), 404
    engine.pause()
    return jsonify({"status": "Paused"}), 200


@bp.route("/index/<crawler_id>/resume", methods=["POST"])
def resume_index(crawler_id):
    engine = get_engine(crawler_id)
    if not engine or not engine.is_alive():
        return jsonify({"error": "Crawler not active or already finished"}), 404
    engine.resume_crawl()
    return jsonify({"status": "Active"}), 200


@bp.route("/index/<crawler_id>/stop", methods=["POST"])
def stop_index(crawler_id):
    engine = get_engine(crawler_id)
    if engine and engine.is_alive():
        engine.stop()
        return jsonify({"status": "stop_requested"}), 200
    return jsonify({"status": "not_active"}), 200


@bp.route("/index/list", methods=["GET"])
def list_index():
    crawlers = list_crawlers()
    engines  = all_engines()
    for c in crawlers:
        eng = engines.get(c["id"])
        if eng and eng.is_alive():
            c["status"] = "Paused" if eng.is_paused() else "Active"
            c["queue_depth"]   = eng.queue_depth()
            c["visited_count"] = eng.visited_count()
        c["back_pressure"] = (c.get("queue_depth", 0) /
                               max(c.get("queue_cap", 1), 1)) > 0.8
    return jsonify({"crawlers": crawlers, "total": len(crawlers)}), 200


@bp.route("/index/stats", methods=["GET"])
def index_stats():
    stats = get_stats()
    active = sum(1 for e in all_engines().values() if e.is_alive())
    stats["active_crawlers"] = active
    return jsonify(stats), 200


@bp.route("/index/clear", methods=["POST"])
def clear_index():
    """Stop all active crawlers and wipe the database."""
    for cid, eng in list(all_engines().items()):
        if eng.is_alive():
            eng.stop()
        remove_engine(cid)
    # Drop and recreate tables
    conn = get_connection()
    conn.executescript("""
        DELETE FROM word_index;
        DELETE FROM pages;
        DELETE FROM crawler_logs;
        DELETE FROM crawlers;
    """)
    conn.commit()
    return jsonify({"status": "cleared"}), 200
