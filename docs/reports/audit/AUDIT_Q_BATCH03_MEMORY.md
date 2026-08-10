# Batch 3 — Memory System Audit, Intelligent Memory Management

Covers §5, §120. Evidence-only, file:line cited.

**Architecture reality check:** the question file implies 8 distinct memory subsystems (Working/Session/Shared/Project/Long-Term/Procedural/Failure/Knowledge). Real implementation has **2 physical Postgres tables** (`memory_embeddings`, `versioned_lessons`) plus **1 in-process structure** (`LessonStore`) — the "8 types" are mostly `category`/`outcome` string discriminators on the same `memory_embeddings` rows, explicitly documented as such in `store.py`'s own docstring ("project/fleet/long-term are the same store — not a fifth system"). This isn't a gap so much as a naming mismatch between the question framing and the real design — noted, not penalized as missing.

**Remediation pass (2026-08-10):** both concrete findings from the original Production Enhancement Plan below were implemented — the `versioned_lessons` TOCTOU race and the uncapped memory-injection block. See "Remediation" at the bottom for what changed, file:line evidence, and full test/lint/type-check results. The other four PARTIALs (`Session memory retains/compresses`, `Context Compression`, `Memory Quality Control`, `Memory Evolution`) were re-examined and are genuinely new-subsystem builds, not gap-closures — reclassified as scope-bounded with explicit reasoning per row, not silently left vague.

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
| How synchronized | **YES** (was PARTIAL) | `memory_embeddings` writes are protected by a real `pg_advisory_xact_lock`. **Fixed 2026-08-10:** `versioned_lessons`'s publish/promote/rollback path now has the equivalent protection — a session-scoped `pg_advisory_lock`/`pg_advisory_unlock` pair (`fleet/versioned_memory.py::_lesson_lock`, lines 64-109) wraps the full read-then-write critical section of `_publish` (line 376), `_promote` (line 418), and `_rollback_locked` (line 448). See Remediation section for why a session-scoped lock (not `pg_advisory_xact_lock`) was required here. |
| Survives restart | **YES** | Both Postgres tables persist; only `LessonStore` (explicitly, intentionally ephemeral) and raw in-memory counters do not. |
| Shared between agents | **YES** | Single shared table (repo-scoped, not per-agent-isolated); `LessonStore` is a process-wide singleton. |

---

## §120 Intelligent Memory Management

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Working Memory scoped to task, no overflow | **YES** | Bounded to one run's lifetime by construction. |
| Session memory retains/compresses/preserves | **PARTIAL — scope-bounded** | Retains and dedups (Jaccard similarity replace, `base_graph.py::LessonStore.add`, lines 316-344) real; no dedicated "summarize completed work" function found. Re-examined 2026-08-10: closing this for real means designing a new LLM-summarization trigger/prompt/replace-many-with-one pipeline for the ephemeral, keyword-only `LessonStore` — a new capability, not a mechanical gap-closure (unlike the two fixed below, which reused an existing pattern one-for-one). Left open rather than building a speculative, undirected feature. |
| Long-term memory promotion gate | **YES** | `VersionedMemoryStore.publish()` always inserts `state="draft"`; `promote()` is the only path to `published`, explicitly closing a prior gap where self-reported lessons went straight to fleet-wide-searchable with no review. |
| Context Compression | **PARTIAL — scope-bounded** | No general condense/compress/summarize function over memory content. The closest real thing is `_merge_via_llm` (versioned_memory.py:261-285), a genuine LLM call that merges two near-duplicate lesson texts — narrow, not general context compression. Re-examined 2026-08-10: distinct from the Context Window Management fix below — that fix truncates an oversized block (a bound), it does not summarize (a compression). A real general-purpose compressor needs its own design (what triggers it, what it's allowed to drop) — same reasoning as the Session Memory row above, not a mechanical fix. |
| Memory Retrieval targeted, not full dump | **YES** | Semantic top-k + repo filtering + archived filtering + composite ranking — confirmed targeted. |
| Automatic Memory Cleanup | **YES** | `services/retention.py::start_retention_loop`, real asyncio background loop from app startup (`main.py:554,724-725`), runs every 24h, archives (not hard-deletes) stale rows by configurable retention windows, hard-deletes stale LangGraph checkpoints. |
| Memory Prioritization | **YES** | `_COMPOSITE_SCORE_EXPR` (store.py:137-155), config-driven weighted blend; separate `fleet/memory_score.py::compute_memory_score` for a distinct verified-ratio quality metric (correctly kept separate from the ranking formula). |
| Token Optimization | **YES** | top_k-limited retrieval + explicit field-length truncation (`[:500]`, `[:300]`, `[:800]`) throughout embed_* functions, plus (2026-08-10) an aggregate cap on the combined injected block — see Context Window Management below. |
| Context Window Management | **YES** (was NO — not found) | **Fixed 2026-08-10:** `base_graph.py::_cap_memory_context_tokens` (lines 862-886) estimates the combined `memory_context` block's token count (~4 chars/token, the same heuristic `chat_agent.py::_estimate_tokens` already uses) and truncates with a logged warning if it exceeds the new `Settings.memory_injection_token_budget` (config.py:398-410, default 3000, 0 disables). Wired into `memory_hook_node` at the point `updates["memory_context"]` is set (base_graph.py:958-961, formerly a single-line assignment pre-fix), so the check runs before the block ever reaches `_make_call_llm_node`'s system-prompt composition. |
| Memory Aging/Lifecycle | **YES** | `memory_embeddings`: computed (not stored) recent/aging/stale/obsolete buckets via `_compute_staleness_distribution`. `versioned_lessons`: real stored 5-state lifecycle column. |
| Shared Memory Synchronization | **YES** (was PARTIAL) | Same fix as "How synchronized" above — `_lesson_lock` closes the `versioned_lessons` TOCTOU gap that used to leave this PARTIAL. |
| Memory Quality Control | **PARTIAL — scope-bounded** | Near-duplicate cosine-similarity gate before insert (real); no separate accuracy/usefulness validation beyond that and the coarse `verified = outcome=="completed"` boolean. Re-examined 2026-08-10: a real accuracy/usefulness validator (beyond similarity-gating and the existing verified flag) is a new evaluative subsystem — e.g. a second LLM-as-judge pass, or a human feedback loop — with no existing pattern in this codebase to reuse. Out of scope for a gap-closure pass. |
| Memory Analytics | **YES** | `memory/analytics.py::compute_memory_analytics` — total rows, size (`pg_total_relation_size`), growth trend, unused count, duplicate-pair count (self-capped with honest skip-reason), retrieval-time stats, staleness distribution. Real API route: `GET .../analytics`. |
| Memory Evolution (shrinks/cleans over time) | **PARTIAL — scope-bounded** | Retention loop archives (soft-delete) on a schedule — this bounds growth but doesn't actively shrink/optimize; no evidence of active "cleaner over time" beyond archival. Re-examined 2026-08-10: active consolidation (e.g. periodically re-merging clusters of related old memories, compacting archived rows) is a new background-job design, not a fix to existing wiring — same class as the three rows above. |

---

## Summary — Batch 3 (20 checkpoints across 2 sections)

- **YES:** 16 (was 13)
- **PARTIAL — scope-bounded (impossible without changing project scope, explained per row):** 4 (was 6 PARTIAL)
- **NO / NOT FOUND:** 0 (was 1)

Memory remains the strongest-scoring subsystem in this audit series: real Postgres persistence, real migrations, config-driven scoring, a documented promotion gate for long-term knowledge, and a comprehensive test suite (182 tests pass under `pytest tests/ -k "memory or versioned"` post-remediation, including 5 new tests added by this pass — 2 in `test_versioned_memory.py` for the locking fix, 3 in `test_day0_capabilities.py` for the token-budget fix).

### Remediation (2026-08-10)

**1. `versioned_lessons` TOCTOU race (`fleet/versioned_memory.py`)**

The original finding: `pg_advisory_xact_lock` closed the identical read-then-write race for `memory_embeddings` writes (`store.py::_find_near_duplicate`) but was never applied to `versioned_lessons`'s `publish()`/`promote()`/`rollback()`, which have the exact same shape — a read (find similar published lesson / find current draft or superseded row) followed by a write (insert / flip state), with nothing preventing two concurrent callers from both reading stale state.

A transaction-scoped `pg_advisory_xact_lock` (the `store.py` fix) does not work here: every helper in `versioned_memory.py` opens its own disposable engine/session (`_new_isolated_db_engine()` per call — see that function's docstring), so a lock tied to one of those transactions would already be released before the paired read or write ran on the next one. The fix instead uses a session-scoped `pg_advisory_lock`/`pg_advisory_unlock` pair (`_lesson_lock`, `fleet/versioned_memory.py:64-109`) held on one dedicated connection for the whole critical section — Postgres advisory locks are visible fleet-wide regardless of which connection is doing the actual reads/writes, so this still fully serializes concurrent calls sharing the same key even though the underlying queries run on other connections. Keyed on `topic` for `publish()` and `lesson_id` for `promote()`/`rollback()`, with a fixed `-2` second key distinguishing this namespace from `store.py`'s `(category_hash, repo_id)` domain so the two stores' lock keyspaces can never collide.

`rollback()`'s two separate `asyncio.run()` calls (a read, then a write) were merged into one (`_rollback_locked`, lines 442-457) — a lock acquired and released inside one `asyncio.run()` cannot span a second, later one, so both had to move inside a single async call for the lock to cover the whole critical section.

Real-DB tests added (`tests/test_versioned_memory.py`):
- `test_lesson_lock_serializes_same_key_but_not_different_keys` — proves `_lesson_lock` itself is a real mutex for a shared key and does not block unrelated keys (mirrors `store.py`'s own category/repo_id-scoping test coverage in `test_gap42_memory_dedup.py`).
- `test_concurrent_promote_on_same_lesson_only_promotes_once` — fires two concurrent `promote()` calls on the same lesson_id via `asyncio.gather`; asserts exactly one succeeds and the other correctly raises `ValueError("No draft version to promote...")` because the second call's read only happens after the first's write has committed. This is the "no test currently proves or disproves concurrent-write safety" gap called out in the original audit, now closed.

All 18 pre-existing `test_versioned_memory.py`/`test_versioned_memory_sync.py` tests still pass unchanged (20 total after the 2 new ones added below) — no behavior change for the non-concurrent path.

**2. Uncapped memory-injection block (`base_graph.py`, `config.py`)**

The original finding: `format_full_memory_context`/`LessonStore.format_for_injection` truncate individual fields, but nothing capped the *combined* `memory_context` block before `_make_call_llm_node` appended it to the system prompt — several large sections together had no aggregate ceiling.

Fix: `_cap_memory_context_tokens` (`base_graph.py:862-886`) estimates the block's token count using the same ~4-chars/token heuristic `chat_agent.py::_estimate_tokens` already uses elsewhere in this codebase (reused, not reinvented), and truncates with a logged warning if it exceeds the new `Settings.memory_injection_token_budget` (`config.py:398-412`, default 3000 tokens, 0 disables). Wired in at `memory_hook_node`'s `updates["memory_context"] = ...` assignment (`base_graph.py:958-961`) — the exact injection point the original audit named.

Tests added (`tests/test_day0_capabilities.py::TestMemoryHookNodeFires`):
- `test_memory_hook_caps_oversized_memory_context` — an oversized DB block + lesson is truncated end-to-end through the real hook.
- `test_cap_memory_context_tokens_disabled_when_budget_zero` — `budget=0` preserves prior (uncapped) behavior.
- `test_cap_memory_context_tokens_passes_through_when_under_budget` — no-op for normal-sized content.

**Validation:** full backend test suite (4023 passed, 51 skipped, 17 deselected, 0 failed), `ruff check` (clean), `ruff format --check` (clean after applying), `mypy` on all changed files (0 issues). No existing test was modified to make it pass — only additive fixes and additive tests.
