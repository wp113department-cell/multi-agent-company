# Batch 3 — Memory System Audit, Intelligent Memory Management

Covers §5, §120. Evidence-only, file:line cited.

**Architecture reality check:** the question file implies 8 distinct memory subsystems (Working/Session/Shared/Project/Long-Term/Procedural/Failure/Knowledge). Real implementation has **2 physical Postgres tables** (`memory_embeddings`, `versioned_lessons`) plus **1 in-process structure** (`LessonStore`) — the "8 types" are mostly `category`/`outcome` string discriminators on the same `memory_embeddings` rows, explicitly documented as such in `store.py`'s own docstring ("project/fleet/long-term are the same store — not a fifth system"). This isn't a gap so much as a naming mismatch between the question framing and the real design — noted, not penalized as missing.

---

## §5 Memory System Audit

| Memory type | Verdict | Storage | Evidence |
|---|---|---|---|
| Working Memory | **YES** | In-process `AgentRunState` (per LangGraph run) | `base_graph.py:165`, scoped to one `run_agent_graph()` call. |
| Session Memory | **YES** | In-process singleton `LessonStore` | `base_graph.py:267-368`, thread-safe (`Lock`), Jaccard-dedup on add, FIFO eviction at capacity. Cleared on restart. |
| Shared Memory | **YES** | Postgres `memory_embeddings` (pgvector) | All agents read/write the same table via `query_memory_context_sync`. |
| Project Memory | **YES** | Same table, `repo_id`-scoped | Migration `024_memory_project_scoping.py`. |
| Long-Term Memory | **YES** | Same table, unscoped rows | Not architecturally distinct from project memory per the code's own docstring. |
| Procedural Memory | **YES** | Same table, `category="procedure"` | `embed_procedure`/`query_procedures` (store.py:1068-1223). |
| Failure Memory | **YES** | Same table, `outcome="failure"` | `embed_failure`/`query_failures` (store.py:749-876). |
| Knowledge Memory | **YES** | `category="learning"` + separate `versioned_lessons` lifecycle table | Draft→Published→Superseded/Merged→Archived state machine (`fleet/versioned_memory.py`). |

| Question | Verdict | Evidence |
|---|---|---|
| Where stored | **YES** | Real Postgres schema: `memory_embeddings` (db/models.py:519-559), `versioned_lessons` (db/models.py:664-694+), both with real Alembic migrations (010, 014, 020-022, 024, 026). |
| How updated | **YES** | `embed_task_outcome`/`embed_failure`/`embed_architecture_note`/`embed_learning_signal`/`embed_procedure`, universal hook `record_agent_run_outcome` (memory/hooks.py:50-137) called from `main.py:397,444` and `api/specialized_agents.py`. |
| How retrieved | **YES** | pgvector cosine search + composite ranking (similarity + recency decay + reuse_count + importance + verified), all weights config-driven. Real caller: `memory_hook_node` on every agent run. |
| How synchronized | **PARTIAL** | `memory_embeddings` writes are protected by a real `pg_advisory_xact_lock` closing a documented TOCTOU race. **`versioned_lessons`'s publish/promote/rollback path has the identical read-then-write shape but no lock found** — the fix applied to one store was not applied to the other. |
| Survives restart | **YES** | Both Postgres tables persist; only `LessonStore` (explicitly, intentionally ephemeral) and raw in-memory counters do not. |
| Shared between agents | **YES** | Single shared table (repo-scoped, not per-agent-isolated); `LessonStore` is a process-wide singleton. |

---

## §120 Intelligent Memory Management

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Working Memory scoped to task, no overflow | **YES** | Bounded to one run's lifetime by construction. |
| Session memory retains/compresses/preserves | **PARTIAL** | Retains and dedups (Jaccard similarity replace) real; no dedicated "summarize completed work" function found. |
| Long-term memory promotion gate | **YES** | `VersionedMemoryStore.publish()` always inserts `state="draft"`; `promote()` is the only path to `published`, explicitly closing a prior gap where self-reported lessons went straight to fleet-wide-searchable with no review. |
| Context Compression | **PARTIAL** | No general condense/compress/summarize function over memory content. The closest real thing is `_merge_via_llm` (versioned_memory.py:261-280), a genuine LLM call that merges two near-duplicate lesson texts — narrow, not general context compression. |
| Memory Retrieval targeted, not full dump | **YES** | Semantic top-k + repo filtering + archived filtering + composite ranking — confirmed targeted. |
| Automatic Memory Cleanup | **YES** | `services/retention.py::start_retention_loop`, real asyncio background loop from app startup (`main.py:554,724-725`), runs every 24h, archives (not hard-deletes) stale rows by configurable retention windows, hard-deletes stale LangGraph checkpoints. |
| Memory Prioritization | **YES** | `_COMPOSITE_SCORE_EXPR` (store.py:137-155), config-driven weighted blend; separate `fleet/memory_score.py::compute_memory_score` for a distinct verified-ratio quality metric (correctly kept separate from the ranking formula). |
| Token Optimization | **YES** | top_k-limited retrieval + explicit field-length truncation (`[:500]`, `[:300]`, `[:800]`) throughout embed_* functions. |
| Context Window Management | **NO — not found** | No code checks total token usage against a limit and reacts (warn/summarize/archive) in the memory modules. |
| Memory Aging/Lifecycle | **YES** | `memory_embeddings`: computed (not stored) recent/aging/stale/obsolete buckets via `_compute_staleness_distribution`. `versioned_lessons`: real stored 5-state lifecycle column. |
| Shared Memory Synchronization | **PARTIAL** | See §5 above — one store fixed, the other not. |
| Memory Quality Control | **PARTIAL** | Near-duplicate cosine-similarity gate before insert (real); no separate accuracy/usefulness validation beyond that and the coarse `verified = outcome=="completed"` boolean. |
| Memory Analytics | **YES** | `memory/analytics.py::compute_memory_analytics` — total rows, size (`pg_total_relation_size`), growth trend, unused count, duplicate-pair count (self-capped with honest skip-reason), retrieval-time stats, staleness distribution. Real API route: `GET .../analytics`. |
| Memory Evolution (shrinks/cleans over time) | **PARTIAL** | Retention loop archives (soft-delete) on a schedule — this bounds growth but doesn't actively shrink/optimize; no evidence of active "cleaner over time" beyond archival. |

---

## Summary — Batch 3 (20 checkpoints across 2 sections)

- **YES:** 13
- **PARTIAL:** 6
- **NO / NOT FOUND:** 1

This is the strongest-scoring batch so far — memory is a genuinely mature subsystem: real Postgres persistence, real migrations, config-driven scoring, a documented promotion gate for long-term knowledge, and 21 test files with substantial (not stub) test counts.

**One finding worth flagging:** the TOCTOU race fix (`pg_advisory_xact_lock`) applied to `memory_embeddings` writes was not applied to `versioned_lessons`'s publish/promote/rollback path, which has the identical read-then-write shape. Since `versioned_lessons` governs what becomes fleet-wide "published" knowledge, a race here has higher blast radius than a duplicate task-outcome row.

**Production Enhancement Plan:** Add the same `pg_advisory_xact_lock(hashtext(:lesson_id or :topic)::int, repo_id)` pattern to `VersionedMemoryStore.publish()`/`promote()` that `store.py::_find_near_duplicate` already uses — same fix, second location. Also add an explicit token-budget check (e.g. tiktoken/Anthropic token counting against `Settings.model_context_limit`) in `memory_hook_node` before injecting retrieved context into the system prompt, since none of the retrieval/composition path currently guards against the injected memory block itself contributing to a context overflow.
