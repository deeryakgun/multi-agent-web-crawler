# Multi-Agent Workflow
## Multi-Agent Crawler — Agent Collaboration Log

---

## Overview

The development of Agent Crawler v2 was structured as a **five-agent pipeline**, where each agent owned a specific vertical of the system. Agents communicated through structured PRD sections, interface contracts (function signatures, API schemas), and iterative critique-and-revise loops. The human developer acted as **Product Owner**: approving designs, resolving conflicts between agent proposals, and making final technology decisions.

```
┌─────────────────────────────────────────────────────┐
│                   Product Owner (Human)             │
│   Approves PRD · Resolves conflicts · Merges output │
└──────┬──────────────────────────────────────────────┘
       │
  ┌────▼────┐      ┌──────────┐     ┌──────────┐
  │Architect│─────▶│ Crawler  │────▶│ Indexer  │
  │  Agent  │      │  Agent   │     │  Agent   │
  └─────────┘      └──────────┘     └────┬─────┘
       │                                 │
  ┌────▼────┐      ┌──────────┐          │
  │  Search │◀─────│   UI     │◀─────────┘
  │  Agent  │      │  Agent   │
  └─────────┘      └──────────┘
```

---

## Agent 1 — Architect Agent

**Responsibility:** System design, technology selection, data model, API contract.

**Prompt given:**
> "Design a web crawler and search system for a single machine. Requirements: no duplicate crawls, configurable depth k, back pressure via queue depth, live search while indexing. Choose storage and define the data model. Output: ER diagram, API route table, and technology rationale."

**Key decisions made:**
- Selected **SQLite + WAL mode** over flat files to enable concurrent reads (live search) with atomic writes.
- Proposed **Token Bucket** over `time.sleep()` for more accurate rate control with burst allowance.
- Defined the API using `/index` (not `/crawler/create`) to match the assignment's exact terminology.
- Chose `concurrent.futures.ThreadPoolExecutor` over bare threads for cleaner lifecycle management.

**Output delivered to other agents:**
- SQLite schema (4 tables: `crawlers`, `pages`, `word_index`, `crawler_logs`)
- API route table (9 endpoints)
- Interface contracts: `db.py` function signatures

**Human decision:** Approved SQLite over PostgreSQL for the single-machine constraint. Approved Token Bucket design.

---

## Agent 2 — Crawler Agent

**Responsibility:** Implement `core/crawler_engine.py` — fetch, rate-limit, BFS, back-pressure.

**Prompt given:**
> "Implement a multi-worker web crawler using Python stdlib only (urllib, threading, ssl). Use the Token Bucket algorithm for rate limiting. Implement back-pressure: when queue depth exceeds 80% of capacity, halve the token refill rate. Workers should be managed by ThreadPoolExecutor. Input: Architect Agent's db.py contracts and API schema."

**Key decisions made:**
- Implemented `TokenBucket.set_queue_ratio()` so the BFS manager thread can update pressure state without locking.
- Used `queue.put_nowait()` with `except queue.Full` for non-blocking enqueue, logging "back pressure active" when hit.
- Applied dual SSL context fallback (strict → permissive) identical to Project 1 but refactored for engine class.
- URL deduplication uses both an in-memory set (fast path) guarded by `threading.Lock` and SQLite (persistence).

**Critique received from Indexer Agent:** "Workers write to SQLite per-word — this causes too many small transactions."  
**Resolution:** Crawler Agent switched to `insert_words_batch()` which uses a single `executemany()` per page.

**Output delivered:** `core/crawler_engine.py`, updated `core/db.py` with batch insert.

---

## Agent 3 — Indexer Agent

**Responsibility:** TF computation, SQLite write strategy, data integrity.

**Prompt given:**
> "Design the indexing pipeline: given raw HTML, compute TF (term frequency) per word, and write to SQLite efficiently. The system must support concurrent writers. Propose a batch write strategy and define the word_index schema."

**Key decisions made:**
- TF computed as `frequency / total_words` at crawl time and stored in `word_index.tf` — avoids recomputation at query time.
- IDF is computed at query time (not stored) so it always reflects the current state of the index.
- Recommended `executemany()` for batch inserts (one transaction per page vs. one per word).
- Noted that storing `origin_url` and `depth` on each `word_index` row denormalizes data but avoids JOIN overhead at search time.

**Critique received from Search Agent:** "IDF at query time is fine for correctness but will be slow for large indexes."  
**Resolution:** Human decided to keep on-the-fly IDF for correctness, accepting the performance trade-off at this scale.

**Output delivered:** `core/db.py` `insert_words_batch()`, finalized `word_index` schema.

---

## Agent 4 — Search Agent

**Responsibility:** Implement `core/search_engine.py` — TF-IDF ranking, pagination, live search.

**Prompt given:**
> "Implement TF-IDF search over the word_index SQLite table. IDF should be computed per query. Apply a depth bonus (shallower pages rank higher). Support pagination. Return results as (relevant_url, origin_url, depth) triples. The search must work while indexing is active."

**Key decisions made:**
- Used smoothed IDF formula: `log((N+1)/(df+1)) + 1` to avoid zero IDF for very common words.
- Depth factor: `1 / (1 + depth * 0.1)` — a crawl-depth of 5 reduces score by ~33%.
- Exact query-word match gets ×1.5 multiplier to prioritise literal results over stem matches.
- Autocomplete via `LIKE prefix%` SQL query — simple and fast with the index on `word`.

**Critique received from Architect Agent:** "The suggest endpoint scans the full index — add a covering index."  
**Resolution:** `CREATE INDEX idx_word ON word_index(word)` already in schema; confirmed sufficient.

**Output delivered:** `core/search_engine.py`, `api/search_routes.py`.

---

## Agent 5 — UI Agent

**Responsibility:** Design and implement `frontend/index.html` — single-page dashboard.

**Prompt given:**
> "Build a single HTML file (no frameworks, no build step) that serves as the complete UI for the crawler system. Must include: new crawl form, live job list with queue depth progress bar and back-pressure indicator, real-time stats, and a TF-IDF search interface with autocomplete and pagination. Use a dark modern aesthetic."

**Key decisions made:**
- Single `.html` file served by Flask's `send_from_directory` — zero build tooling.
- Polling interval: 3 seconds (balance between freshness and request load).
- Back-pressure shown as a red "High Load" badge + progress bar colour change (green → yellow → red).
- Suggest dropdown uses `GET /search/suggest` with 250 ms debounce.
- Collapsed log terminal per job (opens on demand) to avoid UI clutter.

**Critique received from Human:** "Make the queue meter show the percentage and absolute numbers."  
**Resolution:** Updated meter label to show `X% of Y,000` format.

**Output delivered:** `frontend/index.html`.

---

## Interaction Summary

| Step | From → To | Artifact |
|------|-----------|----------|
| 1 | Human → Architect | Requirements briefing |
| 2 | Architect → All | Schema, API routes, technology choices |
| 3 | Crawler → Indexer | Calls DB write functions |
| 4 | Indexer → Crawler | Batch write contract |
| 5 | Indexer → Search | `word_index` schema |
| 6 | Search → UI | API response shapes |
| 7 | UI → Human | Dashboard demo |
| 8 | Human → All | Final review + approval |

---

## Design Decisions by Human

| Decision | Options Considered | Chosen | Reason |
|----------|-------------------|--------|--------|
| Storage | Flat files, SQLite, Postgres | SQLite | Single-machine, no extra services |
| IDF timing | Pre-computed, query-time | Query-time | Always reflects latest index |
| Concurrency model | Single thread, process pool, thread pool | Thread pool (4 workers) | GIL-friendly for I/O-bound crawl |
| Rate limiting | sleep(), semaphore, token bucket | Token bucket | Accurate burst + back-pressure |
| UI | Multi-page, React SPA, Vanilla SPA | Vanilla SPA | No build step, single file |
| Resume | Queue file, full re-crawl, SQLite | SQLite | Atomic, always consistent |
