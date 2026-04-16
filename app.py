"""
app.py — Main Flask application entry point.
Serves the API and the frontend SPA from a single process.
Port: 3700 (different from Project 1's 3600)
"""

import os
from flask import Flask, send_from_directory
from api.crawler_routes import bp as crawler_bp
from api.search_routes   import bp as search_bp
from core.db import init_db

# ── App factory ───────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)

# CORS — allow localhost calls from the SPA
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return resp

# Register blueprints
app.register_blueprint(crawler_bp)
app.register_blueprint(search_bp)

# ── Serve single-page frontend ────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/<path:filename>", methods=["GET"])
def serve_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)

# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_):
    return {"error": "Not found"}, 404

@app.errorhandler(405)
def method_not_allowed(_):
    return {"error": "Method not allowed"}, 405

# ── Bootstrap ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("🕷️  Agent Crawler v2 — http://localhost:3700")
    app.run(debug=True, host="0.0.0.0", port=3700, use_reloader=False)
