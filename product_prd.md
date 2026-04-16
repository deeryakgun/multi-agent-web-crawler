# Product Requirements Document (PRD)
## Agent Crawler — Multi-Agent Web Crawler & Search System
**Version:** 2.0 | **Date:** April 2026

---

## 1. Overview

This document defines the requirements for a web crawler and full-text search system built using a **multi-agent AI development workflow**. The system is designed to scale to large crawls on a single machine while remaining operationally transparent through a real-time dashboard.

---

## 2. Goals

| # | Goal |
|---|------|
| G1 | Crawl any seed URL up to depth *k*, never revisiting the same URL twice. |
| G2 | Index page content via TF-IDF to support relevance-ranked keyword search. |
| G3 | Return search results as `(relevant_url, origin_url, depth)` triples. |
| G4 | Support live search while indexing is still active. |
| G5 | Apply back-pressure when the system is under load. |
| G6 | Resume a crawl after interruption without starting from scratch. |
| G7 | Provide a single-page UI showing indexing progress, queue depth, and back-pressure status. |

---

## 3. Functional Requirements

### 3.1 Index (Crawling)

**Endpoint:** `POST /index`

**Input:**
```json
{
  "origin": "https://en.wikipedia.org/wiki/Web_crawler",
  "k": 2,
  "hit_rate": 2.0,
  "queue_cap": 5000,
  "max_urls": 200
}
```

**Behaviour:**
- BFS traversal from `origin` up to depth `k`.
- URL deduplication via a global in-memory set (seeded from SQLite on startup).
- `hit_rate` controls the Token Bucket refill rate (requests/second).
- `queue_cap` sets the maximum BFS frontier size (back-pressure trigger).
- `max_urls` caps the total pages visited per job.
- Worker threads: up to 4 concurrent fetch workers per job (`ThreadPoolExecutor`).

**Back-pressure rule:**  
When `queue_depth / queue_cap > 0.8`, the Token Bucket refill rate is halved automatically. The UI shows a "High Load" badge.

**Response:**
```json
{ "crawler_id": "...", "status": "Active", "origin": "...", "max_depth": 2 }
```

### 3.2 Crawl Job Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/index/<id>/status`  | GET  | Status + logs + queue metrics |
| `/index/<id>/pause`   | POST | Pause BFS traversal |
| `/index/<id>/resume`  | POST | Resume paused job |
| `/index/<id>/stop`    | POST | Graceful shutdown |
| `/index/list`         | GET  | All jobs with live metrics |
| `/index/stats`        | GET  | Global stats |
| `/index/clear`        | POST | Wipe all data |

### 3.3 Search

**Endpoint:** `GET /search?query=<q>&page_limit=10&page_offset=0&sort_by=relevance`

**Behaviour:**
- Tokenise query (lower-case, alpha-only words ≥ 2 chars).
- Compute TF-IDF score per result page:
  - TF = `frequency / total_words` (stored at crawl time)
  - IDF = `log( (N+1) / (df+1) ) + 1`  (smoothed)
  - Depth bonus: `score *= 1 / (1 + depth * 0.1)`
  - Exact match multiplier: `× 1.5`
- Return list of `{ relevant_url, origin_url, depth, score, title }`.
- Results are paginated (`page_limit`, `page_offset`).
- Live: SQLite WAL mode allows concurrent reads during active indexing.

**Autocomplete:** `GET /search/suggest?q=<prefix>` — returns up to 8 matching words.

---

## 4. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Throughput  | Up to 20 req/sec with default settings |
| Concurrency | 4 worker threads per crawler |
| Storage     | SQLite with WAL journal (no extra services) |
| Scalability | Designed for single-machine, large-scale crawls |
| Resumability | Crawl state persisted in SQLite; resume by re-seeding from DB |
| Port        | 3700 (separate from Project 1's 3600) |

---

## 5. Data Model (SQLite)

```sql
crawlers   (id, origin, max_depth, hit_rate, queue_cap, max_urls,
            status, visited_count, queue_depth, created_at, updated_at, completed_at)

pages      (url PK, crawler_id FK, origin_url, depth, title,
            word_count, crawled_at)

word_index (id, word, page_url, crawler_id, origin_url,
            depth, frequency, tf)

crawler_logs (id, crawler_id FK, message, logged_at)
```

---

## 6. Technology Constraints

- **Language**: Python 3.10+
- **Framework**: Flask (minimal, API + static file serving)
- **Libraries**: Python stdlib only for crawling/parsing (`urllib`, `html.parser`, `sqlite3`, `threading`, `concurrent.futures`)
- **Frontend**: Vanilla HTML/CSS/JS (no frameworks)
- **Database**: SQLite (local, no external services)
- **Deployment**: Localhost

---

## 7. Success Criteria

1. `POST /index` with a Wikipedia URL crawls at least 50 pages without errors.
2. `GET /search?query=python` returns ranked results while indexing is running.
3. Stopping and restarting the server and calling `POST /index` with `"resume": true` continues without re-crawling visited pages.
4. Dashboard shows live queue depth and back-pressure badge.
5. All documentation files are present and accurate.
