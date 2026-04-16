# Agent: Search Agent

## Role
Implements the TF-IDF search engine and the search API endpoints.

## Responsibilities
- Implement `core/search_engine.py`
- Implement `api/search_routes.py`
- Define IDF formula and scoring logic
- Implement depth bonus and exact-match multiplier
- Implement pagination
- Implement autocomplete (`/search/suggest`)

## Prompt
> "You are the Search Agent. Implement TF-IDF search over the word_index SQLite table. TF is already stored; compute IDF at query time. Use smoothed IDF: log((N+1)/(df+1))+1. Add a depth bonus: score *= 1/(1 + depth*0.1). Exact query-word match gets a ×1.5 multiplier. Support pagination (page_limit, page_offset). Implement autocomplete via LIKE prefix search. The search must work concurrently with active indexing (SQLite WAL mode handles this). Output: core/search_engine.py and api/search_routes.py"

## Scoring Formula
```
TF-IDF(w, d) = TF(w, d) × IDF(w)
IDF(w) = log( (N+1) / (df(w)+1) ) + 1   [smoothed]
depth_factor = 1 / (1 + depth × 0.1)
exact_bonus = 1.5 if word in query_words else 1.0

final_score(d) = Σ TF-IDF(w,d) × exact_bonus(w) × depth_factor(d)
```

## Live Search
SQLite WAL mode: read transactions see a consistent snapshot and never block crawler write transactions. No additional locking required.

## Critique Received from Architect Agent
"Autocomplete needs the idx_word index."
**Response:** Index already defined in `db.py` init script. Confirmed safe.

## Outputs
- `core/search_engine.py` — full TF-IDF implementation
- `api/search_routes.py` — `/search` and `/search/suggest` endpoints
