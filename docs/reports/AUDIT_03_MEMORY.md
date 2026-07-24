# AUDIT 03 — MASTER MEMORY AUDIT

**Run date:** 2026-07-24
**Scope:** Read-only. Evidence-only. Follows `files/Audit/00b_AUDIT_STANDARDS.md`.

---

## 1. Executive Summary

The three memory systems are structurally exactly as documented: `LessonStore` (in-process, `base_graph.py`), durable outcome embeddings (`app/memory/store.py`, `memory_embeddings`), and versioned lessons (`app/fleet/versioned_memory.py`, `versioned_lessons`). Both asyncio-hazard-prone call sites (`publish()`, `archive_expired()` — both wrap `asyncio.run()` internally) are correctly, deliberately isolated inside `asyncio.to_thread()` contexts with no pre-existing event loop, so the recurring hazard documented elsewhere in this project's history does not recur here — a real, verified-clean design. However, this audit found a genuine, previously-undocumented correctness bug: 2 of the 4 `embed_*` functions never set the `category` column, so their rows silently fall back to the ORM's `default="task"` regardless of their real `outcome` — meaning `/api/memory/patterns?category=architecture` and `?category=failure` return zero rows even when matching data exists. It also found `versioned_lessons` has no vector index (unlike `memory_embeddings`, which does), no retention/archival policy exists for `memory_embeddings` at all (unlike the other 4 retained/archived tables in this codebase), `versioned_memory.rollback()` has never had a real caller wired to it, and the lesson-merge LLM call references the wrong semantically-named config field for its "must stay cheap" requirement.

---

## 2. Phase 1 — Correctness Findings

### MEM-03-001
- **severity:** High
- **file:** `backend/app/memory/store.py`
- **location:** `embed_architecture_note`, `embed_failure`
- **line:** 185-222, 277-313
- **finding:** Neither function passes `category=` when constructing `MemoryEmbedding(...)`. The ORM column declares a Python-side default: `category: Mapped[str] = mapped_column(String(50), default="task")` (`db/models.py:459-461`). Because these two functions never override it, every architecture-note and failure row is silently tagged `category="task"` regardless of its real `outcome` (`"architecture"`/`"failure"`). Only `embed_task_outcome` (correctly, since its rows genuinely are task outcomes) and `embed_learning_signal` (which explicitly sets `category="learning"`) end up with a category matching their real content.
- **evidence:** `store.py:203-211` (`embed_architecture_note`'s `MemoryEmbedding(...)` call has `outcome="architecture"` but no `category=` key); `store.py:296-304` (`embed_failure`'s call has `outcome="failure"`, no `category=`); `db/models.py:459-461` for the Python-side `default="task"`. Migration `010_memory_category_retention.py`'s own stated purpose: *"Adds a 'category' column... so that memories can be tagged as task | architecture | failure | learning — matching Doc 11 (Memory System Specification)."*
- **production_impact:** `api/memory.py`'s `GET /api/memory/patterns?category=architecture` and `?category=failure` (the exact feature this column was added for) return zero matching rows even when architecture notes / failure records exist in the table — they're all hiding under `category="task"`. The `categoryDistribution` aggregate in the same endpoint's response is correspondingly wrong (inflates `"task"`, shows 0 for `"architecture"`/`"failure"`).
- **confidence:** High
- **recommendation:** Add `category="architecture"` to `embed_architecture_note`'s `MemoryEmbedding(...)` call and `category="failure"` to `embed_failure`'s, matching `embed_learning_signal`'s existing correct pattern. Also recommend a one-time DB backfill (`UPDATE memory_embeddings SET category = outcome WHERE outcome IN ('architecture','failure')`) to correct existing mis-tagged rows.
- **effort:** Small (2 one-line additions + an optional backfill statement)

### MEM-03-002
- **severity:** Medium
- **file:** `backend/migrations/versions/014_versioned_lessons.py`
- **location:** `upgrade()`
- **line:** 24-49
- **finding:** Creates indexes on `lesson_id`, `topic`, `state` but none on `embedding`. Compare `memory_embeddings` (migration `004_phase6_tables.py:88-91`), which explicitly creates `memory_embeddings_embedding_hnsw` (`USING hnsw (embedding vector_cosine_ops)`). `versioned_lessons` — added 10 migrations later, same pgvector `Vector(1536)` column type — has no equivalent.
- **evidence:** `grep -rn "hnsw" migrations/versions/*.py` matches only in `004_phase6_tables.py`; `014_versioned_lessons.py`'s `upgrade()` has 3 `op.create_index(...)` calls, none for `embedding`.
- **production_impact:** `_find_most_similar_published()` (`versioned_memory.py:75-81`) runs `ORDER BY embedding <=> CAST(:vec AS vector) LIMIT 1` — a full sequential scan computing exact cosine distance against every published row — on every single `publish()` call (i.e., every lesson extraction across all ~72 agents whenever `VOYAGE_API_KEY` is configured). Fine at current scale; degrades as `versioned_lessons` grows, with no query-plan change needed to fix it later (an index add is non-invasive).
- **confidence:** High
- **recommendation:** Add a migration creating `CREATE INDEX IF NOT EXISTS versioned_lessons_embedding_hnsw ON versioned_lessons USING hnsw (embedding vector_cosine_ops)`, matching the existing `memory_embeddings` pattern exactly.
- **effort:** Small (one new migration)

### MEM-03-003
- **severity:** Medium
- **file:** `backend/app/services/retention.py`
- **location:** `_RETAINED_TABLES`
- **line:** 30-34
- **finding:** `_RETAINED_TABLES = {"task_logs": ..., "agent_runs": ..., "artifacts": ...}` — no entry for `memory_embeddings`. `versioned_lessons` has its own dedicated, separately-wired retention mechanism (`versioned_memory.archive_expired()` + `main.py`'s `_versioned_lesson_archive_loop()`), but `memory_embeddings` (the oldest of the three memory systems, Day 6) has never had any retention/archival policy added — and unlike the other 3 retained tables (which gained `archived`/`archived_at` columns in migration `019_retention_archive_fields.py`), `memory_embeddings` has no such columns at all.
- **evidence:** `retention.py:30-34` (dict has exactly 3 keys); `grep -n "archived" migrations/versions/019_retention_archive_fields.py` — confirms the 3 retained tables' columns, `memory_embeddings` absent from that migration too.
- **production_impact:** `memory_embeddings` grows without bound — every task/epic completion (`embed_task_outcome`), architecture note, failure record, and learning signal writes a permanent row with no cleanup path, ever. Not an immediate crash risk, but a genuine, unaddressed data-growth gap this project's own `retention.py` docstring explicitly says the Memory System Specification calls for ("archived to cheaper storage rather than deleted") — just never extended to this specific table.
- **confidence:** High
- **recommendation:** Add `memory_embeddings` to `_RETAINED_TABLES` (needs an `archived`/`archived_at` column pair added via a new migration first, matching the existing pattern) — or, if unbounded retention of task-outcome memory is actually the deliberate design intent (arguably reasonable, since this is the system's own long-term "experience"), document that explicitly rather than leaving it as an apparent oversight.
- **effort:** Medium (one migration + a `_RETAINED_TABLES` entry + a design decision on intent)

### MEM-03-004
- **severity:** Low-Medium
- **file:** `backend/app/fleet/versioned_memory.py`
- **location:** `VersionedMemoryStore.rollback`
- **line:** 278-287
- **finding:** Zero real (non-test) callers anywhere in `app/`. `grep -rn "get_versioned_memory_store()\." app --include="*.py"` finds exactly 2 real call sites: `.publish(` (`base_graph.py:798`) and `.archive_expired` (`main.py:169`). `.rollback(` does not appear at any real call site.
- **evidence:** As above — the grep result set.
- **production_impact:** This is the same "built but never wired" pattern PROJECT.md's gap-closure history documents recurring for `publish()` and `archive_expired()` in this exact module (both were found-and-fixed in the Days-11-13 gap-closure) — `rollback()` was evidently never checked in that same pass and is still unreachable. Unlike `prompt_registry.deploy()` (which has an explicit code comment acknowledging its intentionally-dormant status), there is no such acknowledgment here — this reads as a genuine oversight, not a documented design choice.
- **confidence:** High
- **recommendation:** Either wire `rollback()` into a real trigger (a "rollback this lesson" action on a memory/fleet dashboard would be the natural fit, mirroring how `fleet_checkpoint.rollback_to()` eventually got wired into the failure ladder), or add an explicit comment if it's meant as manual/operator-only tooling invoked outside the app (e.g. a management script) rather than a live code path.
- **effort:** Small to Medium, depending on which resolution is chosen

### MEM-03-005
- **severity:** Medium
- **file:** `backend/app/fleet/versioned_memory.py`
- **location:** `VersionedMemoryStore._publish`
- **line:** 261-263
- **finding:** `_merge_via_llm(existing_row.content, content, get_settings().model_planner)` — the lesson-merge LLM call uses `settings.model_planner`, not `settings.model_router` (the field `config.py` itself documents as *"Model for triage/summary/heartbeat"* — the semantically correct fit for this operation, and the field CLAUDE.md's Model Tiering section designates for cheap work). It happens to resolve to the same string today only because `model_planner`'s current default (`"claude-haiku-4-5-20251001"`) coincidentally equals `model_router`'s default — not because the code deliberately binds to the cheap tier.
- **evidence:** `versioned_memory.py:262`; `config.py`: `model_planner` default `"claude-haiku-4-5-20251001"` (described as *"Model for PM/Architect/Decomposer"*, not merge/triage work) vs. `model_router` default, same string value, described as *"Model for triage/summary/heartbeat"*.
- **production_impact:** No cost impact today (the two fields currently share a value). But if `model_planner` is ever changed independently (e.g. to comply with CLAUDE.md's own stated tiering intent that PM/Architect reasoning may warrant a stronger model than pure triage work), every lesson-merge call — which fires on every `publish()` call where a semantically similar prior lesson exists, across the whole agent fleet — would silently start using the more expensive model with no code change flagging the cost shift. This is exactly the kind of coincidental-not-deliberate binding this audit was asked to check for.
- **confidence:** High
- **recommendation:** Change `versioned_memory.py:262` to `get_settings().model_router`.
- **effort:** Small (one line)

### MEM-03-006
- **severity:** Low
- **file:** `backend/app/agents/decomposer.py`
- **location:** `decomposer_node`
- **line:** 109-168 (full function body)
- **finding:** Never reads `state["memory_context"]`, unlike `pm_node` (`pm.py:115-116`) and `architect_node` (`architect.py:137-138`), which both correctly append it to their prompts via a `memory_block`. `decomposer_node` only reads `state["pm_brief"]` and `state["architect_plan"]`.
- **evidence:** `grep -n "memory_context" app/agents/pm.py app/agents/architect.py app/agents/decomposer.py` — 2 hits in `pm.py`, 2 in `architect.py`, 0 in `decomposer.py`.
- **production_impact:** Low — `decomposer_node` still receives `pm_brief`/`architect_plan`, both of which may already reflect memory-informed reasoning from the upstream nodes, so this isn't a complete memory blackout for decomposition. But it does mean the specific claim "`memory_context` flows PM → Architect → Decomposer" (as this audit was asked to verify) is only true for 2 of the 3 stages — the raw retrieved-lesson text itself never reaches the Decomposer directly.
- **confidence:** High
- **recommendation:** Either add the same `memory_block` append pattern to `decomposer_node` for consistency, or explicitly document that Decomposer intentionally relies on upstream-summarized context only (a legitimate design choice, just currently undocumented as such).
- **effort:** Small (if adding: a few lines matching the existing pm.py/architect.py pattern)

---

## 3. Confirmed-Clean Items (with evidence)

- **Embedding fallback**: `_embed()` (`store.py:38-59`) returns `_ZERO_VECTOR_1536` (not a crash) when `VOYAGE_API_KEY` is unset, or on any Voyage API exception (caught, logged, zero-vector returned). Verified by direct read, not assumed.
- **`versioned_memory.publish()` gating on a real key**: still gated at its one real call site — `base_graph.py`: `if _get_settings().voyage_api_key: ... get_versioned_memory_store().publish(...)`. No regression since the Days-11-13 gap-closure that added this gate.
- **Similarity query correctness**: `query_similar_tasks()` queries `memory_embeddings` only; `_find_most_similar_published()` queries `versioned_lessons` only. No cross-querying between the two systems found.
- **Merge-on-conflict lifecycle**: traced the exact state machine in `_publish()` (`versioned_memory.py:231-276`) against the documented design — V2 inserted as `draft` → LLM merge call → `V_merged` inserted `published` → V1 flipped to `superseded` → V2 flipped to `merged_into`. Matches exactly, in the correct order (V1 flip happens after the merged row exists, avoiding a window with zero published rows for the topic).
- **Zero-vector rows never trigger a merge**: `_find_most_similar_published()` explicitly returns `None` when the query vector is the zero vector (`versioned_memory.py:68-69`) — a zero-vector lesson can never be "found similar" to anything, correctly preventing the exact contamination bug the Days-11-13 gap-closure fixed from recurring.
- **`asyncio.run()` safety**: both `publish()` and `archive_expired()` wrap `asyncio.run()` internally (sync methods), which is only safe when no event loop is already running in the calling thread. Verified both real call sites are correctly isolated: `publish()` is reached via `_extract_and_store_lesson()` inside `run_agent_graph()`, which every real production caller invokes through `asyncio.to_thread()` (confirmed in Audit 01/02); `archive_expired()` is explicitly wrapped in `await asyncio.to_thread(get_versioned_memory_store().archive_expired)` at its one call site (`main.py:169-171`). Neither can hit `RuntimeError: asyncio.run() cannot be called from a running event loop`. `_new_isolated_db_engine()`'s own docstring shows this was a deliberate design decision, not an accident.
- **Memory isolation**: `query_similar_tasks`/`_find_most_similar_published` queries are global (not scoped by repo/task/tenant) — confirmed by reading the SQL directly (no `WHERE task_id=`/`repo_id=` filter). This is not flagged as a leak: this project has no multi-tenant design anywhere else in the codebase (confirmed across all 3 prior audits), so a single shared engineering-memory pool across all repos/tasks is consistent with the system's actual single-tenant scope, not a boundary violation.
- **No raw memory-write API endpoint**: `api/memory.py` defines only 2 routes, both `GET` (`/patterns`, `/search`) — no write path reachable without going through the agent pipeline.
- **`_write_failed_event`-class silent swallowing**: not present in this layer — every `embed_*`/query function has a real `try/except` with `logger.warning(...)` and a safe fallback (`None`/`[]`), not a bare silent pass.

---

## 4. Phase 2 — Isolation & Security: no new findings beyond what's noted above (globally-scoped by design, no write API, LLM-merge model tier addressed in MEM-03-005).

## 5. Phase 3 — Performance

- **Batching**: `_embed()` is called once per lesson/outcome/note/failure/signal — synchronous, one text at a time, no batching across a run. At current per-agent-run volume (one lesson extraction per completed run) this is not a bottleneck; would need batching if extraction frequency grows substantially. Not flagged as a finding — informational only, matching this audit's "advisory, not a hard defect" allowance for tuning observations.
- **HNSW index**: present and correctly used for `memory_embeddings` (MEM-03-002 covers the `versioned_lessons` gap).
- **N+1 patterns**: none found — `query_similar_tasks`/`query_architecture_notes`/`query_failures`/`query_learning_signals` are each single queries, not called in a per-subtask loop anywhere traced in this pass.

---

## 6. Prioritized Fix List

| Priority | ID | Task | Effort |
|---|---|---|---|
| 1 | MEM-03-001 | Set `category=` correctly in `embed_architecture_note`/`embed_failure`; backfill existing mis-tagged rows | Small |
| 2 | MEM-03-005 | Fix `versioned_memory.py:262` to use `model_router` instead of `model_planner` | Small |
| 3 | MEM-03-002 | Add HNSW index migration for `versioned_lessons.embedding` | Small |
| 4 | MEM-03-004 | Wire `rollback()` to a real trigger, or document it as intentionally manual-only | Small-Medium |
| 5 | MEM-03-003 | Add `memory_embeddings` to the retention policy (or explicitly document unbounded-by-design) | Medium |
| 6 | MEM-03-006 | Decide/document whether Decomposer should also receive raw `memory_context` | Small |

---

## 7. Memory Layer Production-Readiness Score: 80/100

The three-system architecture is real, correctly separated, and the two asyncio-hazard-prone call sites are both genuinely, deliberately safe — no regression of this project's own recurring hazard class. The score is held down by one real correctness bug affecting a shipped, user-facing filter feature (MEM-03-001) plus a cluster of smaller, well-evidenced gaps (missing index, missing retention policy, one more unwired function in the same "built but never called" pattern this module has twice before, and a fragile model-tier reference). None are production blockers; MEM-03-001 is the one worth prioritizing since it directly affects the correctness of a real API response.

**Overall: READY for next audit phase (Audit 04 — Orchestration).**

---

## 8. Fixes Applied (2026-07-24)

All 6 findings fixed per user direction.

- **MEM-03-001 [FIXED]** — Added `category="architecture"`/`category="failure"` to `embed_architecture_note`/`embed_failure`'s `MemoryEmbedding(...)` calls (`app/memory/store.py`). Added migration `021_backfill_memory_category.py` to correct existing mistagged rows (`UPDATE memory_embeddings SET category = outcome WHERE outcome IN ('architecture','failure') AND category != outcome`). Live-verified against the real dev DB: both functions now produce correctly-tagged rows.
- **MEM-03-002 [FIXED]** — Added migration `020_versioned_lessons_hnsw.py` creating `versioned_lessons_embedding_hnsw` (cosine ops), matching the existing `memory_embeddings` pattern. Applied and confirmed present via `pg_indexes`.
- **MEM-03-003 [FIXED]** — Added `memory_embeddings_retention_days` config field (default 180, matching `lesson_retention_days`'s precedent of memory tables having their own retention knob rather than reusing `LOG_RETENTION_DAYS`). Added migration `022_memory_embeddings_retention.py` (archived/archived_at columns + index) and updated the `MemoryEmbedding` ORM model to match. Wired `memory_embeddings` into `retention.py`'s cleanup cycle on its own separate cutoff. Applied and confirmed present via `information_schema.columns`.
- **MEM-03-004 [FIXED]** — Added two new endpoints to `api/memory.py`: `GET /api/memory/lessons` (list, read-only, filterable by state) so a `lesson_id` can actually be discovered, and `POST /api/memory/lessons/{lesson_id}/rollback` (protected by the existing `require_approver` RBAC dependency, dispatches `VersionedMemoryStore.rollback()` via `asyncio.to_thread` — the same safe pattern already used for `archive_expired()` — with a `ValueError` → 404 mapping for an unknown/no-superseded lesson). `rollback()` now has its first real, reachable caller.
- **MEM-03-005 [FIXED]** — `versioned_memory.py:262` now references `get_settings().model_router` instead of `model_planner`.
- **MEM-03-006 [FIXED]** — Added the same `memory_block` append pattern already used in `pm.py`/`architect.py` to `decomposer_node`'s prompt construction (`app/agents/decomposer.py`).

**Also fixed in passing:** while adding the new `memory_embeddings_retention_days` field, ran a fresh `Settings` vs `.env.example` diff and found `LLM_CALL_TIMEOUT_SECONDS` (added in Audit 02's fix) had never been added to `.env.example` — a real gap this project's own config-completeness discipline exists to catch. Added both that and the new field; re-ran the diff — 0 fields now missing.

**Verification:** Ran all 3 new migrations against the real dev database (`alembic upgrade head` — 019→020→021→022, all applied cleanly) and confirmed the resulting schema directly via `pg_indexes`/`information_schema.columns`, not just migration success. `pytest tests/ -q` → 2758 passed, 0 failed (3 pre-existing retention tests needed their settings mocks updated to include the new `memory_embeddings_retention_days` field — a legitimate, expected test update given the intentional new behavior, not a workaround). `mypy app/ --strict` → 0 errors, 176 source files. Live end-to-end verification against the real dev DB: (1) `embed_architecture_note`/`embed_failure` now produce correctly-tagged rows; (2) a full publish → merge → `GET /api/memory/lessons` → unauthenticated rollback (rejected) → authenticated rollback (restores the real prior content) → rollback-on-unknown-lesson (404) cycle, exercised through a real `TestClient` against the real DB, all passed.
