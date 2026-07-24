# AUDIT 01 — MASTER ARCHITECTURE AUDIT

**Run date:** 2026-07-24
**Scope:** Read-only. Evidence-only (file:line or `NOT FOUND`). Follows `files/Audit/00b_AUDIT_STANDARDS.md`.
**Baseline:** commit `b5c6902` (post scipy 1.17.1 downgrade), PROJECT.md through "Days 0-18 Full Re-Audit + Day 19 Prep" (2026-07-22).

---

## 1. Executive Summary

The two-graph architecture (`base_graph.py` for worker agents, `pipeline/graph.py` for the checkpointed PM→Architect→Decomposer→human_review flow) is correctly separated with no confusion between the two found in this pass, and the previously-documented `task_id`/`trace_id` fix (Days 0-18 gap closure) is holding with no regression. Orphan-module remediation from prior gap-closure sessions (`versioned_memory.publish`, `fleet_checkpoint`, `tool_discovery`) is verified still wired. However, this audit found a new, previously-undocumented architectural gap: the Postgres-backed legacy event bus (`app/event_bus/bus.py`) — DB persistence, replay, dead-letter recording, and in-process subscriber dispatch — has **zero real effect in production**, because no call site anywhere in the codebase (including the entire test suite) ever passes a `db` session to `publish_event()`, and `subscribe()` has zero real callers. A second, independent bug compounds this: the Fleet OS event overlay's forward-to-legacy-bus path silently fails whenever `publish()` is invoked from inside `asyncio.to_thread()` — which is the actual execution context for essentially every real agent run. One config-sprawl violation (a hardcoded model string bypassing `model_router.py`) and one dead dependency (`langchain-anthropic`, never imported) were also found. No circular imports, no migration-chain gaps, and the one frontend/backend contract field spot-checked (`pr_status`/`prStatus`) is correctly handled.

**Architecture score: 74/100** — solid, deliberate two-graph design with real gap-closure discipline evident in history, but the event-bus finding is a genuine "looks wired, isn't" defect of the exact class this project has repeatedly found and fixed before, this time undiscovered until now.

---

## 2. Two-Graph Correctness Verdict: **CORRECT, VERIFIED**

| | `base_graph.py` (worker agents) | `pipeline/graph.py` (PM→Architect→Decomposer) |
|---|---|---|
| Checkpointer | **None.** `build_agent_graph()` calls `g.compile()` with no `checkpointer=` argument (`backend/app/agents/base_graph.py:899`). | **Real, persistent.** `AsyncPostgresSaver` via `init_checkpointer()` (`backend/app/pipeline/graph.py:28-56`), held open for app lifetime via `_pg_cm`, closed in `close_checkpointer()`. Falls back to `MemorySaver` only if Postgres init fails. |
| Resume semantics | No `interrupt()`, no resume — a run either finishes or ends (stall/max_turns/exception). | `interrupt_before=["human_review"]` (`graph.py:134`) + `Command(resume=...)` via `resume_pipeline()`. Survives restarts because the checkpointer is real Postgres. |
| Used by | All 79 agent files in `app/agents/*.py` via `run_agent_graph()` (backend_dev, frontend_dev, qa, reviewer, coder, and all specialist/auditor agents). | Exactly 3 nodes: `pm_node`, `architect_node`, `decomposer_node` (`graph.py:115-117`), invoked once per task via `run_planning_pipeline()`/`resume_pipeline()`. |

**No instance found** in this pass of code assuming `base_graph.py` agents have checkpoint/resume semantics they don't have. `manager.py`'s own retry loop (bounded by `max_retries`, `backend/app/agents/manager.py:190`) is the correct mechanism for that graph's failure recovery, not `interrupt()`/checkpointing.

---

## 3. Event / Trace-ID Correctness Verdict: **task_id/trace_id FIX HOLDING — but see Finding ARCH-01-001/002 for a separate, new event-bus gap**

The Days 0-18 gap-closure fix (using real `task_id` instead of the per-run `trace_id` in `agent_registry.start_task()` and `TaskStarted`/`TaskCompleted`/`TaskFailed`) was re-verified with fresh reads, not trusted from PROJECT.md:

- `base_graph.py:1017-1018` — `_reg.start_task(role_name, task_id=task_id)`; `publish(task_started(task_id=task_id, ...))` — correct, uses `task_id` not `tid`.
- `base_graph.py:1263-1264`, `1290-1307` — `task_completed`/`task_failed` — same, correct.
- `manager.py:117` — `manager_trace_id = f"task-{task_id}-manager"` — stable per-run trace id, correct per the Days 0-18 fix's stated convention.

**No regression found.** `HealthUpdated` is published on both success (`base_graph.py:1264-1266`) and error (`base_graph.py:1303-1307`) paths — Gap 7's exit criterion confirmed still satisfied.

---

## 4. Orphan-Module List

### Confirmed still wired (re-verified fresh, not trusted from PROJECT.md)

| Module/function | Real caller (file:line) |
|---|---|
| `versioned_memory.get_versioned_memory_store().publish()` | `base_graph.py:760`, gated on `settings.voyage_api_key` at `base_graph.py:755` |
| `versioned_memory.get_versioned_memory_store().archive_expired` | `main.py:169` (lifespan background loop) |
| `fleet_checkpoint.save_checkpoint`/`rollback_to` | Aliased as `checkpoint`/`rollback` in `failure_ladder.py:46-47`; `checkpoint()` called from `base_graph.py:1209,1318` (stall + exception paths) and `manager.py:429` (epic halt) |
| `tool_discovery.check_availability()` | `fleet_manager.py:102`, reached via `fleet_manager().select(verify_tool_availability=True)` called at `manager.py:151-153` |

### Confirmed still intentionally unused (no new finding — matches documented precedent)

- `prompt_registry.deploy()` — zero real callers. `main.py:181` has a standing code comment acknowledging this ("prompt_registry.deploy()'s regression [gate is dormant] by design"). Consistent with PROJECT.md's Days 11-15 gap-closure audit, which explicitly ruled this out of scope. Not re-flagged as new.

### New orphan finding (see ARCH-01-001 for full detail)

- `event_bus.bus.subscribe()` — zero real (non-test) callers anywhere in `app/`.
- `event_bus.bus.get_unprocessed_events()` — zero real callers anywhere (only referenced in its own module's docstring).

### Scope note

A full agent-by-agent (all 79) real-caller sweep is Audit 02's explicit mandate (its Phase 1 checklist's last item). This pass spot-checked the previously-flagged modules plus ran `vulture` (installed into the backend venv for this audit) across `app/` as a first-pass signal — it flagged ~150 `run_<agent>_agent`-style functions as "unused," which is expected noise from static analysis: these are dispatched dynamically by name through `app/pipeline/dispatcher.py`/`manager.py`/API routes, which `vulture` cannot see. Recommend Audit 02 do the real per-agent trace; not re-derived here to avoid duplicating that audit's scope.

---

## 5. Findings

### ARCH-01-001
- **severity:** High
- **file:** `backend/app/event_bus/bus.py`
- **location:** `publish_event()`, `_persist_event()`, `subscribe()`, `get_unprocessed_events()`
- **line:** 42-51 (`subscribe`), 87-118 (`_persist_event`), 159-190 (`publish_event`), 193-224 (`get_unprocessed_events`)
- **finding:** `publish_event()` accepts an optional `db` parameter that gates all DB persistence (`_persist_event`) and dead-letter recording (`_write_failed_event`) — `if db is None: return`. Every call site of `publish_event()` in the entire codebase — 9 in `manager.py` (lines 165, 300, 316, 355, 401, 529, 557, 677, 711), 2 in `api/epics.py` (177, 210), 1 in `fleet_events.py`'s `FleetBus` forward (247), and every call in `tests/test_event_bus.py` — omits `db` entirely, so it always defaults to `None`. In parallel, `event_bus.bus.subscribe()` (the in-process handler registry `_subscribers`) has zero real callers anywhere in `app/` — only `activity_stream.py`'s unrelated, separately-implemented `.subscribe()` method (a per-task SSE queue, not this module) is ever called.
- **evidence:** `grep -rn "publish_event(" app --include="*.py"` returns 12 call sites, none containing `db=`; `grep -rn "publish_event(" tests --include="*.py"` returns calls exclusively of the form `publish_event(evt, db=None)`. `grep -rn "\.subscribe(\|add_subscriber\|def subscribe" app` shows `event_bus/bus.py:42`'s `subscribe()` is defined but never called; the only real `.subscribe(` call sites (`api/activity.py:45`, `api/fleet_dashboard.py:276`) target `app/services/activity_stream.py:75`'s distinct `subscribe()` method, not this one.
- **production_impact:** The `events` and `failed_events` tables (migration `002_phase4_tables.py`) are permanently empty in production — no event has ever been persisted through this path. `get_unprocessed_events()` (the documented replay-on-restart mechanism) always returns `[]` because it queries a table that is never written to, and additionally has zero real callers so replay never runs anyway. The in-process retry-then-dead-letter design (`_dispatch_to_handler`, `_write_failed_event`) is unreachable in practice, since `_subscribers` is always empty — there is never a handler to fail. This does not affect user-visible functionality: task/epic status is persisted through separate, direct SQLAlchemy updates in `manager.py`, and real-time UI streaming uses the independent `activity_stream.py` SSE mechanism (Day 18) — but the entire "Postgres LISTEN/NOTIFY event bus with in-memory subscriber registry" subsystem described in this file's own module docstring has no real effect beyond a `logger.info()` line and (if `REDIS_STREAMS_ENABLED=true`) a Redis Streams fan-out.
- **confidence:** High
- **recommendation:** Either (a) thread a real `AsyncSession` into every `publish_event()` call site (manager.py, api/epics.py, the FleetBus forward) so the events/dead-letter tables actually populate, or (b) if DB persistence was never actually intended to be load-bearing (logging + Redis Streams considered sufficient), remove `_persist_event`/`_write_failed_event`/`get_unprocessed_events`/the `events`+`failed_events` tables and the `db` parameter entirely, and update the module docstring to stop claiming DB-backed replay. Decide deliberately — right now it's neither.
- **effort:** Medium (multiple call sites, or one migration + module simplification if removing)

### ARCH-01-002
- **severity:** Medium
- **file:** `backend/app/fleet/fleet_events.py`
- **location:** `FleetBus._publish_to_existing_bus`
- **line:** 219-249
- **finding:** The Fleet OS→legacy forwarding path does `loop = asyncio.get_event_loop()` inside a bare `try/except RuntimeError: pass`, then only calls `asyncio.create_task(publish_event(legacy))` `if loop and loop.is_running()`. `asyncio.get_event_loop()` raises `RuntimeError` when called from a thread that never had an event loop set on it — which is exactly the situation inside every `asyncio.to_thread()` worker. `run_agent_graph()` (the function that contains every `publish(task_started(...))`/`publish(task_completed(...))`/`publish(task_failed(...))`/`publish(health_updated(...))`/`publish(lesson_published(...))` call in `base_graph.py`) is invoked via `asyncio.to_thread` at every real production call site traced: `api/agents.py:667` (`asyncio.to_thread(run_coder, ...)`, simple mode) and `manager.py:213-232,288-295,334-342` (`asyncio.to_thread(run_frontend_dev/run_backend_dev/run_qa/run_reviewer, ...)`, full mode).
- **evidence:** `app/fleet/fleet_events.py:240-247`: `loop = None` then `try: loop = asyncio.get_event_loop() except RuntimeError: pass` then `if loop and loop.is_running(): asyncio.create_task(publish_event(legacy))`. `app/api/agents.py:667`: `files_changed, error, tokens_in, tokens_out = await asyncio.to_thread(run_coder, ...)`. `app/agents/coder.py:144` confirms `run_coder` calls `run_agent_graph(...)` directly (sync call, no further threading), so `run_agent_graph`'s body executes inside the `to_thread` worker.
- **production_impact:** Even where ARCH-01-001's `db=None` issue is fixed, the legacy-bus forward for the majority of Fleet OS lifecycle events would still silently never fire, because the code never reaches `publish_event()` at all from a `to_thread` context. Combined with ARCH-01-001, this means the FleetBus's stated purpose ("forwarding to the existing event_bus so legacy subscribers receive them," per this file's own docstring) fails for two independent reasons on the path that produces the large majority of this system's Fleet OS event volume.
- **confidence:** High
- **recommendation:** Don't rely on the ambient/current event loop from inside a thread that was never given one. Either capture the main event loop's reference before spawning the `to_thread` call and use `loop.call_soon_threadsafe(...)`/`asyncio.run_coroutine_threadsafe(...)` to schedule the forward, or move the FleetBus forward out of `publish()` and into an async wrapper called explicitly from the async call sites that already have a running loop (`manager.py`, `api/agents.py`) after the `to_thread` call returns.
- **effort:** Small (single file, `fleet_events.py`)

### ARCH-01-003
- **severity:** Medium
- **file:** `backend/app/api/settings.py`
- **location:** `_verify_anthropic`
- **line:** 250
- **finding:** `client.messages.create(model="claude-haiku-4-5-20251001", ...)` is a hardcoded model string used to test a user-supplied Anthropic API key. CLAUDE.md's permanent Zero Hardcoding rule states model names must live in config (`MODEL_PLANNER`/`MODEL_CODER`/`MODEL_ROUTER`) specifically "so we can swap models without code changes" — every other model-string reference in the codebase goes through `config.py` or `fleet/model_router.py`; this is the one exception found.
- **evidence:** `app/api/settings.py:249-253`:
  ```python
  client.messages.create(
      model="claude-haiku-4-5-20251001",
      max_tokens=1,
      messages=[{"role": "user", "content": "hi"}],
  )
  ```
- **production_impact:** Low immediate risk (a key-verification ping, not a production inference path), but if this model string is ever deprecated/retired by Anthropic, key verification silently breaks for all users until someone finds this specific literal — exactly the maintenance cost the project's own hardcoding rule exists to prevent. `grep -rn "claude-[a-z0-9.-]*\|gpt-[0-9]" app --include="*.py"` confirms this is the only such literal outside `config.py`/`model_router.py`/`groq_adapter.py`.
- **confidence:** High
- **recommendation:** Replace the literal with `get_settings().model_router` (or whichever config field represents the cheapest/Haiku tier) — matching the pattern already used everywhere else in the codebase.
- **effort:** Small (single line)

### ARCH-01-004
- **severity:** Low
- **file:** `backend/requirements.txt`
- **location:** dependency pin
- **line:** `langchain-anthropic==1.4.8`
- **finding:** Pinned but never imported. `grep -rln "langchain_anthropic\|langchain\.anthropic\|from langchain" app tests --include="*.py"` returns zero files. The codebase calls the `anthropic` SDK directly (`anthropic.Anthropic(...)`, confirmed throughout `base_graph.py`, `base.py`) — not through LangChain's wrapper. `langgraph` itself (also pinned, `langgraph==1.2.7`) is a separate package from `langchain-anthropic` and does not require it.
- **evidence:** Zero matches for the import; `requirements.txt` contains the pin with no corresponding usage anywhere in `app/` or `tests/`.
- **production_impact:** Unnecessary supply-chain surface (one more package's CVEs to track for zero functional benefit) and could mislead a future engineer into thinking LangChain-proper is used somewhere in the LLM-call path, when it isn't.
- **confidence:** High
- **recommendation:** Remove `langchain-anthropic` from `requirements.txt` unless a concrete near-term use is planned; if intentionally kept for a specific reason, add a one-line comment saying so (matching this project's own convention of leaving a rationale comment next to anything that looks unused, e.g. `main.py:181`, `fleet_manager.py:77-81`).
- **effort:** Small (single line, plus a `pip install -r requirements.txt` re-verify)

---

## 6. Config-Sprawl Findings

Re-verified (not trusted from PROJECT.md) that the three previously-documented hardcoding fixes are still config-driven, no regression:

- **CORS origins**: `config.py:439` (`cors_origins: str = Field(...)`) + `main.py:352` reads `get_settings().cors_origins.split(",")`. ✅ still config-driven.
- **Event bus max retries**: `config.py:443` + `event_bus/bus.py:39` (`return get_settings().event_bus_max_retries`). ✅ still config-driven.
- **Groq max retries**: `config.py:447` + `groq_adapter.py:318` (`max_retries = get_settings().groq_max_retries`). ✅ still config-driven.

One new instance found and reported above: **ARCH-01-003** (hardcoded model string in `api/settings.py:250`).

---

## 7. Frontend/Backend Contract Drift Findings

One field spot-checked as representative of the most recently-added feature (Day 14 git-push workflow, the newest DB fields at time of this audit):

- `DevTask.pr_status` (`db/models.py:79`) → serialized as `"prStatus": task.pr_status` (`api/tasks.py:432`) → typed in frontend as `prStatus: "none" | "pending" | "pushed" | "failed"` (`apps/web/lib/api.ts:68`). **VERIFIED CLEAN** — correct snake_case→camelCase handling and matching literal union.

**Scope note:** A full per-endpoint diff across all 18 API routers vs. `apps/web/lib/api.ts` was not performed in this pass — that is a large, mechanical cross-check better suited to a dedicated pass (recommend as a follow-up item, not blocking). Only this one field, chosen because it represents the newest schema surface, was verified.

---

## 8. Circular Dependencies

**0 real circular imports found.** A static AST scan of all `app/**/*.py` module-level and function-level `import`/`from` statements (script run during this audit, not a pre-existing tool) surfaced 2 candidate cycles, both traced and confirmed to be false positives from this project's own established deferred-import convention (imports inside function bodies, not at module top level, so no import-time cycle actually occurs):

1. `app.agents.base_graph` ↔ `app.fleet.versioned_memory` — the only import from `versioned_memory.py` back to `base_graph.py` is `from app.agents.base_graph import _serialize_content, _text_from_content` at `versioned_memory.py:204`, inside a function body (not top-level). The only import the other direction (`base_graph.py:757`) is likewise inside `_extract_and_store_lesson()`, not at module top.
2. `app.db.repository` ↔ `app.security.credential_vault` — same pattern: `db/repository.py:345,355` imports from `credential_vault` inside function bodies; `credential_vault.py:155,174,198` imports from `db.repository` inside method bodies.

---

## 9. DB Schema Flow

19 real Alembic migrations (`001` through `019`), chain verified linear and gapless by reading each file's actual `revision`/`down_revision` values (not inferred from filenames): `001→002→003→...→019`, no branches, no gaps.

| Migration | Adds |
|---|---|
| 001_initial_schema | `CREATE EXTENSION vector`; core tables (dev_tasks, task_logs, agent_runs, etc.) |
| 002_phase4_tables | events, failed_events (indexes on task_id/event_type/created_at) — **see ARCH-01-001: never populated** |
| 003_phase5_tables | epics, policies, policy_approvals; `dev_tasks.epic_id` |
| 004_phase6_tables | memory_embeddings (re-runs `CREATE EXTENSION IF NOT EXISTS vector`, idempotent — correct ordering, no issue); pgvector column type fix (drop/re-add as `vector(1536)`) |
| 005_phase7_tables | goals; agent_runs cache-token columns added then dropped (self-correcting within the migration) |
| 006_add_repos | repos table |
| 007_task_repo | `dev_tasks.repo_id` |
| 008_system_settings | system_settings |
| 009_outcome_enum_chat_messages | chat_messages |
| 010_memory_category_retention | `memory_embeddings.category` |
| 011_enhancement_requests | enhancement_requests |
| 012_agent_benchmarks | agent_benchmarks |
| 013_prompt_versions | prompt_versions |
| 014_versioned_lessons | versioned_lessons |
| 015_pending_approvals | pending_approvals |
| 016_dev_task_pr_fields | `dev_tasks.branch_name`/`pr_url`/`pr_status` |
| 017_task_images | task_images |
| 018_dev_task_metadata_fields | `dev_tasks.project`/`final_summary`/`assigned_agent`/`priority` |
| 019_retention_archive_fields | `archived`/`archived_at` columns across retention-eligible tables |

Full DDL-vs-ORM field-by-field drift checking (the class of bug that caused the documented `MemoryEmbedding.created_at` crash) and timezone-consistency grepping are explicitly Audit 06's mandate — not duplicated here.

---

## 10. Memory Data Flow (light pass — full correctness is Audit 03's mandate)

Three systems confirmed structurally present exactly as PROJECT.md describes: in-process `LessonStore` (`base_graph.py:130-188`), durable task-outcome embeddings (`app/memory/store.py`, called from `manager.py:667,686,726` via `embed_task_outcome`), and versioned lessons (`app/fleet/versioned_memory.py`, called from `base_graph.py:760`). `memory_context` is pre-fetched in `run_planning_pipeline()` (`pipeline/graph.py:159-167`) and placed into `initial_state["memory_context"]` (`graph.py:192`) before the graph runs. **Not verified in this pass**: whether `pm_node`/`architect_node`/`decomposer_node` actually read and append `state["memory_context"]` into their outgoing prompts, vs. it sitting unused in state — this is explicitly Audit 03's Phase 1 "Context injection correctness" item; deferred there rather than asserted here without full evidence.

---

## 11. Technology Fit Review

All major libraries in `requirements.txt` (fastapi, uvicorn, sqlalchemy[asyncio], alembic, asyncpg, langgraph, anthropic, voyageai, pgvector, groq, langgraph-checkpoint-postgres, rq, redis, boto3, sentry-sdk, slowapi, python-jose, bcrypt, openai, cryptography, networkx, scipy) were checked for real usage; all confirmed used except `langchain-anthropic` (ARCH-01-004). Spot-checked: `networkx` → `repo_tools/cross_file_graph.py` (real). `playwright` → `repo_tools/browser_driver.py` (real). `duckduckgo-search` → `agents/tools.py` (real). No swap-to-different-framework recommendations made, per this audit's own scope (LangGraph/FastAPI/SQLAlchemy are this project's deliberate, documented choices).

---

## 12. Prioritized Fix List

| Priority | ID | Task | Effort |
|---|---|---|---|
| 1 | ARCH-01-001 | Decide and implement: either thread real `db` sessions into all 12 `publish_event()` call sites, or remove the dead DB-persistence/replay/dead-letter machinery from `event_bus/bus.py` and its migration | Medium |
| 2 | ARCH-01-002 | Fix `FleetBus._publish_to_existing_bus()`'s event-loop capture to work from `asyncio.to_thread()` contexts (`call_soon_threadsafe`/`run_coroutine_threadsafe`, or move the forward to the async call sites) | Small |
| 3 | ARCH-01-003 | Replace hardcoded `"claude-haiku-4-5-20251001"` in `api/settings.py:250` with a config-driven model reference | Small |
| 4 | ARCH-01-004 | Remove unused `langchain-anthropic` pin from `requirements.txt` (or document why it's kept) | Small |

---

## 13. Overall: READY for next audit phase (Audit 02 — Agents)

No finding in this audit blocks proceeding to Audit 02. ARCH-01-001/002 are real and should be fixed before production, but they degrade an already-redundant observability path (activity_stream.py's SSE mechanism independently covers real-time UI needs) rather than corrupting task state, which is persisted through separate, verified-correct direct DB writes. Recommend fixing ARCH-01-003 (one line) opportunistically alongside whichever audit's fix batch touches `api/settings.py` next.

---

## 14. Fixes Applied (2026-07-24)

Per user direction, ARCH-01-001, ARCH-01-002, and ARCH-01-003 were fixed before proceeding to Audit 02. ARCH-01-004 (unused `langchain-anthropic` dependency) was explicitly deferred/skipped.

- **ARCH-01-001 [FIXED]** — Threaded a real `db: AsyncSession` parameter through `run_manager()` (new optional param, `backend/app/agents/manager.py`) and passed `db=db` at all 9 `publish_event()` call sites inside `run_manager()`/`run_epic_manager()`, plus both `publish_event()` call sites in `backend/app/api/epics.py`. Updated both real callers of `run_manager()` (`run_epic_manager()` in `manager.py`, and `launch_manager()` in `backend/app/api/agents.py`) to pass their already-in-scope `db` session through. All 11 direct `publish_event()` call sites in the codebase now persist to the `events` table. The 12th call site (`FleetBus`'s legacy forward in `fleet_events.py`) remains best-effort/non-persisting by design — it originates from `run_agent_graph()`, a sync function with no natural `AsyncSession` to thread through; threading a DB session into that path would require a materially larger restructuring than this fix's scope. Documented as a known, deliberate limitation rather than silently left ambiguous.
- **ARCH-01-002 [FIXED]** — Added `set_main_loop()`/`_main_loop` to `backend/app/fleet/fleet_events.py`, called once from `backend/app/main.py`'s `lifespan()` startup (`asyncio.get_running_loop()`, which runs on the real main loop). `FleetBus._publish_to_existing_bus()` now schedules the legacy-bus forward via `asyncio.run_coroutine_threadsafe(publish_event(legacy), _main_loop)`, which works correctly regardless of which thread `publish()` is called from (main loop or a `to_thread` worker) — replacing the previous `asyncio.get_event_loop()` call that silently raised and was swallowed inside worker threads. Falls back to `asyncio.get_running_loop()` + `create_task` for contexts where the app lifespan never ran (e.g. an async test calling `publish()` directly without starting the app). **Live-verified** with a standalone script mirroring the real production shape (a `to_thread` worker calling `publish(task_started(...))`, subscribed via `event_bus.subscribe()`) — the event now reaches the legacy bus; before the fix, this exact scenario would have silently dropped the event.
- **ARCH-01-003 [FIXED]** — `backend/app/api/settings.py:250` now reads `get_settings().model_router` instead of the hardcoded `"claude-haiku-4-5-20251001"` literal.
- **ARCH-01-004 [SKIPPED]** — Per user instruction, not addressed this round.

**Verification:** `pytest tests/ -q` → 2758 passed, 0 failed, 55 skipped, 17 deselected (unchanged from pre-fix baseline — no regressions). `mypy app/ --strict` → 0 errors, 176 source files. All 6 modified files (`manager.py`, `api/agents.py`, `api/epics.py`, `api/settings.py`, `fleet/fleet_events.py`, `main.py`) syntax- and type-checked clean.
