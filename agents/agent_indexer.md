# Agent: Indexer Agent

## Role
Designs and implements the indexing pipeline: HTML parsing, TF computation, and efficient SQLite writes.

## Responsibilities
- Define and review `core/html_parser.py`
- Design the word indexing strategy (TF computation)
- Design the SQLite write strategy (batch INSERT)
- Ensure concurrent writes are safe
- Advise on denormalization vs. normalization trade-offs

## Prompt
> "You are the Indexer Agent. Design the pipeline that transforms raw HTML into searchable data. Define: (1) how text is extracted from HTML using only Python's html.parser, (2) how TF (term frequency) is computed, (3) how data is written to SQLite efficiently under concurrent load. Produce the word_index schema and the batch write function. Input: Architect Agent's data model."

## Key Decisions

### TF Computation
```
TF(word, page) = frequency(word, page) / total_words(page)
```
Stored in `word_index.tf` at crawl time. IDF computed at query time.

### Batch Write Strategy
Use `executemany()` for all words in a page as a single transaction:
- Before: 1 INSERT per word → 500+ transactions per page
- After: 1 `executemany()` per page → 1 transaction

### Denormalization Decision
`origin_url` and `depth` are stored on each `word_index` row.
- **Pro:** No JOIN needed at search time
- **Con:** Storage overhead
- **Decision by human:** Accept storage overhead for query simplicity

## Critique Delivered to Crawler Agent
"Workers were writing one word at a time. Switched to `insert_words_batch()` with executemany()."

## Outputs
- `core/html_parser.py` — title extraction, text extraction, link resolution
- `core/db.py` `insert_words_batch()` function
- `word_index` schema review
