# Audit 03: Master Memory Audit

**Spec:** `files/Audit/03_MASTER_MEMORY_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_03_MEMORY.json`

## Result

🟢 **GREEN: the memory code is correct, safe and well-guarded, and live semantic memory is now proven end to end with a real `VOYAGE_API_KEY` (added 2026-09-29).**

**Memory layer score: 94 / 100.** No code defect was found in the three memory systems. Live check (`evidence/live_memory_probe.py`, real Voyage embeddings, real Postgres): 3/3 memories stored with real 1,536-dim vectors; the query *"users cannot sign in, the authentication token endpoint is broken"* ranked the JWT-login memory first (similarity 0.782 vs 0.762 / 0.755); repo B could not see repo A's memories; test rows cleaned up.

Two non-blocking notes:
1. **Owner action (agreed): add a card at dashboard.voyageai.com.** Without one, the account is limited to 3 requests/minute (the 200M free tokens still apply after adding it). At that limit, most embeddings under real load fall back to "no memory", which is graceful but loses value.
2. The versioned-lesson **LLM merge** step also needs Anthropic credit, so its live check stays in `PENDING_TESTS_API_KEYS.md` L3. The code path and its tests were verified.

## The three memory systems (matches the design)

| System | Where | What it is | Verified |
|---|---|---|---|
| In-process `LessonStore` | `app/agents/base_graph.py` | Fast, per-process lesson cache injected by `memory_hook_node` during a run | ✅ bounded, with LLM compression at capacity (Task 2 #88) |
| Task memory (pgvector) | `app/memory/store.py`, `memory_embeddings` | Semantic search over past tasks, failures, learnings, procedures, preferences, bugs and prompt changes (7 categories) | ✅ |
| Versioned lessons | `app/fleet/versioned_memory.py`, `versioned_lessons` | Durable lesson history with draft → published → superseded / merged_into → archived | ✅ |

## Correctness checks

| Audit question | Answer, with evidence |
|---|---|
| No `VOYAGE_API_KEY`: crash? | ✅ No. `_embed()` returns a zero vector (`store.py:392-394`); every `query_*` returns `[]` on a zero vector without touching the DB (`store.py:608-610`). A transient provider error retries with backoff before falling back (`store.py:397-423`), and `reembed_zero_vector_rows()` repairs rows later. |
| Versioned publish gated on a real key? | ✅ Still in place: `base_graph.py:3085` `if _get_settings().voyage_api_key:` |
| Similarity queries hit the right table/column? | ✅ `query_similar_tasks` → `memory_embeddings.embedding <=>` (`store.py:622-631`); versioned merge detection → `versioned_lessons`, published rows only (`versioned_memory.py:115`). No cross-querying. |
| Merge-on-conflict lifecycle | ✅ and **safer than the spec describes**: `publish()` never publishes directly. A new or merged lesson is always inserted as a **draft** (`versioned_memory.py:626-652`); only `promote()`, reachable only after a human approves the curation on the Fleet dashboard, flips the old version to `superseded` and the draft to `published` (`:672-679`). |
| Merge model tier | ✅ Haiku tier: `_merge_via_llm(..., get_settings().model_router)` (`versioned_memory.py:640`). |
| Retention / archival scheduled? | ✅ `_versioned_lesson_archive_loop` runs in the lifespan under leader election (`main.py:220-240, 1632`); window is `LESSON_RETENTION_DAYS` from config (`config.py:1683`). |
| Real callers | ✅ `query_similar_tasks` (pipeline `graph.py:257`, API, tool); `query_memory_context(_sync)` (chat `chat_agent.py:1227`, every agent run `base_graph.py:1570`); `versioned_memory.publish` (`base_graph.py:3090`), `promote` (curator tool), `rollback` (`api/memory.py:222`), `archive_expired` (`main.py:234`). |
| `memory_context` really reaches PM → Architect → Decomposer? | ✅ Built once in `pipeline/graph.py:245-285`, then placed in each node's actual user message: `pm.py:156`, `architect.py:160`, `decomposer.py:159`. |

## Isolation and security

| Check | Result |
|---|---|
| Cross-repo leakage | ✅ Every production read passes `repo_id`: pipeline (`graph.py:257`), chat (`chat_agent.py:1227`, resolved at session creation), every agent run (`base_graph.py:1570`, resolved once at entry). Repo A's scoped rows never appear for repo B; unscoped legacy rows are shared on purpose as general knowledge (`store.py:573-580`). |
| The one unscoped reader | `memory_search` tool: only `knowledge_curator` is offered it (runtime scorecard), and its job is fleet-wide curation. By design. |
| Unauthenticated memory writes | ✅ None. `POST /api/memory/lessons/{id}/rollback` needs approver (`api/memory.py:203`); `POST /api/memory/{id}/feedback` needs an authenticated user (`:252`). No raw "write a memory" endpoint exists. |

## Performance

| Check | Result |
|---|---|
| HNSW indexes present in the live DB | ✅ `memory_embeddings_embedding_hnsw`, `versioned_lessons_embedding_hnsw`, `code_embeddings_embedding_hnsw` (queried from `pg_indexes`) |
| Index actually usable by the query | ✅ Two-stage query: a bare `ORDER BY embedding <=> vec LIMIT k×overfetch` CTE (index-accelerated), then a composite re-rank of that small set (`store.py:612-640`). |
| Blocking embedding calls | ✅ The synchronous Voyage client runs via `asyncio.to_thread` (`store.py:405`). |

## Findings

- **id:** MEM-03-001 · **severity:** High (operational) · **status: RESOLVED 2026-09-29** (key added to `backend/.env`; live retrieval verified). Remaining owner action: add a card to lift the 3 requests/minute free-tier limit.
  **file:** `backend/.env` · **location:** `VOYAGE_API_KEY`
  **finding:** No embedding key is configured, so all semantic memory (task, failure, learning, procedure and lesson retrieval) is inactive on this deployment. The code degrades exactly as designed (no crash, no bad rows).
  **production_impact:** Agents get no long-term memory context; the "memory" feature silently does nothing.
  **recommendation:** Set `VOYAGE_API_KEY` in the production environment, then run `PENDING_TESTS_API_KEYS.md` §L rows L2 and L3.
  **confidence:** High · **effort:** Small (configuration)

- **id:** MEM-03-002 · **severity:** Low · **status: ACCEPTED**
  **file:** `backend/app/memory/store.py` · **line:** 622-631
  **finding:** The repo filter sits inside the HNSW candidate CTE; pgvector applies it after the index scan, so a very selective repo filter can return fewer than `k` rows. `memory_candidate_overfetch_factor` already mitigates this. Not reproducible at current data volumes (0 real embeddings).
  **confidence:** Medium · **effort:** Small

- **Cross-cutting (bug class (d), found during this audit):** an AST call-graph scan over all 127 `asyncio.run()` sites (`evidence/asyncio_run_in_loop.py`) found one more real instance outside memory: `run_executive()` breaks "Create goal". It is reported and fixed in audit 04 (ORCH-04-001).

## Verdict

**READY:** code verified, live semantic retrieval verified. The test suite keeps running without the key (`tests/conftest.py` blanks it unless `RUN_PENDING_TESTS=1`), so tests never make paid calls or write real memories.
