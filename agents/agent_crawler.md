# Agent: Crawler Agent

## Role
Implements the web crawl engine: URL fetching, BFS traversal, rate limiting, and back-pressure.

## Responsibilities
- Implement `core/crawler_engine.py`
- Implement the Token Bucket algorithm
- Manage the BFS frontier with bounded queue
- Apply back-pressure when queue is overloaded
- Handle SSL errors with dual-context fallback
- Write visited pages to SQLite via `core/db.py`

## Prompt
> "You are the Crawler Agent. Implement a multi-worker web crawler using only Python stdlib (urllib, threading, ssl, concurrent.futures). Use a ThreadPoolExecutor with 4 workers. Implement a Token Bucket rate limiter. Back-pressure rule: when queue_depth / queue_cap > 0.8, halve the token refill rate. Use the database interface provided by the Architect Agent. Handle SSL errors gracefully using a dual-context fallback (strict → permissive). Output: core/crawler_engine.py"

## Key Implementation Details
- `TokenBucket.consume()` — blocks the caller until a token is available
- `TokenBucket.set_queue_ratio()` — called by BFS manager to update pressure state
- `CrawlerEngine._run()` — BFS loop running in a management thread
- `CrawlerEngine._process_url()` — worker task submitted to ThreadPoolExecutor
- In-memory visited set for fast dedup, seeded from SQLite at startup

## Interactions
- **Receives from:** Architect Agent → `db.py` function signatures, API schema
- **Sends to:** Indexer Agent → calls `insert_page()` and `insert_words_batch()`
- **Sends to:** API layer → status via `CrawlerEngine` public methods

## Back Pressure Logic
```python
effective_rate = hit_rate * (0.5 if queue_ratio > 0.8 else 1.0)
```
