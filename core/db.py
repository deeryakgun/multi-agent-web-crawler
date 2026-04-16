"""
db.py — SQLite database schema and helper layer
Uses WAL (Write-Ahead Logging) mode so reads and writes can happen concurrently,
which allows live search while indexing is still active.
"""

import sqlite3
import os
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "crawler.db")

# Thread-local storage so each thread gets its own connection
_local = threading.local()


def get_connection():
    """Return a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL mode: readers don't block writers, writers don't block readers
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def close_connection():
    """Close the thread-local connection."""
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS crawlers (
            id          TEXT PRIMARY KEY,
            origin      TEXT NOT NULL,
            max_depth   INTEGER NOT NULL,
            hit_rate    REAL NOT NULL DEFAULT 1.0,
            queue_cap   INTEGER NOT NULL DEFAULT 10000,
            max_urls    INTEGER NOT NULL DEFAULT 1000,
            status      TEXT NOT NULL DEFAULT 'Active',
            visited_count INTEGER NOT NULL DEFAULT 0,
            queue_depth INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            completed_at REAL
        );

        CREATE TABLE IF NOT EXISTS pages (
            url         TEXT NOT NULL,
            crawler_id  TEXT NOT NULL,
            origin_url  TEXT NOT NULL,
            depth       INTEGER NOT NULL,
            title       TEXT,
            word_count  INTEGER DEFAULT 0,
            crawled_at  REAL NOT NULL,
            PRIMARY KEY (url, crawler_id),
            FOREIGN KEY (crawler_id) REFERENCES crawlers(id)
        );

        CREATE TABLE IF NOT EXISTS word_index (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            word        TEXT NOT NULL,
            page_url    TEXT NOT NULL,
            crawler_id  TEXT NOT NULL,
            origin_url  TEXT NOT NULL,
            depth       INTEGER NOT NULL,
            frequency   INTEGER NOT NULL DEFAULT 1,
            tf          REAL NOT NULL DEFAULT 0.0,
            FOREIGN KEY (crawler_id) REFERENCES crawlers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_word ON word_index(word);
        CREATE INDEX IF NOT EXISTS idx_page_url ON word_index(page_url);
        CREATE INDEX IF NOT EXISTS idx_crawler ON word_index(crawler_id);
        CREATE INDEX IF NOT EXISTS idx_crawlers_status ON crawlers(status);

        CREATE TABLE IF NOT EXISTS crawler_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            crawler_id  TEXT NOT NULL,
            message     TEXT NOT NULL,
            logged_at   REAL NOT NULL,
            FOREIGN KEY (crawler_id) REFERENCES crawlers(id)
        );
    """)
    conn.commit()


# ── Crawler helpers ────────────────────────────────────────────────────────────

def insert_crawler(crawler_id, origin, max_depth, hit_rate, queue_cap, max_urls, created_at):
    conn = get_connection()
    conn.execute(
        """INSERT INTO crawlers
           (id, origin, max_depth, hit_rate, queue_cap, max_urls, status,
            visited_count, queue_depth, created_at, updated_at)
           VALUES (?,?,?,?,?,?,'Active',0,0,?,?)""",
        (crawler_id, origin, max_depth, hit_rate, queue_cap, max_urls,
         created_at, created_at)
    )
    conn.commit()


def update_crawler_status(crawler_id, status, visited_count=None,
                          queue_depth=None, updated_at=None, completed_at=None):
    import time
    conn = get_connection()
    sets = ["status=?", "updated_at=?"]
    vals = [status, updated_at or time.time()]
    if visited_count is not None:
        sets.append("visited_count=?"); vals.append(visited_count)
    if queue_depth is not None:
        sets.append("queue_depth=?"); vals.append(queue_depth)
    if completed_at is not None:
        sets.append("completed_at=?"); vals.append(completed_at)
    vals.append(crawler_id)
    conn.execute(f"UPDATE crawlers SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def get_crawler(crawler_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM crawlers WHERE id=?", (crawler_id,)).fetchone()
    return dict(row) if row else None


def list_crawlers():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM crawlers ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def insert_log(crawler_id, message, logged_at):
    conn = get_connection()
    conn.execute(
        "INSERT INTO crawler_logs (crawler_id, message, logged_at) VALUES (?,?,?)",
        (crawler_id, message, logged_at)
    )
    conn.commit()


def get_logs(crawler_id, limit=100):
    conn = get_connection()
    rows = conn.execute(
        "SELECT message, logged_at FROM crawler_logs WHERE crawler_id=? "
        "ORDER BY logged_at DESC LIMIT ?",
        (crawler_id, limit)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── Page / word helpers ────────────────────────────────────────────────────────

def insert_page(url, crawler_id, origin_url, depth, title, word_count, crawled_at):
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO pages
           (url, crawler_id, origin_url, depth, title, word_count, crawled_at)
           VALUES (?,?,?,?,?,?,?)""",
        (url, crawler_id, origin_url, depth, title, word_count, crawled_at)
    )
    conn.commit()


def insert_words_batch(entries):
    """
    entries: list of (word, page_url, crawler_id, origin_url, depth, frequency, tf)
    """
    conn = get_connection()
    conn.executemany(
        """INSERT INTO word_index
           (word, page_url, crawler_id, origin_url, depth, frequency, tf)
           VALUES (?,?,?,?,?,?,?)""",
        entries
    )
    conn.commit()


def get_total_pages():
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as c FROM pages").fetchone()
    return row["c"] if row else 0


def get_pages_with_word(word):
    """Return count of pages containing this word (for IDF)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(DISTINCT page_url) as c FROM word_index WHERE word=?",
        (word,)
    ).fetchone()
    return row["c"] if row else 0


def search_word_index(words, limit=200):
    """
    Fetch word_index rows for the given words.
    Returns list of dicts with tf, frequency, depth, etc.
    """
    if not words:
        return []
    placeholders = ",".join("?" * len(words))
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT wi.word, wi.page_url, wi.crawler_id, wi.origin_url,
                   wi.depth, wi.frequency, wi.tf,
                   p.title
            FROM word_index wi
            LEFT JOIN pages p ON p.url = wi.page_url AND p.crawler_id = wi.crawler_id
            WHERE wi.word IN ({placeholders})
            ORDER BY wi.tf DESC
            LIMIT ?""",
        (*words, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_connection()
    total_pages = conn.execute("SELECT COUNT(*) as c FROM pages").fetchone()["c"]
    total_words = conn.execute("SELECT COUNT(DISTINCT word) as c FROM word_index").fetchone()["c"]
    total_crawlers = conn.execute("SELECT COUNT(*) as c FROM crawlers").fetchone()["c"]
    active_crawlers = conn.execute(
        "SELECT COUNT(*) as c FROM crawlers WHERE status='Active'"
    ).fetchone()["c"]
    return {
        "total_pages": total_pages,
        "total_unique_words": total_words,
        "total_crawlers": total_crawlers,
        "active_crawlers": active_crawlers,
    }


def is_url_visited(url):
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM pages WHERE url=?", (url,)).fetchone()
    return row is not None


def get_visited_urls_set(crawler_id=None):
    """Return set of all visited URLs (optionally filtered by crawler)."""
    conn = get_connection()
    if crawler_id:
        rows = conn.execute("SELECT url FROM pages WHERE crawler_id=?", (crawler_id,)).fetchall()
    else:
        rows = conn.execute("SELECT url FROM pages").fetchall()
    return {r["url"] for r in rows}
