# Fleet Day 18 Test Report — Real-Time Streaming to Frontend
Date: 2026-07-22

## What was built

Per `docs/DAY18_PLAN.md`, grounded in REPO-FIRST research before any design (CLAUDE.md rule).

### Research

`repos/opencode/packages/server/src/handlers/event.ts` — confirmed the plan's own constants
(`subscriberCapacity = 256`, a 15-second heartbeat, `Cache-Control: no-cache, no-transform` /
`X-Accel-Buffering: no` headers) are real, load-bearing values from a real project, not guesses.

### The central finding — the infrastructure already existed

The plan's own note said "Chat agent already has SSE streaming. This day wires the same SSE to the
pipeline agents." Investigated before designing anything, per the standing project lesson (a
feature wired into only one of several real entry points is a real gap, not a false negative):

- `app/services/activity_stream.py` (`TaskStream`/`ActivityStreamRegistry`/`push_*` helpers) and
  `app/api/activity.py`'s `GET /api/tasks/{id}/stream` — **already the exact endpoint URL the plan
  asks for**, fully built.
- `app/agents/base_graph.py`'s `run_agent_graph()` (the shared core for all 72+ agents) **already
  calls every push_* function**, gated behind `if task_id:` — confirmed by grep.
- `apps/web/app/stream/[taskId]/page.tsx` — a **complete, already-built activity feed UI**
  (EventSource subscription, thinking/tool_call/tool_result/file_edit/terminal/token_usage/
  stopped/done/error rendering, auto-scroll, Stop/Resume controls, dark mode).

**The real gap**: `task_id` was never passed to `run_agent_graph()` from any of the 8 real agent
runners — `pm_node`, `architect_node`, `decomposer_node` (`pipeline/graph.py`) and
`run_backend_dev`, `run_frontend_dev`, `run_coder`, `run_qa`, `run_reviewer` (the dev-agent
runners) — confirmed by grep across every file, not assumed. This meant the fully-built stream and
fully-built frontend feed had never received a single real event for an actual task pipeline run.

## What was built

- Threaded `task_id=str(...)` into all 8 `run_agent_graph()` calls (each function already had the
  real id in scope — `state["task_id"]` in the three pipeline nodes, an existing `task_id: int`
  parameter in the five dev-agent runners).
- `activity_stream.py` gained two functions: `push_agent_switch()` (documented in the module's own
  docstring since it was written — "agent_switch — role_name changed mid-pipeline" — but never
  implemented until now) and `push_approval_required()` (entirely new — the plan's explicit
  "approval gate shows as interactive card in the stream" success criterion had nothing pushing
  it).
- `push_agent_switch` called at the top of `pm_node`/`architect_node`/`decomposer_node` and before
  each `backend_dev`/`frontend_dev`/`qa`/`reviewer` dispatch in `manager.py`'s subtask loop.
- `push_approval_required` called right after Day 13/14's two real `arecord_pending()` call sites
  (`launch_planning_pipeline`'s plan_review, `_record_git_push_approval`'s git_push) — the same
  approvals system, not a parallel mechanism.
- `activity.py`'s heartbeat interval: `30.0` → `15.0`, matching both the plan's stated interval and
  OpenCode's real constant — the previous value meant the plan's own "heartbeat tested with 16s
  wait" success criterion could never observe one in time.
- Frontend: `apps/web/app/stream/[taskId]/page.tsx` gained rendering for the two new event types
  (a node-transition divider for `agent_switch`, an interactive "Review in Approvals →" card for
  `approval_required`). The task detail page gained a "View live activity →" link to the existing
  feed — reusing the already-built, already-tested ~400-line component rather than duplicating it
  into a new inline panel (the plan's own pseudocode path, `apps/web/src/components/TaskStream.tsx`,
  doesn't even match this project's real `apps/web/components/` convention).

## A real asyncio shared-engine hazard hit while testing, fixed per the documented playbook

The first version of the `approval_required` wiring test drove `launch_planning_pipeline()`
directly via a bare `asyncio.run()` from sync test code. Passed in isolation, failed only when run
as part of the full suite — the exact signature of the project's documented "production code
correctly using the shared `get_session_factory()` singleton fails under a bare `asyncio.run()`
from sync test code" hazard (variant #3, first found in Day 13/14). Fixed per the established
playbook: rewrote the test to drive the same code path through a real `TestClient`
(`POST /api/tasks/{id}/run`) instead — one continuous event loop for the whole test.

## Testing

- `test_activity_stream.py` extended: `push_agent_switch`/`push_approval_required` unit tests
  (matching the file's existing `TestConvenienceHelpers` convention), a new `TestHeartbeat` class
  (a fast `TaskStream.subscribe(timeout=0.05)` test proving the ping mechanism itself works without
  a real 15s wait, plus a direct assertion — via `inspect.getsource` — that the real production
  endpoint uses `timeout=15.0`, not a re-implementation of the check).
- New `test_day18_streaming_wiring.py` (11 tests): each of the 8 agent runners verified to actually
  pass `task_id` to `run_agent_graph()` (mocked at each module's home site, matching the
  established "patch the home module" convention); `pm_node` verified to call `push_agent_switch`;
  `run_manager()`'s subtask loop verified to announce `backend_dev`/`qa`/`reviewer` transitions
  with the correct task id; the real `plan_review` approval-recording path verified to produce a
  real `approval_required` event in a real `TaskStream`, driven through `TestClient`.

## Frontend verification

`tsc --noEmit`, `eslint`, `npm run build` all clean.

## Real-caller verification

```
push_agent_switch()      → pm.py, architect.py, decomposer.py, manager.py (x3: backend/frontend, qa, reviewer)
push_approval_required() → api/agents.py (x2: plan_review, git_push)
task_id= (all 8 sites)   → pm.py, architect.py, decomposer.py, backend_dev.py, frontend_dev.py,
                            coder.py, qa.py, reviewer.py
```
5th clean day in a row — zero orphaned modules.

## Test Results

```
pytest tests/ -q
→ 2699 passed, 0 failed, 55 skipped, 17 deselected, 24 warnings in 90.48s (11 new tests + 3 extended)

mypy app/ --strict
→ 0 errors

Frontend: tsc --noEmit (clean), eslint (clean), npm run build (succeeds)
```

## Verdict
✅ GREEN FLAG — DAY 18 COMPLETE. Ready for Day 19 (Cloud Deployment).
