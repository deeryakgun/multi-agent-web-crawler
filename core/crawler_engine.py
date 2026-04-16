"""
crawler_engine.py — Multi-worker web crawler with Token Bucket rate limiting.

Key differences from Project 1:
  - Uses concurrent.futures.ThreadPoolExecutor instead of a single Thread
  - Token Bucket algorithm replaces naive time.sleep() for rate control
  - Back pressure: when queue is > 80% full, the bucket refill slows down
  - Stores state in SQLite (via core.db) instead of flat files
  - Global visited-URL deduplication across all crawlers via SQLite
"""

import threading
import time
import queue
import urllib.request
import urllib.parse
import urllib.error
import ssl
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional

from core.db import (
    init_db, insert_crawler, update_crawler_status,
    insert_log, get_visited_urls_set, is_url_visited,
    insert_page, insert_words_batch, get_connection
)
from core.html_parser import parse_html


# ── Token Bucket ──────────────────────────────────────────────────────────────

class TokenBucket:
    """
    Classic token bucket for rate limiting.

    capacity  = max burst = hit_rate * 2 tokens
    refill    = hit_rate tokens/second
    Back-pressure: if queue_depth > 80% of max, refill rate halves.
    """

    def __init__(self, rate: float, capacity: float):
        self._rate = rate          # normal refill rate (tokens/sec)
        self._capacity = capacity
        self._tokens = capacity    # start full
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._queue_ratio = 0.0    # updated externally

    def set_queue_ratio(self, ratio: float):
        """ratio = current_depth / max_depth  (0.0 – 1.0)"""
        self._queue_ratio = max(0.0, min(1.0, ratio))

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        # Apply back-pressure: if queue > 80% full, halve refill speed
        effective_rate = self._rate * (0.5 if self._queue_ratio > 0.8 else 1.0)
        self._tokens = min(self._capacity, self._tokens + elapsed * effective_rate)
        self._last_refill = now

    def consume(self, tokens: float = 1.0):
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
            time.sleep(0.01)


# ── Crawler Engine ────────────────────────────────────────────────────────────

class CrawlerEngine:
    """
    Manages one web-crawl job.

    Uses a ThreadPoolExecutor with up to MAX_WORKERS workers.
    All writes to SQLite go through core.db helpers.
    """

    MAX_WORKERS = 4

    def __init__(self, crawler_id: str, origin: str, max_depth: int,
                 hit_rate: float = 1.0, queue_cap: int = 10_000,
                 max_urls: int = 1_000, resume: bool = False):
        self.crawler_id = crawler_id
        self.origin = origin
        self.max_depth = max_depth
        self.hit_rate = hit_rate
        self.queue_cap = queue_cap
        self.max_urls = max_urls
        self.resume = resume

        # URL frontier: (url, depth)
        self._frontier: queue.Queue = queue.Queue(maxsize=queue_cap)

        # In-memory visited set (pre-loaded from DB for dedup)
        self._visited: set[str] = set()
        self._visited_lock = threading.Lock()

        # Control signals
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()   # start unpaused

        # Rate limiter
        self._bucket = TokenBucket(rate=hit_rate, capacity=hit_rate * 2)

        # Stats
        self._visited_count = 0
        self._dispatched_count = 0
        self._stats_lock = threading.Lock()

        # SSL contexts
        self._ssl_secure = ssl.create_default_context()
        self._ssl_permissive = ssl.create_default_context()
        self._ssl_permissive.check_hostname = False
        self._ssl_permissive.verify_mode = ssl.CERT_NONE

        # Management thread
        self._manager: Optional[threading.Thread] = None
        self._executor: Optional[ThreadPoolExecutor] = None

    # ── Public control API ─────────────────────────────────────────────────

    def start(self):
        init_db()
        self._log("Crawler engine starting")
        if self.resume:
            self._load_state_from_db()
        else:
            self._visited = get_visited_urls_set()   # global dedup
            self._frontier.put((self.origin, 0))

        self._manager = threading.Thread(target=self._run, daemon=True)
        self._manager.start()

    def pause(self):
        self._pause_event.clear()
        self._log("Crawler paused")
        self._sync_status("Paused")

    def resume_crawl(self):
        self._pause_event.set()
        self._log("Crawler resumed")
        self._sync_status("Active")

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()   # unblock if paused
        self._log("Stop requested")

    def is_alive(self) -> bool:
        return self._manager is not None and self._manager.is_alive()

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def queue_depth(self) -> int:
        return self._frontier.qsize()

    def visited_count(self) -> int:
        with self._stats_lock:
            return self._visited_count

    # ── Internal ──────────────────────────────────────────────────────────

    def _load_state_from_db(self):
        """Pre-seed visited set from DB (resume support)."""
        self._visited = get_visited_urls_set()
        self._log(f"Resume: {len(self._visited)} URLs already visited")
        # Re-queue origin if nothing was queued
        if self._frontier.empty():
            self._frontier.put((self.origin, 0))

    def _log(self, message: str):
        ts = time.time()
        print(f"[{self.crawler_id[:12]}] {message}")
        try:
            insert_log(self.crawler_id, message, ts)
        except Exception:
            pass

    def _sync_status(self, status: str, completed: bool = False):
        depth = self._frontier.qsize()
        self._bucket.set_queue_ratio(depth / max(self.queue_cap, 1))
        update_crawler_status(
            self.crawler_id,
            status,
            visited_count=self.visited_count(),
            queue_depth=depth,
            completed_at=time.time() if completed else None,
        )

    def _mark_visited(self, url: str) -> bool:
        """Return True if URL is new (not yet visited)."""
        with self._visited_lock:
            if url in self._visited:
                return False
            self._visited.add(url)
            return True

    # ── Main loop ─────────────────────────────────────────────────────────

    def _run(self):
        self._log("Worker pool starting")
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            self._executor = executor
            futures: list[Future] = []

            while not self._stop_event.is_set():
                # Respect pause
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                # Check URL limit (use dispatched count, not completed,
                # so the 4 workers don't overshoot the limit)
                with self._stats_lock:
                    if self.max_urls > 0 and self._dispatched_count >= self.max_urls:
                        self._log(f"URL limit ({self.max_urls}) reached")
                        break

                # Pull next URL from frontier
                try:
                    url, depth = self._frontier.get(timeout=2)
                except queue.Empty:
                    # If no pending futures either, we're done
                    futures = [f for f in futures if not f.done()]
                    if not futures:
                        break
                    continue

                if depth > self.max_depth:
                    continue

                if not self._mark_visited(url):
                    continue

                # Consume a token (blocks if rate-limited)
                self._bucket.consume()

                # Dispatch to worker thread
                with self._stats_lock:
                    self._dispatched_count += 1
                future = executor.submit(self._process_url, url, depth)
                futures.append(future)

                # Periodically sync status and clean finished futures
                if len(futures) % 10 == 0:
                    futures = [f for f in futures if not f.done()]
                    self._sync_status("Active")

            # Wait for remaining workers
            self._executor = None

        # Determine final status
        if self._stop_event.is_set():
            final_status = "Interrupted"
        else:
            final_status = "Finished"

        self._log(f"Crawler {final_status.lower()}. Visited {self.visited_count()} pages.")
        self._sync_status(final_status, completed=True)

    def _process_url(self, url: str, depth: int):
        """Fetch, parse, index one URL (runs in worker thread)."""
        try:
            html_content = self._fetch(url)
            if html_content is None:
                return

            title, text, child_urls = parse_html(html_content, url)
            word_freq = Counter(re.findall(r"\b[a-zA-Z]{2,}\b", text.lower()))
            total_words = sum(word_freq.values()) or 1

            # TF per word
            entries = [
                (word, url, self.crawler_id, self.origin,
                 depth, freq, freq / total_words)
                for word, freq in word_freq.items()
                if len(word) >= 2
            ]

            insert_page(url, self.crawler_id, self.origin, depth,
                        title, total_words, time.time())
            if entries:
                insert_words_batch(entries)

            with self._stats_lock:
                self._visited_count += 1

            self._log(f"[depth={depth}] {url} → {len(word_freq)} words, {len(child_urls)} links")

            # Enqueue children
            if depth < self.max_depth and not self._stop_event.is_set():
                added = 0
                for child_url in child_urls:
                    with self._visited_lock:
                        already = child_url in self._visited
                    if already:
                        continue
                    try:
                        self._frontier.put_nowait((child_url, depth + 1))
                        added += 1
                    except queue.Full:
                        self._log("Queue full — back pressure active")
                        break

        except Exception as exc:
            self._log(f"Error processing {url}: {exc}")

    def _fetch(self, url: str) -> Optional[str]:
        """Fetch HTML with SSL fallback. Returns None on failure."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AgentCrawler/2.0 (+educational)"},
        )
        for ctx in (self._ssl_secure, self._ssl_permissive):
            try:
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    if resp.status != 200:
                        return None
                    raw = resp.read(1_000_000)   # cap at ~1 MB per page
                    try:
                        return raw.decode("utf-8")
                    except UnicodeDecodeError:
                        return raw.decode("latin-1", errors="replace")
            except ssl.SSLError:
                continue
            except (urllib.error.URLError, urllib.error.HTTPError, Exception):
                return None
        return None


# ── Registry (in-process singleton) ──────────────────────────────────────────

_registry: dict[str, CrawlerEngine] = {}
_registry_lock = threading.Lock()


def register(engine: CrawlerEngine):
    with _registry_lock:
        _registry[engine.crawler_id] = engine


def get_engine(crawler_id: str) -> Optional[CrawlerEngine]:
    with _registry_lock:
        return _registry.get(crawler_id)


def remove_engine(crawler_id: str):
    with _registry_lock:
        _registry.pop(crawler_id, None)


def all_engines() -> dict[str, CrawlerEngine]:
    with _registry_lock:
        return dict(_registry)
