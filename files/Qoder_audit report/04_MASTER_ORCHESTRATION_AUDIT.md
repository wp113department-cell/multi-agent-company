# 04 — Master Orchestration Audit

- **Audit ID:** 04
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` (HEAD, "Production audits 09 and 11", 2026-10-02 11:11 +0530)
- **Run date:** 2026-10-02
- **Method:** read-only static verification with file:line evidence against HEAD. No LLM-driven tests executed in this audit (full backend suite running concurrently; see §9). The working tree is *dirty* because a separate concurrent process ("Production audit 12") is editing `backend/app/api/{auth,epics,fleet_dashboard}.py` and adding untracked test/e2e files — all citations below were re-verified against the on-disk content and match HEAD semantics.
- **Scope per brief:** two-entry-point parity (simple vs full), epic manager path, state machine, human-in-the-loop gates, failure ladder, concurrency/resource governance, idempotency, failure-scenario classification (Phase 6C), prioritized fix list, 0–100 score.

---

## 1. Headline — Entry-Point Parity Table

Four real orchestration entry points exist, not two:

| Stage | simple (`PIPELINE_MODE=simple`) | full (`=full`) | auto (`=auto`, router) | epic (`POST /api/epics`) |
|---|---|---|---|---|
| Entry | `POST /tasks/{id}/run` → `launch_planner` (tasks.py:399, agents.py:686) | → `launch_planning_pipeline` (agents.py:75) | → `launch_router` (agents.py:636); small/medium → routed plan, large → full | `_launch_epic_manager` → `run_epic_manager` (epics.py:380, manager.py:1823) |
| Planning | single planner LLM call, no graph | LangGraph PM→Arch→Decomp, **pauses** at `human_review` (graph.py:220 `interrupt_before` + graph.py:174 `interrupt()`) | none for small/medium (plan = router text, agents.py:663-667); full for large (agents.py:659-661) | `run_planning_pipeline` **called but its pause is never resumed/approved** (manager.py:2184); subtasks taken pre-approval |
| Plan-approval gate | `ready_for_review` + `approve_task` (tasks.py:657) | `plan_review` pending row + `/pipeline/approve` (agents.py:196-219, tasks.py:762) | `ready_for_review` + `approve_task` (agents.py:672) | **none** — epic batches review only at the end (`/epics/batch-review`) |
| Coding dispatch | `approve_task` → `launch_coder` (tasks.py:714) | `resume_planning_pipeline` → `launch_manager` → `run_manager` (agents.py:343-352, 470) | same as simple, with routed specialists (tasks.py:700-722) | `_coding_node` → `run_manager` with **fan-out default ON** (manager.py:2325, 2346) |
| Worktree | `create_worktree(task_id, repo)` — no `epic_id` (agents.py:928) | no `epic_id` (agents.py:496) | no `epic_id` (via launch_coder) | no `epic_id` (manager.py:2325) |
| Git-push gate | via `launch_coder` (agents.py:1033) | via `launch_manager` (agents.py:596) | via `launch_coder` | **none** (no `_record_git_push_approval` caller on epic path) |
| Failure end state | planner error → `blocked` (agents.py:739) | planning exception → `blocked` (agents.py:257-277); **manager exception → no transition** (§5, finding ORCH-04-101) | routing error → `blocked` (agents.py:682) | epic halt → `halted` w/ `halt_reason` visible (manager.py:2417-2467); hard exception → epic stuck, no recovery endpoint (§5, ORCH-04-108) |
| Child `DevTask` end state | `completed` via push flow (approvals.py:201-211) | same | same | **stuck in `planning` forever** (finding ORCH-04-103) |

Parity verdict: simple / full / auto converge on the same task lifecycle (planning → ready_for_review → coding → testing → ready_for_review → completed/blocked), with mode-specific planning gates. The **epic path is not at parity**: it bypasses the plan-approval gate without recording the decision, never completes the child `DevTask`, and has no push gate or child-task close-out.

---

## 2. State Machine (+ call-site verification)

`VALID_TRANSITIONS` (db/models.py:30-99) verified against every real `transition_task` call site:

- `pending → planning|blocked|failed|cancelled`; `planning → ready_for_review|blocked|rejected|failed|cancelled`; `ready_for_review → coding|blocked|rejected|completed|cancelled`; `coding → testing|blocked|failed|cancelled`; `testing → ready_for_review|blocked|failed|cancelled`; `rejected → planning|blocked|cancelled`; `blocked → planning|coding|failed|cancelled`; terminal: `completed|failed|cancelled`.
- `transition_task()` is an atomic CAS (`UPDATE … WHERE status IN (allowed) RETURNING id`, repository.py:377-435) — TOCTOU fix verified; double-restart double-dispatch guarded twice (pre-check tasks.py:471-481 + CAS reset tasks.py:489-502).
- Sweep of all `transition_task` call sites (api/ + fleet/ + specialized_agents.py) — every target is a legal transition; none found violating the table.
- `cancelled` is terminal and refused by resume (activity.py:38-40, 149-158); Stop vs Cancel distinction is real (activity.py:205-254).
- `awaiting_approval` is **not** a DevTask status (not in `VALID_TRANSITIONS`; no writer found) — it is only a `pipeline_state.stage`. The batch-review task filter (epics.py:195) uses it anyway → finding ORCH-04-109.
- `patch_status` (`PATCH /api/tasks/{id}`, tasks.py:231-244) is a generic manual-transition escape hatch (approver-only) — it is the only API-level recovery for a task stuck in `coding` (see ORCH-04-101).

---

## 3. Human-in-the-Loop Gates

Three real gates, all recorded in `pending_approvals` (`approval_gate.py`):

1. **plan_review** — recorded after the graph pause is confirmed (agents.py:196-219, `arequest_human_input(kind="plan_review", thread_id="task-{id}")`); resumed by `/api/tasks/{id}/pipeline/approve` (tasks.py:762) or `/api/approvals/{id}/approve` (approvals.py:83-145); both dispatch `resume_planning_pipeline` (agents.py:283).
2. **git_push** — `thread_id="task-{id}-push"`, recorded by `launch_manager` (agents.py:596) / `launch_coder` (agents.py:1033); resolution pushes and closes the task (approvals.py:148-224: `push_and_create_pr` → `completed` → worktree removal, ORCH-04-002/012 fixes verified).
3. **clarification** — `request_clarification` tool → `resume_planner_after_clarification` / `resume_coder_after_clarification` (agents.py:760-818, 1051-1106) with a `can_transition` guard.

Decision recording is compare-and-set (`approval_gate.py:183-231`, `.returning()` flip; ORCH-04-007 fix verified). Dual-endpoint gating inconsistency → finding ORCH-04-107.

---

## 4. Failure Ladder (verified rungs)

- **Retry:** per-subtask dev/QA/review loop, `manager_max_subtask_retries` (manager.py:554-653, 1537, ORCH-04-015); dev-error and blocking-finding both feed `should_retry`.
- **Checkpoint:** epic halt snapshots results (`failure_ladder.py` checkpoint, manager.py:1720-1734).
- **Rollback/Resume:** deliberately not auto-wired (documented, failure_ladder.py:48-60; no caller found — expected-not-found).
- **Escalate/Request-human-review:** single-subtask escalation + `request_human_review` on blocked subtasks (manager.py:1754-1777); reuse of "blocked" documented.
- **Abort:** epic-level abort emits `TaskFailed` with `transition=False` — launcher owns the status flip (manager.py:1735-1739 + launch_manager blocked path agents.py:599-613).
- **Orphan recovery:** `reconcile_orphaned_runs` (failure_ladder.py:282-422) resumes via `resume_registry` or marks failed+escalates; loop leader-gated and wired (main.py:1711-1715); resumable-agent slice is deliberate (resume_registry.py:19-35).
- **Gap:** the ladder does not cover the *launch_manager* wrapper itself or the *planning graph* across restarts (§5 findings ORCH-04-101, scenario 3).

---

## 5. Findings

### ORCH-04-101 — `launch_manager` generically-failed path never transitions the task out of an active status
- **Severity:** High · **File:** backend/app/api/agents.py:615-620 · **Confidence:** High
- **Finding:** the `except Exception` handler logs, sets `pipeline_state="blocked"` and alerts, but never calls `transition_task`. If the failure happens after the `coding` transition (L500), the task is stuck in `coding`; if before it (e.g. worktree creation, L496), stuck in `ready_for_review`.
- **Evidence:** agents.py:615-620 (no transition); contrast the explicitly fixed identical bug for planning (agents.py:257-277, comment "Blocker (audit_v1.md 4.3 #2): this handler used to log and alert but never transition the task out of 'planning' … leaving no self-service recovery path") and `launch_coder` (agents.py:1043-1048 does `transition_task(db2, task_id, "blocked")`). `restart_task` refuses `planning|coding|testing` with 409 (tasks.py:471-481); `run_task` accepts only `pending|rejected|blocked` (tasks.py:345-348). Only manual `PATCH /api/tasks/{id} {"status":"blocked"}` (tasks.py:231-244) or cancel recovers a `coding`-stuck task.
- **Production impact:** any generic exception in the manager pipeline (DB error, artifact write failure, diff capture) orphans the task in an active status with no automated or UI recovery; the same gap applies to a process crash mid-`launch_manager` (orphan recovery only covers `agent_runs`, not the launcher).
- **Recommendation:** mirror the planning fix — `update_pipeline_state` + `transition_task(db2, task_id, "blocked")` inside the handler, swallowing `TransitionError`/`ValueError`.
- **Effort:** S

### ORCH-04-102 — Leader-election pool sized for 16 loops but 20 loops registered; 4 loops never run
- **Severity:** High · **File:** backend/app/main.py:1625-1644, 1665-1792, 1341-1343 · **Confidence:** High
- **Finding:** `_leader_loop_names` has **16** entries (main.py:1625-1642) but **20** loops are launched via `_run_as_leader` (main.py:1665-1792). Four registered names are absent from the sizing tuple: `loop:versioned_lesson_consolidation` (L1685), `loop:memory_embeddings_consolidation` (L1692), `loop:agent_historical_performance_rollup` (L1699), `loop:documentation_score_compute` (L1772). The shared engine is created with `pool_size=len(_leader_loop_names)` = 16 and `max_overflow=0` (main.py:1341-1343), and each winning loop holds its connection for the loop's entire lifetime (`await run_loop()` inside `async with engine.connect()`, main.py:1375-1398).
- **Evidence:** 20 concurrent lock-holders need 20 connections; only 16 exist and are never released. In the single-instance case (comment: "this instance always wins its own uncontested locks", main.py:1619-1620) exactly 4 tasks block in `engine.connect()`, hit the default 30 s pool timeout, raise `TimeoutError` outside any `try`, and die **permanently** — no retry exists around `connect()`. Which 4 die follows scheduling; in creation order the last four (prompts_score_compute, documentation_score_compute, enhancement_quality_monitor, dependency_auto_dispatch) are the prime candidates. `leader_election_enabled` defaults to **True** (config.py:1642-1654). Docstring is also stale ("One shared engine for all 9", main.py:1621).
- **Production impact:** on every default deployment, ≥4 singleton background loops silently never run (candidates include memory-consolidation/agent-performance rollup/documentation scoring/dependency auto-dispatch), plus recurring "Task exception was never retrieved" noise. No log, metric, or health check surfaces the dead loops.
- **Recommendation:** derive the pool size from the actual registration list (single source of truth, e.g. build one tuple of `(name, loop)` pairs and size from it), or set `max_overflow ≥ 4`.
- **Effort:** S

### ORCH-04-103 — Epic entry point bypasses the plan-review gate and leaves the child DevTask permanently in `planning`
- **Severity:** Medium · **File:** backend/app/agents/manager.py:2130-2222 · **Confidence:** High (mechanics) / Medium (intent)
- **Finding:** `_planning_node` calls `run_planning_pipeline`, which "stops at human_review checkpoint" (graph.py:237-240): the graph pauses (graph.py:220 `interrupt_before=["human_review"]` + in-node `interrupt()` graph.py:174) and is **never resumed** for epic-created tasks. The node consumes the pre-approval subtasks and proceeds to conflict-check → coding, i.e. epic work executes with no plan approval recorded anywhere.
- **Evidence:** manager.py:2184-2197 (subtasks taken from the paused graph; no resume, no `arequest_human_input`); `save_subtasks` has exactly one real caller (`agents.py:190`) so epic tasks get **no `Subtask` rows** — `run_manager`'s `_db_subtask_rows` stays empty (manager.py:1559-1579) and every `update_subtask_status` is skipped (guard L988-1000); a grep of manager.py shows the epic-created `DevTask` (L2168-2180, `status="planning"`) is never transitioned by any epic code path; `epics.py` approve/reject never touch it either. The child task therefore stays `planning` forever: `restart_task` 409 (tasks.py:471-481), `run_task` 400 (tasks.py:345), absent from batch-review (epics.py:193-198), no diff/`files_touched` persisted (that write lives only in launch_manager, agents.py:579-581), and one dangling checkpoint thread per epic.
- **Production impact:** the two entry points are not at parity (headline table): epic children are ghost rows in the task list, epic output is reviewable only through the epic batch package, and no per-subtask status/diff history exists for epics.
- **Recommendation:** decide and make explicit — either (a) resume the paused graph through a real `plan_review` approval before `_coding_node` (record + resume like the task path), or (b) remove `human_review` from the epic planning invocation and document the epic batch review as the single gate; in both cases call `save_subtasks` and transition/close the child `DevTask` (`ready_for_review` on success, `blocked` on halt).
- **Effort:** M

### ORCH-04-104 — Epic approve/reject perform no downstream lifecycle actions
- **Severity:** Medium · **File:** backend/app/api/epics.py:249-314 · **Confidence:** High
- **Finding:** `POST /epics/{id}/approve` and `/reject` only flip `Epic.status` and publish an event. Nothing pushes the branch/creates a PR, nothing transitions the child `DevTask`, nothing removes/preserves worktrees, nothing records a git-push approval.
- **Evidence:** epics.py:267-278 (approve), 301-312 (reject). Contrast the task path: approvals.py:201-224 (`completed` transition + `remove_worktree`), tasks.py:143-157/743-757. `_record_git_push_approval` callers are only agents.py:596/1033 (task paths). Worktree retention prunes only `completed/failed/cancelled` tasks (config.py:840-843) — the epic child (ORCH-04-103) never reaches any of those, so its worktree is never pruned by the documented retention contract.
- **Production impact:** an approved epic has no completion side effects (no PR, no merged artifact trail); epic worktrees accumulate indefinitely; there is no epic analogue of the task `completed` terminal state.
- **Recommendation:** define the epic close-out: on approve, drive child tasks to a terminal state and run the worktree/PR decision; on reject, remove epic worktrees.
- **Effort:** M

### ORCH-04-105 — Fan-out (default ON for epics) runs concurrent DB work on one shared AsyncSession
- **Severity:** Medium · **File:** backend/app/agents/manager.py:1643-1664 · **Confidence:** High (mechanism) / Medium (loss frequency)
- **Finding:** the epic path passes `enable_fanout=get_settings().enable_subtask_fanout` (manager.py:2346) and that flag **defaults True** (config.py:310-314). `run_manager` then `asyncio.gather`s whole waves, passing the **same `db` session** to every concurrent `_dispatch_one_subtask` (manager.py:1643-1664, `db=db` L1655). Concurrent operations on one `AsyncSession` are not supported by SQLAlchemy; every affected call site swallows the resulting errors — `_persist_event` (bus.py:140-141), best-effort subtask status (manager.py:995-1000), `record_agent_run_outcome` (manager.py:1046-1052) — so the failure mode is **silent event/status loss**, not a crash. `publish_event`'s docstring claim "Events are ordered per task_id (sequential publish within a task pipeline)" (bus.py:188) has no enforcing mechanism once a wave runs >1 subtask.
- **Production impact:** under epic fan-out, `subtask.*`/`task.blocked` events and subtask status rows can silently vanish; audit/replay consumers (`get_unprocessed_events`) see gaps.
- **Recommendation:** serialize DB writes (per-task lock around publish/status writes, or a session per subtask, or a queue drained by the wave coordinator), and update the bus docstring to the enforced reality.
- **Effort:** M

### ORCH-04-106 — `queue_adapter` module docstring contradicts the code it documents
- **Severity:** Low · **File:** backend/app/pipeline/queue_adapter.py:10-27 · **Confidence:** High
- **Finding:** the docstring (ORCH-04-016) asserts "every real task-launch call site in api/tasks.py … dispatches via FastAPI's BackgroundTasks.add_task(...) directly, not queue().enqueue(...) — so QUEUE_BACKEND=rq currently has no effect on real task dispatch". The code contradicts this: `dispatch_job` (queue_adapter.py:322-364) is the single chokepoint all 10 real dispatch sites call (tasks.py:409, 420, 431, 526, 589, 599, 714, 815, 850, 1113) and it branches to `queue().enqueue(...)` when `queue_backend == "rq"` (L358-359). RQ is wired; the doc is stale.
- **Production impact:** an operator reading module docs will believe `QUEUE_BACKEND=rq` is inert and may mis-plan queue/worker operations; conversely this is exactly the "documentation contradicts code" class flagged by the zero-policy audit (11).
- **Recommendation:** rewrite the docstring to match dispatch_job's real behavior (asyncio=BackgroundTasks + wall-clock wrapper; rq=persistent enqueue).
- **Effort:** S

### ORCH-04-107 — Two plan-approval endpoints with inconsistent gating
- **Severity:** Low · **File:** backend/app/api/tasks.py:762-824 vs backend/app/api/approvals.py:83-145 · **Confidence:** Medium
- **Finding:** `/tasks/{id}/pipeline/approve` gates only on `pipeline_state.stage == "awaiting_approval"` and consumes no pending-approval row; `/api/approvals/{id}/approve` CAS-flips the row (ORCH-04-007 fix) but does not check `pipeline_state`. Either endpoint can be called while the other's state is still stale, and neither invalidates the other: two rapid `/pipeline/approve` calls both pass the stage check (stage flips only later, agents.py:344) and both dispatch `resume_planning_pipeline`. The eventual double launch is bounded — the final `transition_task(ready_for_review)` is a CAS and the loser skips the `launch_manager` spawn (agents.py:343-352 + generic handler 372-375) — but the second graph resume and a stale pending row in the approvals inbox remain.
- **Production impact:** double-click/duplicate approval produces redundant graph resumes, log noise, and an approval inbox item that can remain "pending" after the plan was already approved through the other endpoint.
- **Recommendation:** make one endpoint the single authority: have `/pipeline/approve` also flip the pending row (CAS) or remove it, and have the approvals path verify/rely on pipeline stage.
- **Effort:** S

### ORCH-04-108 — Hard exception in the epic manager leaves the epic in a non-terminal, unreachable status
- **Severity:** Low · **File:** backend/app/api/epics.py:418-419 · **Confidence:** Medium
- **Finding:** `_launch_epic_manager`'s `except` only logs. An exception escaping the epic graph (DB error in a node, unexpected integration error) leaves the epic in whatever status the last node set — `pending`, `planning`, or `coding` — with `halt_reason` unset. No endpoint recovers it: batch-review lists only `ready_for_review`/`pending_cost_approval` (epics.py:186-190), approve/reject require those plus `halted` (L261, L295), and `approve-cost` requires `pending_cost_approval` (L329-333).
- **Production impact:** a transient infra failure permanently strands an epic invisible to every review/recovery surface; only manual DB intervention recovers it.
- **Recommendation:** in the handler, reload the epic and set `status="halted"` + `halt_reason` (mirroring `_finalize_node`'s halted path), so it surfaces in batch review/reject.
- **Effort:** S

### ORCH-04-109 — Batch-review task filter uses a status the DevTask state machine never produces
- **Severity:** Low · **File:** backend/app/api/epics.py:193-198 · **Confidence:** High
- **Finding:** the task query filters `DevTask.status.in_(["ready_for_review", "awaiting_approval"])`, but `awaiting_approval` is not in `VALID_TRANSITIONS` (db/models.py:30-99) and no writer sets `DevTask.status="awaiting_approval"` (grep: only `pipeline_state.stage` uses that string). Tasks whose plan is paused for approval are in `planning` (tasks.py:399/512), so they are never listed here despite the docstring's stated intent (epics.py:183).
- **Production impact:** the batch-review surface cannot list plan-awaiting tasks; the only path to them is the approvals inbox. (If that is intentional, the filter value is still dead code.)
- **Recommendation:** either filter on `planning` tasks with `pipeline_state.stage == "awaiting_approval"`, or delete the dead value and fix the docstring.
- **Effort:** S

---

## 6. Verified Clean (this layer)

- Atomic task transitions with full call-site sweep (repository.py:377-435; all targets legal).
- Approval decision CAS + supersede logic (approval_gate.py:96-108, 183-231) — ORCH-04-007 double-decision fix verified in place.
- Restart double-dispatch guards (pre-check + CAS + transition CAS, tasks.py:471-520).
- Worktree stale-dir detection, registered-worktree check, move-aside, preserve sentinel (worktree.py:31-58, 106-121, 134-143) — ORCH-04-012 verified.
- Semaphores actually wired with bounded waits and blocked-result propagation (concurrency.py:121-215; manager.py:521-552, 596, 1849) — ORCH-04-009 verified.
- Conflict guard handles both plain-path and `{path,reason}` impacted-file shapes; held locks released on epic terminal (conflict_guard.py:59-92; manager.py:2450-2454, 2504-2510) — ORCH-04-010 verified.
- Per-subtask git-commit lock serializes commits across a fan-out wave (manager.py:709-744, 1607).
- Orphan-recovery loop runs, is leader-gated, and reuses the resume registry (failure_ladder.py:282-422, 489-511; main.py:1711-1715).
- Conditional `ready_for_review → completed` close-out after push (approvals.py:195-224; models.py comment ORCH-04-002 verified).
- `dispatch_job` wall-clock wrapper (1800 s) applied on the asyncio path (queue_adapter.py:290-364).
- Auto-router third path converges on the same gates (agents.py:659-682; tasks.py:700-722).
- Prior ORCH-04-001…016 fixes re-verified in code (only ORCH-04-016's *docstring* is now wrong — filed as ORCH-04-106).

## 7. NOT FOUND (checked, absent — expected or gap)

- Epic-manager graph checkpointer (deliberately absent; build_epic_manager_graph docstring manager.py:2565-2569).
- Epic push/PR path (`push_and_create_pr` only caller is approvals.py:180).
- Automatic resume of the planning graph after a process restart (`resume_pipeline` callers: only human approval flows; orphan recovery covers `agent_runs` only).
- Any `DevTask` transition inside manager.py (grep: 13 matches, none is a transition).
- `save_subtasks` caller in the epic path (single caller agents.py:190).
- `worktree_path(..., epic_id=...)` real caller (worktree.py:22 supports it; agents.py:496/928, manager.py:2325 all omit it — namespacing capability is dead code, cross-flagged to audit 11).
- Job revocation on cancel (activity.py cancel sets abort flag + status only; enqueued RQ jobs are not cancelled).
- Epic-level `plan_review`/`git_push` pending rows (`arequest_human_input` callers: agents.py:199/430, chat_agent.py, base_graph.py, request_clarification.py — none in manager.py/epics.py).
- Rollback/Resume auto-rung caller (documented as manual, failure_ladder.py:48-60).
- Per-wave DB-write serialization (see ORCH-04-105).

## 8. Phase 6C — Failure-Scenario Classification

Definitions: **Graceful** = auto-recovers/halts with visible state, no data loss; **Degraded** = continues but silently loses signals or needs manual ops; **Unsafe** = corruption/security. **No Unsafe scenarios were identified in the orchestration layer.**

| # | Scenario | Classification | Evidence |
|---|---|---|---|
| 1 | Dev/QA LLM failure mid-subtask | Graceful (retry → blocked → halt ladder) | manager.py:641-653, 1707-1752 |
| 2 | Process crash mid-subtask | Graceful (orphan recovery: resume or fail+escalate) | failure_ladder.py:282-422 |
| 3 | Process crash mid-planning graph | Degraded (task stuck `planning`, restart 409, no graph auto-resume) | tasks.py:471-481; no resume caller |
| 4 | Generic exception in launch_manager | Degraded (stuck `coding`, manual PATCH only) | ORCH-04-101 |
| 5 | Slot exhaustion under load | Graceful (bounded wait → blocked result) | concurrency.py:121-136; manager.py:521-552, 632-637 |
| 6 | Duplicate run/restart (double-click) | Graceful (CAS → 409) | tasks.py:489-520 |
| 7 | Duplicate plan approval (two endpoints) | Degraded (bounded by final CAS; stale inbox row) | ORCH-04-107 |
| 8 | Epic fan-out wave DB contention | Degraded (silent event/status loss) | ORCH-04-105 |
| 9 | Worktree dir/branch already exists | Graceful (registered check → move-aside → recreate) | worktree.py:31-58, 106-121 |
| 10 | Leader election enabled (default) | Degraded-silent (4/20 loops permanently dead) | ORCH-04-102 |
| 11 | Hard exception in epic manager | Degraded (epic stranded, invisible to review) | ORCH-04-108 |
| 12 | Cancel mid-coding | Graceful (abort flag + terminal status; resume refused) | activity.py:38-40, 205-254 |

## 9. Notes / Limits of This Audit

- No LLM calls were executed for this audit; all verification is static against HEAD. The full backend pytest suite was running concurrently (baseline job started 11:03, ~94 % at 38 min, failure clusters observed at 0-8 % and ~80 %); final failure attribution belongs to audit 08/17 with the suite log (`/tmp/qoder_full_suite.log`).
- Working tree drift: a concurrent process edited `backend/app/api/{auth,epics,fleet_dashboard}.py` during the audit; `epics.py` and `fleet_dashboard.py` route-order changes were visible and do not alter any cited line semantics (citations re-checked). `auth.py` was touched mid-run — flagged to audit 05.
- Orchestration-layer tests exist and were consulted as contract evidence (`test_approvals_api.py`, `test_status_transitions.py` family, `test_subtask_fanout.py`, `test_audit04_orchestration_fixes.py`); pass/fail results come from the running suite, not from this audit.

## 10. Score & Verdict

**Orchestration Layer Production-Readiness: 74 / 100** — Verdict: **READY** (with 2 High findings requiring remediation before production).

- Core lifecycle is real and race-guarded (atomic transitions, CAS approvals, bounded slots, orphan recovery, worktree hygiene) and three task-facing entry points are at parity.
- Deductions: two Highs (unstuck-status gap ORCH-04-101; 4-of-20 dead background loops by default ORCH-04-102), three Mediums (epic-path lifecycle gaps ORCH-04-103/104, fan-out session race ORCH-04-105), four Lows (docs/dual-endpoint/stranded-epic/dead filter).

**Prioritized fix list:**
1. ORCH-04-101 (High, S) — add `blocked` transition to launch_manager's exception handler.
2. ORCH-04-102 (High, S) — size the leader-election engine from the real loop list (or `max_overflow ≥ 4`).
3. ORCH-04-103 (Medium, M) — decide the epic plan-gate; complete the child DevTask; persist subtasks.
4. ORCH-04-105 (Medium, M) — serialize per-task DB writes under fan-out.
5. ORCH-04-104 (Medium, M) — epic close-out (worktree/PR/child-task terminal state).
6. ORCH-04-106/107/108/109 (Low, S each) — docs alignment, single approval authority, epic stranded-status handler, batch-review filter.
