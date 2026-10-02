# AUDIT 01 — MASTER ARCHITECTURE AUDIT
## Gridiron AI Developer Department ("Fleet OS")

**Audit ID:** ARCH-01 | **Report file:** `files/Qoder_audit report/01_ARCHITECTURE_AUDIT.md`
**JSON sidecar:** `files/Qoder_audit report/json/AUDIT_01_ARCHITECTURE.json`
**Run date:** 2026-10-02
**Auditor:** Qoder (read-only audit — no code was modified)
**Baseline commit:** `846021aa0c41b29170797f1c30f3c1c3271d3115` (main, 2026-09-30)
**Working tree state:** 45 uncommitted entries (pre-existing batches: "Production audit 09" 10:06–10:28 and "Audit 11 fixes" 10:49–10:50, made by other sessions — NOT by this audit). All findings below were verified against the files as they exist on disk at audit time.
**Standards followed:** `files/Audit/00b_AUDIT_STANDARDS.md` (evidence schema + JSON sidecar + no-padding rule)

---

## 0. IMPORTANT — GROUND-TRUTH STATUS

`PROJECT.md` — referenced by every audit prompt as "ground truth for what should exist" — **does not exist anywhere in the repository** (`find . -iname "PROJECT.md"` → empty, excluding `repos/` and `node_modules/`). Nearest substitutes found: `README.md` (root, 19.5 KB) and `files/What_is/PROJECT_MASTER_GUIDE.md`.

**Consequence:** every "per PROJECT.md" claim in the audit prompts could not be checked against the document itself. Where the audit prompt states a fact about the code (e.g. "base_graph.py agents do not have a checkpointer"), this report **verifies it against the actual code and flags it when the prompt is stale** (see ARCH-01-004).

---

## 1. Executive summary

The architecture is a genuine, coherent two-layer multi-agent system: a durable epic-level planning graph (`pipeline/graph.py`) with a real Postgres checkpointer, and a shared per-agent execution scaffold (`base_graph.py`, now also Postgres-checkpointed as of the Gap-21/T2-B2 work) driven by ~91 agent modules. The Fleet OS layer (49 modules under `app/fleet/`) is densely wired — no module-level orphans were found — and the 62-migration schema chain is perfectly linear with the live DB at head. The two open High findings are behavioral, not structural: (1) `launch_manager`'s exception handler never transitions the task, leaving tasks permanently stuck in "coding" with no self-service recovery; (2) simple-mode cost estimates use hardcoded, stale, wrong-tier prices (~3.75× understatement vs. the configured Sonnet rates). Two agent modules (`prompt_engineer_agent`, `ux_design_agent`) exist, are tested, and auto-register — but no UI or automated flow can ever dispatch them. Overall: fundamentally sound; fix the two High findings before production use.

---

## 2. Architecture score

**Score: 82 / 100**

Justification: strong bones (clean graph separation, both graphs now have durable checkpointers wired at startup/shutdown, dense fleet wiring, linear migrations, typed event bus, consistent FE/BE camelCase contract, mypy/tsc/eslint/vitest all green). Deductions: one High-severity reliability asymmetry in the orchestration entry points (ARCH-01-001), one High-severity cost-accuracy/config-sprawl defect (ARCH-01-002), two Mediums (dead-capability exposure, stale audit-brief premise requiring downstream correction), and a set of honest Lows (managed import cycles, missing manager-phase run tracking, residual hardcoded tuning constants, silent MemorySaver fallback).

---

## 3. System documentation (Phase 1 output)

### 3.1 Textual system diagram

```
Browser (Next.js 15 App Router, 21 pages)
  └── apps/web/lib/api.ts (722 lines, single apiFetch chokepoint)
        └── /api/* (Next rewrites → FastAPI :8000, 143 endpoints, 21 router files)

FastAPI (backend/app/main.py)
  ├── lifespan startup: init_checkpointer()          ← pipeline graph   (main.py:1566)
  │                     init_agent_checkpointer()    ← worker agents    (main.py:1567)
  │                     ensure_all_agents_registered() (main.py:1489-1491)
  ├── RBAC middleware + rate limiting (slowapi) + budget gate
  └── Routes
        ├── POST /api/tasks {mode: simple|full|auto}  → launch_planner | launch_planning_pipeline | launch_router
        ├── POST /api/tasks/{id}/approve              → launch_coder (simple / routed)
        ├── POST /api/tasks/{id}/pipeline/approve     → resume_planning_pipeline → launch_manager → run_manager
        ├── POST /api/chat/sessions/{id}/messages     → StreamingResponse text/event-stream (chat.py:159-206)
        ├── POST /api/specialized-agents/dispatch     → FleetManager.select() by capability → dynamic agent import
        └── POST /api/specialized-agents/{name}/run   → generic per-agent runner

Execution layers
  ├── Planner/Coder (simple mode): worktree → agent run → git commit → diff → ready_for_review
  └── Full mode: run_manager (plain async, manager.py:1483)
        └── _topological_subtask_waves (manager.py:121)
              └── _dispatch_one_subtask (manager.py:274) → fleet_manager.select("frontend_development"|"backend_development")
                    └── dev → qa → review per subtask (retries, failure ladder)
                        └── blocked | completed → transitions + git-push approval record

State stores: PostgreSQL 16 + pgvector (51 tables, 62 migrations, at head 062)
              Redis 8 (event bus stream, queues: rq)
              LangGraph checkpoints (two independent AsyncPostgresSaver instances)
```

### 3.2 Three real flows traced end-to-end

**(a) Simple task:** POST /api/tasks (tasks.py:168, `resolved_mode = mode or get_settings().pipeline_mode`, tasks.py:576) → `launch_planner` (tasks.py:423) → plan stored → human approves via POST /{id}/approve (tasks.py:647-713) → `launch_coder` (agents.py:866): bootstrap-if-blank (agents.py:896-926) → `create_worktree` → credential-vault env (935-946) → `_task_images` (948) → `_run_executors` → git add/commit (983-1005) → `get_diff` → `transition_task("testing")` → `("ready_for_review")` (1020-1021) → `_record_git_push_approval` (1033-1041).

**(b) Full pipeline:** POST /{id}/pipeline/approve (tasks.py:753) → `resume_planning_pipeline` (agents.py:283) → `resume_pipeline` (pipeline/graph.py:293; `ainvoke(Command(resume=...))`, thread_id `f"task-{task_id}"`) → on approve: `transition_task("ready_for_review")` + `_spawn_tracked(launch_manager(...))` (agents.py:343-352) → `launch_manager` (agents.py:470): worktree (496) → images (510-518) → credentials (525-533) → `run_manager` (543) → per-subtask waves → dev/qa/review → completed? diff + `transition_task("testing")` + `("ready_for_review")` + git-push approval (574-598) : blocked (599-613).

**(c) Chat SSE:** `createChatSession` (api.ts:689) → POST /api/chat/sessions (chat.py:136) → POST /sessions/{id}/messages → `StreamingResponse(..., media_type="text/event-stream")` (chat.py:159-206); live stream GET /sessions/{id}/stream (chat.py:215-238); `confirmChatAction` → POST /confirm (chat.py:321); `stopChatTurn` → POST /stop (chat.py:359). FE client functions verified present in api.ts:689-723.

### 3.3 Two-graph map (verified)

| | `pipeline/graph.py` (epic planning) | `base_graph.py` (per-agent scaffold) |
|---|---|---|
| Nodes | `pm`, `architect`, `decomposer`, `human_review` (graph.py:201-204) | `call_llm`, `execute_tools`, + optional `planner_node`, `memory_hook_node`, `reflection_node`, `critique_node`, `replan_node` (base_graph.py:3466-3488) |
| Checkpointer | `AsyncPostgresSaver` via `init_checkpointer` (graph.py:28-55), fallback `MemorySaver` (graph.py:21, 52-55) | `AsyncPostgresSaver` via `init_agent_checkpointer` (base_graph.py:69-96), fallback `MemorySaver` (base_graph.py:65, 93-94). Compiled with checkpointer at base_graph.py:3572 |
| HITL | `interrupt_before=["human_review"]` (graph.py:220), resume via `Command(resume=...)` | none (no interrupt) |
| Resume model | graph re-enters after the interrupt | explicit `resume_trace_id` param: fetch last checkpoint state, append message, carry forward counters, reuse AgentRun row (base_graph.py:3618-3674); deliberately re-enters at START, never mid-node resume |
| Startup wiring | `main.py:1566`, closed `main.py:1854` | `main.py:1567`, closed `main.py:1855` |
| thread_id | `f"task-{task_id}"` (graph.py:277, 309) | run's own `trace_id` (base_graph.py:3712, `run_config` at ~4027) |

**Which agents run under which graph:** only `pm`, `architect`, `decomposer` run as nodes of the pipeline graph (imported eagerly by graph.py:12-14). All other agents — 91 files containing 131 `run_agent_graph(...)` call sites (verified by grep) — run under `base_graph.py`. The audit prompt's "~72 agents" is outdated; the real population is 105 `.py` files under `app/agents/`, 91 of which call `run_agent_graph`.

### 3.4 Dependency graph / import cycles

AST scan of all 345 modules under `app/` found **28 import cycles**. Spot-verified 3 representative cycles (repository↔credential_vault, temporary_agent↔barot_agent, tools↔type_check): all are **broken by lazy function-level imports** — e.g. `app/db/repository.py` top-level imports are only `app.config` + `app.db.models` (lines 14-15), and `app/security/credential_vault.py` has **zero** top-level `app.*` imports. The app imports and runs cleanly; these are managed cycles, not runtime-breaking ones (see ARCH-01-005).

### 3.5 Event flow

`FleetEventType` has **exactly 8 values** (fleet_events.py:41-49): TASK_CREATED, TASK_STARTED, TASK_COMPLETED, TASK_FAILED, REVIEW_REQUESTED, LESSON_PUBLISHED, HEALTH_UPDATED, MEMORY_CREATED. No 9th type invented. `tests/test_event_compliance.py` exists and enforces the canonical type list. ~23 `publish(...)` call sites in `app/` across: `agents/manager.py:435`, `agents/base_graph.py` (1813, 1840, 1906, 3186, 3911, 4222, 4322, 4323, 4388, 4396), `main.py:597`, `api/agents.py:117,136`, `api/fleet_dashboard.py:204,303`, `fleet/agent_registry.py:191`, `fleet/failure_ladder.py:99,178,212`, `fleet/enhancement_rollback.py:263`, `fleet/bg_process_registry.py:399,429`. Spot-checked 7 sites — all pass the *real* task id in `task_id=` and the run correlation id in `trace_id=` separately (e.g. manager.py:435-443 `task_created(task_id=str(task_id), ..., trace_id=manager_trace_id)`; base_graph.py:3911 `task_started(task_id=task_id, ..., trace_id=tid)`). The documented historical task_id/trace_id bug shows no regression in sampled sites.

### 3.6 DB schema flow

62 Alembic migrations in `backend/migrations/versions/`, **perfectly linear**: single root `001_initial_schema.py` → single head `062_documentation_score.py`, no duplicate numeric prefixes, no branches (AST-verified by walking every `revision`/`down_revision` pair). Live dev DB `alembic_version` = `062` (verified via psql). 51 tables in `public` schema. Per-migration content detail is deferred to Audit 06.

### 3.7 Memory systems (data flow verification)

Two distinct systems confirmed in code, matching the documented design:
- **In-process `LessonStore`** (`base_graph.py:310+`): `Lesson` dataclass + in-memory store; `_persist_lesson_async` (base_graph.py:322+) does best-effort non-blocking DB write via the main loop.
- **Durable Postgres memory**: `app/memory/store.py` (`memory_embeddings`, voyageai embeddings) and `app/fleet/versioned_memory.py` (draft→published→promoted version history). Verified real call: `base_graph.py:3212` `get_versioned_memory_store().publish(...)`; also `quality_score.py:108` → `memory_score.get_latest_memory_score`. Deep dive is Audit 03.

### 3.8 Technology fit (verified against requirements.txt)

LangGraph 1.2.7 + langgraph-checkpoint-postgres 3.1.1 / psycopg 3.3.4 → matches the two persistent checkpointer implementations; FastAPI 0.139 + SQLAlchemy 2.0.51 async + asyncpg + Alembic 1.18.5 → coherent async stack; pgvector 0.4.2 + voyageai 0.4.1 → embeddings; anthropic 0.115.1 primary SDK; **Groq 1.5.0 correctly test-isolated** — `USE_GROQ=false` forced in `tests/conftest.py:66` (the documented fix still holds); `google-genai` carries its own "TEMPORARY, easily removable" note in requirements.txt. No framework replacement suggestions (deliberate build choices respected). Note: `openai==1.109.1` and `boto3` are present in requirements but their usage was not traced in this audit (deferred to Audit 06/09).

---

## 4. Findings (evidence schema per 00b_AUDIT_STANDARDS.md)

### ARCH-01-001 — [HIGH] `launch_manager` exception path never transitions the task; tasks stuck in "coding" forever

- id: ARCH-01-001
- severity: High
- file: `backend/app/api/agents.py`
- location: `launch_manager` (exception handler)
- line: 615-620
- finding: When `run_manager()` or any step of `launch_manager` raises, the exception handler updates `pipeline_state` to "blocked" and writes a log, but never calls `transition_task(...)`, so `dev_tasks.status` remains "coding" (set at line 500). Both sibling entry points do this correctly: `launch_coder` calls `transition_task(db2, task_id, "blocked")` (line 1047) and `launch_planning_pipeline` calls `update_pipeline_state` + `transition_task` (lines 271-277). The codebase itself documents why this matters (agents.py:261-269): `restart_task` refuses tasks in ("planning","coding","testing") with HTTP 409, so a stuck "coding" task has no self-service recovery — only manual DB intervention. The normal (non-exception) blocked path in `launch_manager` does it right (line 602), and also calls `preserve_worktree(task_id)` (line 600) — the exception path omits BOTH the transition and `preserve_worktree`.
- evidence: `except Exception as e: logger.exception(...); async with factory() as db2: await update_pipeline_state(db2, task_id, "blocked"); await append_log(db2, task_id, "pipeline_error", f"Manager failed: {e}")` — agents.py:615-619. Compare agents.py:1047 `await transition_task(db2, task_id, "blocked")` (launch_coder) and agents.py:272-273 `await update_pipeline_state(db2, task_id, "blocked"); await transition_task(db2, task_id, "blocked")` (launch_planning_pipeline).
- production_impact: Any unexpected exception during full-pipeline coding (DB error, cancellation, unhandled edge in run_manager, OOM-killed background task) leaves the task permanently in "coding" with a stale UI and a 409 on restart; the worktree is also not preserved, so partial work can be pruned. Requires manual DB surgery to recover.
- confidence: High
- recommendation: In the except block, mirror launch_planning_pipeline: wrap `update_pipeline_state` + `transition_task(db2, task_id, "blocked")` in a try/except (TransitionError, ValueError) guard, and call `preserve_worktree(task_id)` before the alert. 3-line change in the same handler.
- effort: Small (single file)

### ARCH-01-002 — [HIGH] Simple-mode cost estimates use hardcoded stale rates ~3.75× below the configured Sonnet prices

- id: ARCH-01-002
- severity: High
- file: `backend/app/api/agents.py`
- location: module constants `_COST_PER_INPUT_TOKEN` / `_COST_PER_OUTPUT_TOKEN`, `_estimate_cost`, call sites
- line: 33-34, 66-69 (definition); 727, 960 (callers)
- finding: `launch_planner` (line 727) and `launch_coder` (line 960) compute recorded `cost_estimate` values from module-level hardcoded constants `0.0000008`/`0.000004` (comment: "Haiku cost estimate: ~$0.80/M input, $4.00/M output"). The configured rates in `app/config.py` are `cost_per_input_token = 0.000003` / `cost_per_output_token = 0.000015` (Sonnet, config.py:192-201), and the coder agents run `model_coder = "claude-sonnet-5"` (config.py:32-34). Full mode does it correctly via `compute_actual_cost_usd()` which uses `settings.cost_per_input_token` (manager.py:224-249). So simple-mode cost is recorded at ~3.75× lower than the same tokens would be billed (0.0000008 vs 0.000003 = 3.75×; 0.000004 vs 0.000015 = 3.75×), and the constants bypass config entirely (config-sprawl + tier mismatch).
- evidence: `_COST_PER_INPUT_TOKEN = 0.0000008` / `_COST_PER_OUTPUT_TOKEN = 0.000004` (agents.py:33-34); `cost = _estimate_cost(tokens_in, tokens_out)` (agents.py:960, 727); `cost: float = tokens_in * settings.cost_per_input_token + tokens_out * (settings.cost_per_output_token)` (manager.py:246-248); `cost_per_input_token: float = Field(default=0.000003, ...)` (config.py:192-194).
- production_impact: `agent_runs.cost_estimate` and every cost dashboard/aggregate fed from it (cost page, epic cost rollups) understate real spend for all simple-mode tasks by ~3.75×; budget/cost decisions made from these numbers are wrong. Money is still spent at full rate — only the accounting is wrong.
- confidence: High
- recommendation: Delete the two constants and pass `get_settings()` rates into `_estimate_cost` (or reuse `manager.compute_actual_cost_usd`); tie the rate to the executors' real tier via the existing config fields. Small diff in agents.py only.
- effort: Small (single file)

### ARCH-01-003 — [MEDIUM] Two fully-built agents are unreachable from any UI or automated flow

- id: ARCH-01-003
- severity: Medium
- file: `backend/app/agents/prompt_engineer_agent.py`, `backend/app/agents/ux_design_agent.py` (plus `backend/app/api/specialized_agents.py`, `apps/web/`)
- location: `run_prompt_engineer_agent` (line 165), `run_ux_design_agent` (line 148), capability dispatch path
- line: prompt_engineer_agent.py:165/228; ux_design_agent.py:148/213; specialized_agents.py:586 (dispatch), 655 (/run), 714 (/run-sync)
- finding: Both agents exist with role files (`backend/roles/prompt_engineer_agent.md`, `backend/roles/ux_design_agent.md`), model entries (`app/fleet/agent_models.json:94,98`), tests (`tests/test_batch17_agents.py`, `tests/test_submit_ux_design_agent_hardening.py`, `tests/test_day8_role_prompts.py`) and `_register()` hooks that run at startup via `ensure_all_agents_registered()` (capability_registry.py:158-181, called at main.py:1489-1491). However: (a) no module anywhere statically imports or calls their run functions (repo-wide grep: only self-references); (b) their declared capabilities `"prompt_engineering"`, `"ui_ux_design"`, `"design_system_review"` are requested by **zero** code paths — the only capability strings ever passed to `FleetManager.select()` in the manager loop are `"frontend_development"`/`"backend_development"` (manager.py:392-397); (c) the frontend never calls the generic specialized-agents endpoints (zero references to `/api/specialized-agents` in `apps/web/`), so no button or page can start them. The only theoretical dispatch path is a raw external API call to POST /api/specialized-agents/dispatch with `required_capability: "prompt_engineering"`/`"ui_ux_design"` — machine-reachable, human-unreachable, and never invoked by any pipeline.
- evidence: capability lists in `_register()`: `capabilities=["prompt_engineering"]` (prompt_engineer_agent.py:238) and `capabilities=["ui_ux_design", "design_system_review"]` (ux_design_agent.py:224); manager's only requested capabilities: `required_capability = ("frontend_development" if subtask_type == "frontend" else "backend_development")` (manager.py:392-396); `grep -rn "ui_ux_design\|prompt_engineering" app/` → no hits outside the two agent files; `grep -rn "specialized" apps/web/` → one stale comment only (roadmap/page.tsx:20), no fetch calls.
- production_impact: Feature-exposure gap: two "capabilities" advertised in the roster/registry cannot be exercised by any product surface; if a user asks for prompt engineering or UX design, nothing routes to them. Silent dead weight that will drift from the rest of the code (and reviewers will keep counting them as real capability coverage).
- confidence: High (static facts verified); Medium for the raw-API dispatch claim (path read, not executed)
- recommendation: Either wire them into a real entry point (e.g. allow the smart-router/decomposer to emit subtask types mapped to these capabilities, or add a UI button on /agents calling /{name}/run), or mark them clearly as API-only tools in the roster docs and add a capabilities smoke test asserting every registered capability is requestable somewhere.
- effort: Medium (few files)

### ARCH-01-004 — [MEDIUM] Audit-prompt premise is stale: base_graph.py DOES have a Postgres checkpointer and real resume semantics

- id: ARCH-01-004
- severity: Medium (documentation/audit-process risk, not a code defect)
- file: `backend/app/agents/base_graph.py`, `backend/app/main.py`
- location: `init_agent_checkpointer` / `run_agent_graph(resume_trace_id=...)`
- line: base_graph.py:65-96, 3572, 3618-3674; main.py:1566-1567, 1854-1855
- finding: Audit prompt 01 instructs auditors to "confirm ... base_graph.py agents do not have a checkpointer". This is **false as of the current code**: base_graph.py has `_agent_checkpointer` (AsyncPostgresSaver via `init_agent_checkpointer`, MemorySaver fallback), compiled at line 3572, initialized/closed in the FastAPI lifespan (main.py:1566-1567, 1854-1855), and `run_agent_graph()` implements genuine resume via the `resume_trace_id` parameter (T2-B2, base_graph.py:3618-3674) — including checkpoint-state fetch, history carry-forward, and AgentRun-row reuse. The "two graphs trap" audit check must therefore be re-scoped: the remaining difference is _resume mechanics_ (pipeline: interrupt/Command resume; base_graph: re-enter-at-START re-assessment posture, deliberately not mid-node replay — see the extensive rationale at base_graph.py:3655-3673), not "one has a checkpointer, one doesn't". Downstream audits (esp. 04, 08, 12) must use this corrected premise.
- evidence: `_agent_checkpointer: Any = MemorySaver()` (base_graph.py:65); `async def init_agent_checkpointer(database_url: str) -> None:` (base_graph.py:69); `return g.compile(checkpointer=_agent_checkpointer)` (base_graph.py:3572); `await init_agent_checkpointer(settings.database_url)` (main.py:1567); `resume_trace_id: str = ""` + its 56-line design comment (base_graph.py:3618-3674).
- production_impact: If an auditor (or an LLM fixing from the reports) trusts the stale premise, fixes will target a non-existent "no checkpointer" state and miss the real invariants (e.g. resume re-enters at START; tool_handler reconstruction requirements at base_graph.py:3636-3641).
- confidence: High
- recommendation: No code change. In every downstream audit report, carry this corrected fact forward; verify one runtime resume path (tests `test_t2b2_worker_agent_resume.py`, `test_gap21_agent_checkpointer_postgres.py` exist and are skipped-by-default only if slow/LLM-marked — they are part of the baseline run).
- effort: Small (documentation/process)

### ARCH-01-005 — [LOW] 28 import cycles exist (all managed via lazy imports; sweep recommended)

- id: ARCH-01-005
- severity: Low
- file: `backend/app/**` (cross-cutting)
- location: module import graph
- line: n/a (structural)
- finding: An AST scan of all 345 modules under `app/` found 28 cycles, e.g. `app.db.repository → app.security.credential_vault → app.fleet.audit_log → app.fleet.fleet_events → app.event_bus.bus → app.db.repository` (length 6) and the `tools/delegate/delegation/*` family (lengths 3-9). Three cycles were spot-verified to be broken by function-level (lazy) imports rather than top-level imports; the app imports cleanly and mypy passes over 497 files, so none are runtime-breaking today. They remain a fragility: any refactor that promotes a lazy import to module level in one of these pairs can produce a real circular-import failure.
- evidence: Scan output (345 modules analyzed, 28 cycles); repository.py top-level app imports = only lines 14-15 (`app.config`, `app.db.models`); credential_vault.py top-level app imports = none.
- production_impact: None today. Latent startup-import risk under refactoring; also makes import-order debugging harder.
- confidence: Medium (3 of 28 cycles hand-verified; the rest inferred from the same scan + app booting + mypy clean; recommend a manual sweep when convenient)
- recommendation: Add a CI check using `import-linter` contracts (forbidden contracts) or a small AST test asserting top-level `app.*` imports do not participate in cycles; at minimum document the 28-cycle list in one place.
- effort: Medium (cross-cutting check, no behavior change)

### ARCH-01-006 — [LOW] `launch_manager` phase creates no AgentRun row (no heartbeat / orphan-recovery coverage for the manager loop itself)

- id: ARCH-01-006
- severity: Low
- file: `backend/app/api/agents.py`, `backend/app/agents/manager.py`
- location: `launch_manager`
- line: 470-620 (launch_manager); compare agents.py:886 (launch_coder's `create_agent_run`)
- finding: `launch_coder` (agents.py:886) and `launch_planner` (agents.py:695) create an `AgentRun` row, register a heartbeat, and `finish_agent_run` on all exits. `launch_manager` does none of that (grep: zero `create_agent_run`/`finish_agent_run` in agents.py's manager section and zero in manager.py). Sub-agents dispatched from `run_manager` carry their own runs (via their own run functions), but the manager/phasing loop itself is invisible to run metrics, heartbeat monitoring, and orphan recovery.
- evidence: `run = await create_agent_run(db, task_id, run_label, settings.model_coder)` (agents.py:886, coder) vs. absence in agents.py:470-620; `grep -n "create_agent_run\|finish_agent_run" app/agents/manager.py` → empty.
- production_impact: Manager-phase wall-clock time is not attributed to any agent run (only `record_orchestration_time` metrics at agents.py:540-554); if the manager task hangs between sub-agent dispatches, no heartbeat exists for it (sub-agent heartbeats only cover their own spans).
- confidence: Medium (absence verified; whether an AgentRun for a non-LLM orchestrator is even desired is a design question)
- recommendation: Decide explicitly: either add a lightweight AgentRun row around launch_manager (so /agents and orphan-recovery see it), or document that manager is intentionally untracked. One-file change if adopted.
- effort: Small (single file)

### ARCH-01-007 — [LOW] Residual hardcoded tuning constants outside config.py (targeted list)

- id: ARCH-01-007
- severity: Low
- file: multiple
- location: module-level constants
- line: see evidence
- finding: The audit-named config-sprawl fixes are intact (CORS origins configurable at config.py:2114; event-bus/groq retry settings present; `USE_GROQ=false` conftest isolation at tests/conftest.py:66 — no regression). A residual set of behavior-affecting constants still lives in code rather than Pydantic settings. Highest-signal candidates (not an exhaustive list — most other module constants are benign tool tuning): `app/memory/store.py:375-376` `_EMBED_ATTEMPTS = 3`, `_EMBED_BACKOFF_SECONDS = 0.5`; `app/event_bus/redis_streams.py:29` `_MAXLEN = 10_000` (production memory bound); `app/tools/execution/health_check.py:103` hardcoded `http://localhost:{port}/health`; `app/api/agents.py:33-34` (see ARCH-01-002, the one with real impact).
- evidence: `_EMBED_ATTEMPTS = 3` / `_EMBED_BACKOFF_SECONDS = 0.5` (store.py:375-376); `_MAXLEN = 10_000  # keep at most 10 k events in the stream` (redis_streams.py:29); `f"http://localhost:{port}/health"` (health_check.py:103). Counter-evidence (fixes intact): `default="http://localhost:3000", description="Comma-separated list of allowed CORS origins..."` (config.py:2114-2115).
- production_impact: Ops cannot tune embedding retry or redis stream retention without a code deploy; localhost health URL breaks if backend port/host changes outside default.
- confidence: Medium
- recommendation: Migrate only the listed high-signal items into `Settings` (with current values as defaults); leave pure tool-tuning constants as-is. Scoped diff, few files.
- effort: Small

---

## 5. Orphan-module list (verdict)

**No true module-level orphans found under `app/fleet/` (49 modules) or `app/agents/` (105 files).** Every audit-named wiring was re-verified present:

| Module | Status | Proof (caller) |
|---|---|---|
| `fleet/versioned_memory.py` | WIRED | base_graph.py:3212 `get_versioned_memory_store().publish(...)` |
| `fleet/fleet_checkpoint.py` | WIRED | api/fleet_dashboard.py:152,181; fleet/failure_ladder.py:36 |
| `fleet/tool_discovery.py` | WIRED | imported by base_graph.py |
| `fleet/prompt_registry.py` (deploy) | WIRED | app/agents/tools.py:7330-7351 (`_propose_and_deploy_role_prompt`) |
| `fleet/structural_diff.py` | WIRED (CI) | scripts/ci_tech_debt_scan.py:23, executed by .github/workflows/ci.yml:121 |
| `fleet/memory_score.py` | WIRED | quality_score.py:108 |
| `fleet/docker_health.py`, `fleet/git_worktree_health.py` | WIRED | monitoring_agent.py:235,246 |
| `fleet/release_retrospective.py` | WIRED | main.py:1295-1301 |
| `fleet/dependency_resolver.py` | WIRED | tools/integrations/check_dependency_conflicts.py:16 |

The only "dead" artifacts are at the *capability-exposure* level, not module level: `prompt_engineer_agent` / `ux_design_agent` are dynamically imported (so registered) but never dispatched by any flow — reported as ARCH-01-003.

## 6. Config-sprawl findings

See ARCH-01-002 (High — pricing constants with a real 3.75× impact) and ARCH-01-007 (Low — residual tuning constants). Known historical fixes verified intact: CORS origins (config.py:2114), Groq isolation (tests/conftest.py:66), and retry settings present in config. No hardcoded Anthropic model IDs in app code (only in comments, `fleet/model_router.py:9,88`).

## 7. Frontend/backend contract drift findings

**No drift found in the sampled surface.** Mechanism: the backend manually serializes camelCase dicts (e.g. `_task_to_dict` at `app/api/tasks.py:135-158` → `filesTouched`, `assignedAgent`, `finalSummary`, `repoId`, `createdAt`...) and `api/metrics.py:14,27` uses Pydantic `alias_generator=to_camel`. The `apps/web/lib/api.ts` interface definitions (DevTask:57-74, PipelineStateClient:76-83, TaskPr:86-90, Epic:312-323, RepoRecord:422-432, SystemMetrics:482-492, RoadmapRecord:558-565, AgentRegistryEntry:590-601, AppSettings:613-626) match those serializers field-for-field in the sampled cases. `api.ts` maintains a single `apiFetch` chokepoint (api.ts:15-23). Confidence: High for the sampled routes; a full 143-endpoint sweep was not performed (see remaining-risk note in conclusion).

## 8. Recommended fixes (diff-sized tasks)

1. **agents.py exception handler parity** (ARCH-01-001): add guarded `update_pipeline_state`+`transition_task(...,"blocked")` and `preserve_worktree` to `launch_manager`'s except block — copy the launch_planning_pipeline pattern (agents.py:271-277).
2. **Cost estimate fix** (ARCH-01-002): remove `_COST_PER_*` constants; make `_estimate_cost` read `get_settings()` rates (same fields manager.py:246-248 uses).
3. **Capability exposure decision** (ARCH-01-003): wire prompt_engineer/ux_design into a dispatcher subtask-type mapping or the /agents UI, or mark API-only in the roster; add a test that every registered capability is requestable.
4. **Carry-forward correction** (ARCH-01-004): downstream reports (04/08/12) must state base_graph has a Postgres checkpointer + resume_trace_id semantics.
5. **Import-cycle guard** (ARCH-01-005): CI import-linter contract or AST test.
6. **Manager run tracking decision** (ARCH-01-006): add AgentRun row or document intentional exclusion.
7. **Config migration** (ARCH-01-007): move `_EMBED_ATTEMPTS`, `_EMBED_BACKOFF_SECONDS`, `_MAXLEN` into Settings.

## 9. Overall verdict

**READY** for the next audit phase (02-14). The architecture is coherent, both graphs' checkpointers are real and wired, fleet wiring is dense with zero module orphans, migrations are linear and the DB is at head, and the full toolchain baseline is green (mypy: 497 files clean; tsc: 0 errors; eslint: 0 errors; vitest: 52/52 passing). The two High findings (ARCH-01-001, ARCH-01-002) must be fixed before production release — they are small, localized diffs. The audit-prompt's "no checkpointer in base_graph" premise is stale and is corrected here for all downstream audits.

**Remaining risk / not fully swept:** (a) full 143-endpoint FE/BE drift sweep not performed (spot-checked only); (b) only 3 of 28 import cycles hand-verified; (c) raw-API dispatch path for the two unwired agents read but not executed. Each is marked with its confidence above.
