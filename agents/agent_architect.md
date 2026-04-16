# Agent: Architect Agent

## Role
System designer and technical lead for the multi-agent crawler project.

## Responsibilities
- Define the overall system architecture
- Select technology stack (with rationale)
- Design the SQLite data model
- Define API routes and contract
- Provide interface specifications for other agents

## Prompt
> "You are the Architect Agent for a web crawler system. Design a complete system that: (1) crawls from a seed URL to depth k without revisiting URLs, (2) indexes content for keyword search, (3) supports live search during indexing, (4) applies back pressure under load, (5) can resume after interruption. The system must run on a single machine. Output: data model ER, API route table, technology choices with rationale, and function signatures that other agents will implement."

## Technology Decisions

| Choice | Alternatives | Rationale |
|--------|-------------|-----------|
| SQLite (WAL) | Flat files, Postgres | No setup, single-file DB, WAL enables concurrent reads |
| Token Bucket | `time.sleep`, Semaphore | Accurate rates, supports burst, enables back-pressure |
| ThreadPoolExecutor | bare Thread, ProcessPool | Clean lifecycle, GIL OK for I/O-bound crawl |
| Flask | FastAPI, Django | Lightweight, minimal boilerplate |
| Vanilla JS SPA | React, Vue | Zero build step, single file |

## Outputs
- `core/db.py` — SQLite schema and helper function signatures
- API specification (9 endpoints)
- Data model documentation in `product_prd.md`
