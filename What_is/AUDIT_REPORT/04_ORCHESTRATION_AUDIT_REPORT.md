# Audit 04: Master Orchestration Audit

**Spec:** `files/Audit/04_MASTER_ORCHESTRATION_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_04_ORCHESTRATION.json`

## Result

🟢 **GREEN: every orchestration defect found was reproduced, fixed and regression-tested. No open Critical or High issues.**

**Orchestration score: 88 / 100** (July run: 58, "NOT READY"). All 12 of July's fixes still hold except two that were only half-done, and those are now finished (ORCH-04-004, ORCH-04-006). Seven new defects were found and fixed. Every race condition was proven with a test that **fails on the old code** and passes on the new code.

## 1. Two-entry-point parity (headline table)

"Simple" mode = `launch_planner` → human approves → `launch_coder`.
"Full" mode = `launch_planning_pipeline` → `interrupt()` at human review → `launch_manager` → `run_manager`.

| Feature | Simple mode | Full mode | Evidence |
|---|---|---|---|
| Blank-repo bootstrap | ✅ | ✅ | `api/agents.py` (`launch_coder` bootstrap block), `api/agents.py:130-160` |
| Repo resolution (`task.repo_id` → worktree) | ✅ | ✅ | `resolve_task_repo_path`, `create_worktree(task_id, effective_repo)` |
| Task image forwarding | ✅ **fixed** (was ❌) | ✅ | ORCH-04-002; `test_audit04_simple_mode_parity.py` |
| Credential injection (`extra_env`; GitHub/Anthropic keys stripped) | ✅ | ✅ | `launch_coder` / `launch_manager` vault blocks |
| Commit after write (so Reviewer sees a real diff) | ✅ | ✅ | July ORCH-04-001, still in place |
| Git push / PR approval flow | ✅ **fixed** (was ❌: push impossible) | ✅ | ORCH-04-003 |
| Activity stream `task_id` threading | ✅ | ✅ | audit 02 scorecard (runtime capture) |
| Exception → terminal-ish `blocked` | ✅ | ✅ | `launch_coder` except path; `launch_manager` else/except |

## 2. State machine

Extracted from `app/db/models.py` `VALID_TRANSITIONS` (runtime, not from docs):

```
pending ─► planning ─► ready_for_review ─► coding ─► testing ─► ready_for_review ─► completed
   │          │  └─► rejected ─► planning        │                     │
   └─► blocked ◄──────────────── (any in-progress state) ─────────────┘
   blocked ─► planning | coding | failed | cancelled
   any non-terminal ─► failed | cancelled          terminal: completed, failed, cancelled
```

- Dead-end states: only the three intended terminals.
- Every status the code transitions to (`blocked, cancelled, coding, completed, planning, ready_for_review, rejected, testing`, plus `failed` via the failure ladder) exists and has a legal source. **0 missing transitions.**
- `pr_status` (`none|pending|pushed|failed`): `pending` was documented but never set. Fixed; it is now set when the push approval is recorded.

## 3. Human-in-the-loop correctness

| Check | Result |
|---|---|
| `interrupt()` node has no state mutation before the interrupt (whole node re-runs on resume) | ✅ July finding still holds; July tests pass |
| Every approval-like pause goes through `approval_gate` (plan review, git push, clarification) | ✅ |
| Unknown thread → 404, already decided → 409 | ✅ `api/approvals.py:223-257` |
| **Two simultaneous approve/reject clicks** | ❌ → ✅ **fixed (ORCH-04-006)**. Old code: both won in **15 of 15** concurrent trials (double pipeline resume or double git push). New: exactly one winner in 15 of 15. |

## 4. Failure-ladder reachability

| Rung | Real call site | Reachable from a real failure? |
|---|---|---|
| Retry (with error fed back) | `run_manager` subtask loop, bounded by `manager_max_subtask_retries` | ✅ |
| Escalate | `manager.py:~1743`, `failure_ladder.reconcile_orphaned_runs` | ✅ |
| Human review | `manager.py:~1748` (subtask exhausted), `base_graph.py:4115` (stall) | ✅ **after ARCH-01-001** (was crashing silently from the manager) |
| Abort | `manager.py:~1727` (epic halted) | ✅ **after ARCH-01-001** |
| Checkpoint / resume | `manager` epic_halted snapshot; `reconcile_orphaned_runs` → `_try_resume_orphan` | ✅ |

## 5. Concurrency and conflict safety

| Check | Result |
|---|---|
| `epic_slot` / `agent_run_slot` / `subtask_slot` acquired on real paths | ✅ 4 `async with` sites (`manager.py`) |
| Conflict guard + file locks before concurrent epics write the same file | ✅ `manager.py:2254`, `file_locks.reserve_epic_files` (all-or-nothing) |
| Worktrees namespaced by epic + task | ✅ `worktree_path()` |
| Restart double-click | ❌ → ✅ **fixed (ORCH-04-005)**: two concurrent restarts → exactly `[200, 409]`, one pipeline launch (5 of 5 runs) |

## 6. Idempotency

- The dev→QA→review retry loop is bounded and state-checked per attempt; no double dispatch was found.
- `POST /api/tasks/{id}/push` supports `Idempotency-Key` (July fix, still in place).
- Event ordering: `publish_event` dispatches handlers sequentially per call (`event_bus/bus.py`).

## 6B. Orchestration trace: "add a health check endpoint" (full mode, from code)

1. `POST /api/tasks` creates the DevTask (`pending`).
2. `POST /api/tasks/{id}/run` (mode=full) → `planning` → `dispatch_job(launch_planning_pipeline)`.
3. The pipeline checks for a blank repo (bootstrap if needed) and pre-fetches memory context and task images (`pipeline/graph.py:245-285`).
4. `pm_node` → `architect_node` → `decomposer_node` (Opus/Sonnet via the router; memory placed in each prompt), then `human_review` calls `interrupt()` and registers a `plan_review` approval; the task goes to `ready_for_review`.
5. `POST /api/approvals/task-{id}/approve` (compare-and-set) → `resume_planning_pipeline` → `launch_manager`.
6. `run_manager`: topological waves → `fleet_manager.select("backend_development")` → `backend_dev` in the task worktree (agent-run slot held) → git add/commit → `run_qa` → pass: `run_reviewer`, fail: retry with the QA error. Per-subtask gates (security / architecture / dependency / regression / docstring) run by default.
7. All subtasks complete → diff saved as an artifact → `testing` → `ready_for_review` → git-push approval recorded (`pr_status=pending`).
8. The task outcome is embedded into memory (a no-op without `VOYAGE_API_KEY`, see audit 03).
9. Events fire at each step (activity stream by `task_id`; fleet events now **persisted**, ORCH-04-004).

Every step was checked against code in phases 1–6. Before this audit, the trace broke at step 9 (fleet events were never stored) and, on the failure branch, at the ladder (ARCH-01-001). Both are fixed.

## 6C. Failure scenarios (static reasoning from code, plus reproductions where marked)

| Scenario | What actually happens | Class |
|---|---|---|
| Anthropic down / rate-limited | SDK retries (`llm_call_max_retries`) → shared circuit breaker → agent error → subtask retry → `blocked` + alert. **No automatic provider failover** (human decision, audit 13). | Graceful |
| Groq down (`USE_GROQ=true` only) | Same path with Groq's own retry setting | Graceful |
| Postgres down mid-run | Status writes fail inside the background job → exception logged; `AgentRun` heartbeat stops → orphan sweep reconciles within `agent_run_orphan_threshold_seconds` | Degraded but recoverable |
| Redis down | Default `QUEUE_BACKEND=asyncio` doesn't need Redis; Redis Streams mirroring is best-effort (`to_thread`, errors swallowed) | Graceful |
| Tool hangs (e.g. `bash` running a test suite) | Enforced subprocess / sandbox timeouts (`run_sandboxed(timeout=120)`, per-tool timeouts) | Graceful |
| Retry exhaustion | Subtask `blocked` → human review event → task `blocked` + `send_task_alert` | Graceful |
| Partial epic failure | `≥ MANAGER_MAX_EPIC_FAILURES` → epic `halted` with a checkpoint; otherwise `blocked` with per-subtask statuses persisted (July ORCH-04-011 fix) | Graceful |
| **Leftover branch or worktree** (after a reject, or a reboot wiping `/tmp`) | **Reproduced:** `fatal: a branch named 'agent/task-N' already exists` → task always `blocked`. **Fixed (ORCH-04-007).** | Was Unsafe → Graceful |
| Checkpointer connection drop | `AsyncPostgresSaver` call raises → pipeline job fails → task `blocked`; re-run possible | Degraded but recoverable |

## 7. Findings (all fixed unless stated)

| ID | Sev | Finding | Fix + proof |
|---|---|---|---|
| **ORCH-04-001** | **High** | `POST /api/goals` ("Create goal") **always failed**: async `run_executive` called the sync graph on the event loop; with the Postgres checkpointer initialised at startup (`main.py:1518`) LangGraph raised *"Synchronous calls to AsyncPostgresSaver are only allowed from a different thread"* → HTTP 500. Without the checkpointer, it would block every request for the whole LLM run. The existing tests mocked the entire graph. | `await asyncio.to_thread(run_agent_graph, …)`. Reproduction with real checkpointer + graph: error → `goal_id=True`, event loop kept ticking. |
| **ORCH-04-002** | Medium | Simple mode silently dropped task images (planner/coder had no `images` parameter). | `images` threaded `launch_*` → `run_planner`/`run_coder` → graph. Test. |
| **ORCH-04-003** | Medium | Simple mode never recorded the push approval, which also meant `branch_name` was never set, so `POST /push` returned 400 for **every** simple-mode task: no PR possible. | `_record_git_push_approval` called from `launch_coder`; `pr_status=pending`. Test (real git + DB). |
| **ORCH-04-004** | **High** | *(July JUL-ARCH-01-001, only half fixed)* Fleet OS events were forwarded to the bus **without a DB session** → never stored (live DB: **0** `agent.health_updated` rows). `reseed_health_from_events` found nothing, so **an admin's agent disable/retire was silently undone by any restart.** | `publish_event_persisted()` gives the forward its own session. End-to-end test: disable via API → stored → simulated restart → still disabled. Fails on the old code. |
| **ORCH-04-005** | Medium | *(July ORCH-04-004, incomplete)* `/restart` check-then-reset race: a double click launched **two** pipelines, or returned 500. | Compare-and-set reset + `TransitionError` → 409. Concurrent test `[200, 409]`, 5/5 runs. |
| **ORCH-04-006** | **High** | *(July ORCH-04-007, incomplete)* Approval decisions updated by id only: two concurrent clicks **both** won (15/15 trials) → double resume or double push. | `UPDATE … WHERE status='pending' RETURNING`. Concurrency test fails on old code, passes on new. |
| **ORCH-04-007** | **High** | A leftover `agent/task-N` branch without its directory (after reject, or after a reboot wiping `/tmp`) made `create_worktree` fail → re-running a rejected task, or restarting any blocked task after a reboot, always ended `blocked`. | `git worktree prune` + move the stale branch to `…-stale-<timestamp>` (not deleted: no data loss). Tests: reject→re-run, reboot→restart, old commits preserved. |
| **PERF-04-008** | **High** (perf) | Every agent run re-indexed the whole target repo with no cache and **no `.gitignore` support**: 14,631 files / **~75 s per agent run** in this workspace (cloned repos under `repos/`). Found while profiling ORCH-04-001. | Scanner lists files via `git ls-files --cached --others --exclude-standard` (walk fallback for non-git dirs): **75 s → 2.8 s**, 1,228 files, all app code still indexed. 4 tests. |
| ORCH-04-009 | Low | `pipeline/dispatcher.py` (legacy, test-only) still calls sync agents directly from `async def dispatch_subtask`. It has no production caller. | Recorded; reported in audit 11 dead-code section. |

## 8. July (2026-07-27) findings: regression check

| July ID | Status today |
|---|---|
| ORCH-04-001 simple-mode commit | ✅ still fixed |
| ORCH-04-002 `completed` unreachable | ✅ still fixed (push success → `completed`) |
| ORCH-04-004 restart bypass | ⚠️ was half fixed → **completed now** (ORCH-04-005) |
| ORCH-04-007 approval race | ⚠️ was half fixed → **completed now** (ORCH-04-006) |
| ORCH-04-008 ladder rungs unreachable | ✅ fixed (and ARCH-01-001 made abort/human-review actually work) |
| ORCH-04-009 semaphores unused | ✅ still fixed |
| ORCH-04-010 conflict guard unused | ✅ still fixed |
| ORCH-04-011 Subtask.status never updated | ✅ still fixed |
| ORCH-04-012 `remove_worktree` no callers | ✅ still fixed (3 callers) |
| ORCH-04-014 discarded `create_task` refs | ✅ `_spawn_tracked` |
| ORCH-04-015 retry multiplication | ✅ `manager_max_subtask_retries` separate setting |
| ORCH-04-016 queue adapter unused | ✅ `dispatch_job` used by tasks API |

## Verdict

**READY.** 0 open Critical / High in orchestration. Targeted regression: 459/459 across the 41 related test files. The full regression result is recorded in audit 08.
