# ADR 002 — Use PostgreSQL + pgvector for embeddings, not LanceDB

**Status:** Accepted  
**Date:** 2026-06-01

## Context

Embedding-based code search requires a vector store. Common options:
1. **pgvector** — Postgres extension, stored alongside relational data
2. **LanceDB** — purpose-built columnar vector store (used by Continue)
3. **Pinecone / Weaviate** — cloud-hosted vector databases

## Decision

We use `pgvector` (via `pgvector/pgvector:pg16` Docker image) as our only vector store. All embeddings live in the `code_embeddings` table alongside relational task/agent data.

## Rationale

- **Single database**: one connection pool, one backup strategy, one schema migration system (`node-pg-migrate`). Adding LanceDB would mean two databases to operate.
- **Joins**: we can join embeddings with `dev_tasks`, `files`, and `agent_runs` in a single query — impossible across DB boundaries
- **Platform compatibility**: LanceDB has CPU-specific native dependencies that fail on some Linux configurations (as noted in Continue's own code: `isSupportedLanceDbCpuTargetForLinux()`)
- **Operational simplicity**: our Docker Compose already runs Postgres; no additional service needed
- **pgvector is production-proven**: used by Supabase, Neon, and others at scale

## Consequences

- We must ensure pgvector is installed (`pgvector/pgvector:pg16` Docker image handles this)
- Cosine similarity queries via `<=>` operator require an `ivfflat` or `hnsw` index at scale
- Voyage AI (`voyage-code-2`) produces 1536-dim vectors — well within pgvector's supported range
- If query latency becomes an issue at scale, we can add an `hnsw` index or migrate specific collections to a dedicated vector DB without touching the rest of the system
