# MASTER MEMORY AUDIT — Engineering Memory Systems

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.

You are a Principal AI Research Engineer auditing every memory subsystem in
this repository. This project has THREE distinct memory mechanisms — do not
conflate them:

1. **In-process `LessonStore`** (`backend/app/agents/base_graph.py`) — fast,
   ephemeral, process-lifetime-only cache used for lesson injection during a
   live agent run (`memory_hook_node`).
2. **Durable task-outcome embeddings** (`backend/app/memory/store.py`,
   `memory_embeddings` table, pgvector) — semantic search over past task
   outcomes, categorized (`task`/`architecture`/`failure`/`learning` per
   Day 16-era migration).
3. **Versioned lessons** (`backend/app/fleet/versioned_memory.py`,
   `versioned_lessons` table, migration from Day 11) — durable,
   conflict-merging, version-lineage lesson history, separate from #2.

## PHASE 0 — Orientation

Read in full:
- `backend/app/agents/base_graph.py` — `LessonStore`, `get_lesson_store()`,
  `memory_hook_node`, `_extract_and_store_lesson()`
- `backend/app/memory/store.py` — `_embed()`, `embed_task_outcome()`,
  `query_similar_tasks()`, `format_memory_context()`,
  `embed_architecture_note()`, `embed_failure()`,
  `query_architecture_notes()`, `query_failures()`
- `backend/app/fleet/versioned_memory.py` — `publish()`, `rollback()`,
  `archive_expired()`, similarity-merge logic
- `backend/app/api/memory.py` — `/api/memory/patterns`, `/api/memory/search`
- Relevant Alembic migrations for `memory_embeddings` (with `category` +
  `created_at` columns — PROJECT.md documents `created_at` was once missing
  from the ORM model despite existing in the DB, causing a real crash;
  confirm this is still fixed) and `versioned_lessons`.

## PHASE 1 — Correctness Audit

For each of the 3 systems, verify with file:line evidence:

- **Embedding fallback behavior**: what happens with no `VOYAGE_API_KEY`
  configured? Confirm it degrades gracefully (zero-vector or empty-list, not
  a crash) — trace the actual code path, don't assume from PROJECT.md prose.
- **Gating on real key presence**: PROJECT.md documents that
  `versioned_memory.publish()` was deliberately gated on a real
  `VOYAGE_API_KEY` being configured to avoid polluting similarity search
  with zero-vector rows. Confirm this gate is still in place at its call
  site in `_extract_and_store_lesson()`.
- **Similarity query correctness**: confirm the pgvector `<=>` cosine
  distance usage in both `query_similar_tasks()` and
  `versioned_memory`'s merge-detection is querying the correct
  column/table and not accidentally cross-querying the wrong memory system.
- **Merge-on-conflict logic** (`versioned_memory.publish()`): when
  similarity >= `MEMORY_MERGE_SIMILARITY_THRESHOLD`, confirm the described
  lifecycle actually happens in code: V2 inserted as draft → LLM merge call
  → V_merged published → V1 flipped to superseded → V2 flipped to
  merged_into. Trace every state transition against the actual SQL/ORM
  calls.
- **Category correctness**: confirm every `embed_*` call site passes the
  correct `outcome`/`category` value, and that `/api/memory/patterns`'s
  `?category=` filter actually filters (not silently ignored).
- **Retention/archival**: confirm `archive_expired()` (versioned) and the
  generic log-retention service actually run on a schedule
  (`main.py` lifespan loops) — is `LESSON_RETENTION_DAYS` actually read from
  config, not hardcoded?
- **Real callers**: grep for every call site of `embed_task_outcome`,
  `embed_architecture_note`, `embed_failure`, `versioned_memory.publish`,
  `versioned_memory.rollback`. PROJECT.md's gap-closure history shows
  `versioned_memory.publish()` was once built but never called — confirm
  it IS wired now, and check for any OTHER memory function with zero real
  (non-test) callers today.
- **Context injection correctness**: confirm `memory_context` actually
  flows PM → Architect → Decomposer as claimed (trace
  `pipeline/state.py`'s `memory_context` field through `pipeline/graph.py`
  into `pm_node`/`architect_node`'s actual prompt-building code — is it
  really appended to the user message, or just present in state and unused
  by one of the three?).

## PHASE 2 — Memory Isolation & Security

- Can one task's memory query ever leak data that should be scoped
  differently (e.g. cross-tenant if multi-tenant, cross-repo if
  repo-specific)? Check whether `query_similar_tasks`/`versioned_memory`
  queries are scoped by repo/task or global across the whole database.
- Confirm no memory write path can be triggered by untrusted input without
  going through the agent pipeline (i.e. no raw memory-write API endpoint
  reachable without auth).
- Confirm `versioned_memory`'s LLM-merge call uses a bounded, low-cost model
  tier (Haiku per PROJECT.md) and can't be abused to run arbitrary expensive
  generation.

## PHASE 3 — Performance

- Are embedding calls batched or synchronous per-call? What's the real
  latency/cost impact of `_embed()` being called once per lesson extraction
  across every one of the ~72 agents' runs?
- Is there an index on the pgvector columns (HNSW per migration) actually
  present and used, or could similarity queries degrade to full scans as
  data grows? Check the actual migration DDL.
- Any N+1 query pattern in `query_similar_tasks` / `query_architecture_notes`
  / `query_failures` when called in a loop (e.g. per subtask)?

## PHASE 4 — Final Report

1. Executive summary of the 3-system architecture and whether it matches
   PROJECT.md's stated design
2. Correctness findings per system (Critical/High/Medium/Low, file:line)
3. Orphaned/dead memory functions (if any)
4. Isolation/security findings
5. Performance findings
6. Recommended fixes (concrete, file-scoped)
7. Memory Layer Production-Readiness score (0-100)

Do not write code. Do not modify files. Evidence or NOT FOUND only.
