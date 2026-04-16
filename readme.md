# Agent Crawler v2 — README
## Multi-Agent Crawler — Web Crawler & Search System

---

## 🚀 Quick Start

```bash
# 1. Navigate to the project
cd multi-agent-crawler

# 2. Install the single dependency
pip install flask

# 3. Start the server
python app.py

# 4. Open your browser
open http://localhost:3700
```

---

## 🏗️ Architecture Overview

```
multi-agent-crawler/
├── app.py                    # Flask entry point (port 3700)
├── api/
│   ├── crawler_routes.py     # /index endpoints
│   └── search_routes.py      # /search endpoints
├── core/
│   ├── db.py                 # SQLite layer (WAL mode)
│   ├── html_parser.py        # Native HTML parser (no BeautifulSoup)
│   ├── crawler_engine.py     # ThreadPoolExecutor + Token Bucket
│   └── search_engine.py      # TF-IDF scoring
├── frontend/
│   └── index.html            # Single-page dark-mode dashboard
├── agents/                   # Multi-agent workflow descriptions
├── data/
│   └── crawler.db            # SQLite database (auto-created)
├── product_prd.md
├── readme.md
├── recommendation.md
└── multi_agent_workflow.md
```

---

## 🔧 How It Works

### Indexing (`/index`)

1. A `POST /index` request creates a new `CrawlerEngine` instance.
2. The engine puts the origin URL into a bounded BFS frontier (`queue.Queue`).
3. Up to **4 worker threads** (via `ThreadPoolExecutor`) fetch pages concurrently.
4. Each fetch is rate-limited by a **Token Bucket**:
   - Normal: `hit_rate` tokens/second.
   - Back-pressure mode (queue > 80% full): refill rate halves automatically.
5. Each page is parsed with the native `html.parser`, text is tokenized, and **TF** is computed per word.
6. Results are written atomically to SQLite (`pages` + `word_index` tables).
7. Child URLs are enqueued for the next depth level.
8. State persists in SQLite — the server can be restarted and crawls resumed.

### Searching (`/search`)

1. Query is lower-cased and split into tokens.
2. Matching rows are fetched from `word_index` (indexed column).
3. **IDF** is computed on-the-fly: `log((N+1)/(df+1)) + 1`.
4. Final score = `TF × IDF × exact_match_bonus × depth_factor`.
5. Results are sorted and paginated.
6. Because SQLite runs in **WAL mode**, search reads never block crawler writes — live search works out of the box.

### Back Pressure

| Condition | Behaviour |
|-----------|-----------|
| Queue < 50% | Normal token refill (`hit_rate` req/s) |
| Queue 50–80% | Normal refill, warning colour in UI |
| Queue > 80% | Refill rate halved; "High Load" badge in UI |
| Queue full | `put_nowait()` raises `queue.Full`; new URLs skipped |

---

## 📡 API Reference

### Indexing

```bash
# Start a crawl
POST /index
{
  "origin": "https://en.wikipedia.org/wiki/Web_crawler",
  "k": 2,
  "hit_rate": 2.0,
  "queue_cap": 5000,
  "max_urls": 200,
  "resume": false
}

# Status (includes logs + queue metrics)
GET /index/<crawler_id>/status

# Controls
POST /index/<crawler_id>/pause
POST /index/<crawler_id>/resume
POST /index/<crawler_id>/stop

# List all jobs
GET /index/list

# Global statistics
GET /index/stats

# Reset everything
POST /index/clear
```

### Search

```bash
# TF-IDF search  (sort_by: relevance | frequency | depth)
GET /search?query=python&page_limit=10&page_offset=0&sort_by=relevance

# Autocomplete
GET /search/suggest?q=py
```

**Search result format:**
```json
{
  "relevant_url": "https://...",
  "origin_url":   "https://...",
  "depth":        1,
  "score":        0.4821,
  "title":        "Page title",
  "frequency":    17
}
```

---

## 🛠️ Key Differences vs Project 1

| Feature | v1 | v2 (Multi-Agent) |
|---------|-----------|-----|
| Storage | Flat `.data` files (by letter) | SQLite with WAL |
| Search | Prefix matching + frequency | TF-IDF + depth bonus |
| Rate limiting | `time.sleep()` | Token Bucket algorithm |
| Concurrency | 1 thread/crawler | ThreadPoolExecutor (4 workers) |
| UI | 3 separate HTML files | Single-page dashboard |
| Resume | Queue file deserialization | SQLite state restoration |
| Live search | Possible (file-based) | Guaranteed (WAL mode) |

---

## 🧪 Testing

```bash
# Start a small test crawl
curl -X POST http://localhost:3700/index \
  -H "Content-Type: application/json" \
  -d '{"origin":"https://en.wikipedia.org/wiki/Web_crawler","k":2,"hit_rate":2,"max_urls":30}'

# Check status (replace <ID> with returned crawler_id)
curl http://localhost:3700/index/<ID>/status

# Search while crawling
curl "http://localhost:3700/search?query=hyperlink&page_limit=5"

# Global stats
curl http://localhost:3700/index/stats
```

---

## 🔁 Resume After Interruption

The crawler writes every visited page and every indexed word to SQLite **before** moving to the next URL. If the server is killed:

```bash
# Restart the server
python app.py

# Resume the original crawl (pass resume: true)
curl -X POST http://localhost:3700/index \
  -H "Content-Type: application/json" \
  -d '{"origin":"<same-origin>","k":2,"resume":true}'
```

The engine pre-loads all previously visited URLs from SQLite and skips them, continuing from where it left off.

---

## 📜 License

MIT License.
