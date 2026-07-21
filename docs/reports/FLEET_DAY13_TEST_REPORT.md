# Fleet Day 13 Test Report — Human Approval UI
Date: 2026-07-21

## What was built

Per `docs/DAY13_PLAN.md`, grounded in a live empirical test against the installed LangGraph 1.2.7
package (not just reading `repos/langgraph`'s source — CLAUDE.md's zero-hallucination rule) before
any design.

### Research: real LangGraph interrupt()/Command semantics, verified not assumed

```python
compiled = g.compile(checkpointer=InMemorySaver())
r1 = compiled.invoke({"x": 0}, config=cfg)          # -> {..., "__interrupt__": [Interrupt(...)]}
snap = compiled.get_state(cfg)                       # snap.interrupts is the live pending signal
r2 = compiled.invoke(Command(resume={"approved": True}), config=cfg)
```

Confirmed: `invoke()`'s return carries `"__interrupt__"` when paused; `get_state().interrupts` is
queryable any time after. **Critical finding**: the entire node body re-runs from the top on
resume — a counter incremented before `interrupt()` went from 1 to 2 across the pause/resume
cycle in a minimal test graph. This means any code recording "a pause happened" must live in the
*calling* code (after `invoke()` confirms the pause), never inside the paused node — writing there
would duplicate on every resume.

Also confirmed a real architectural constraint before committing to a design: adding a checkpointer
to `base_graph.py`'s `g.compile()` requires every `graph.invoke()` call site to pass
`config={"configurable": {"thread_id": ...}}` (verified: omitting it raises `ValueError`), and
resuming from a cold HTTP request would require reconstructing `tool_handlers` (external Python
closures, e.g. `backend_dev.py`'s handlers bound to a `worktree_path`) from serialized primitives —
solvable, but separate, larger work than this day's scope. `pipeline/graph.py`'s nodes rebuild
everything from primitive `state` fields instead, so its existing checkpointer + `interrupt()`
(already proven correct in Day 12's smoke test) is the one real, resumable-from-cold gate today.

### Scope decision

Built a **generic approvals system** — tracking table, audit log integration, list/get/approve/
reject API, frontend page — as infrastructure any future `interrupt()` call site registers into,
wired to the one real, working call site (`pipeline/graph.py`'s `human_review_node`) rather than
retrofitting `base_graph.py`'s 72-agent-shared hot path or reusing the plan's literal git-push
example (Day 14's job — `git_push_tool.py` doesn't exist yet). The existing `/pipeline/approve`/
`/pipeline/reject` endpoints (Day 0-era, tested in Day 12) are untouched; the new
`/api/approvals/*` endpoints call the exact same `resume_planning_pipeline()` internally.

## What was built

- **`pending_approvals` table** (migration 015) + **`app/fleet/approval_gate.py`** — pure
  tracking/indexing, no `interrupt()`-calling logic (that already exists correctly). Both sync
  (`record_pending`, `list_pending`, `get_pending`, `record_decision`) and async (`arecord_pending`,
  `alist_pending`, `aget_pending`, `arecord_decision`) facades — needed both, see bug #1 below.
- **Wiring**: `launch_planning_pipeline()` now calls `arecord_pending()` at the exact point it
  already detects "graph is waiting at human_review"; `resume_planning_pipeline()` calls
  `arecord_decision()` and `audit_log.record_approval()` (already existed — reused, not duplicated).
- **`backend/app/api/approvals.py`**: `GET /pending`, `GET /{thread_id}`, `POST /{thread_id}/approve`,
  `POST /{thread_id}/reject` — 404 for unknown thread, 409 if already decided, mirroring Day 9's
  `enhancement_requests` approve/reject convention. `approve`/`reject` dispatch to
  `resume_planning_pipeline()` via `BackgroundTasks`.
- **`apps/web/app/approvals/page.tsx`** + NavBar link with a live pending-count badge — same shape
  as Day 9's `/fleet` page (5s polling instead of SSE, since no new stream endpoint was built).

## Two real bugs found and fixed

### 1. Sync `asyncio.run()` facades called from already-async code — silent failure

First wiring attempt called the sync `record_pending`/`record_decision` (internally
`asyncio.run(...)`) directly from `launch_planning_pipeline`/`resume_planning_pipeline` — both
already `async def`, running inside FastAPI's live event loop via `BackgroundTasks`.
`asyncio.run()` raises when called from within a running loop; the calls failed on every single
pipeline run, silently swallowed by a broad `except Exception: logger.warning(...)`. First
symptom: a `RuntimeWarning: coroutine '_record_pending' was never awaited` in the test output —
investigated rather than ignored. Fixed by adding proper `async def` facades for async call sites.
This is a new *variant* of the asyncio-loop hazard already flagged in project memory (prior
occurrences were about reusing one engine across multiple `asyncio.run()` calls in sync code) —
here the shape was "calling a sync `asyncio.run()` wrapper from code that's already inside a
running loop," a related but distinct failure mode worth remembering separately.

### 2. Pre-existing Day-0 bug: rejecting a plan has always raised `TransitionError`

`resume_planning_pipeline()`'s reject path calls `transition_task(db, task_id, "rejected")`, but
`DevTask.status` is still `"planning"` at that point — the human_review pause is tracked in the
separate `PipelineState.stage` column, not `DevTask.status`. `VALID_TRANSITIONS["planning"]` never
included `"rejected"` (only `"ready_for_review"` did). This means **rejecting a plan during the
approval pause has been broken in real production use since Day 0** — not a regression from this
session's changes, and not caught by Day 12 either (which only tested the approve path). Found by
`test_reject_via_generic_endpoint_marks_task_rejected`, the first test ever written against this
path. Fixed by adding `"planning"` → `"rejected"` to `VALID_TRANSITIONS`.

## Frontend verification

- `npm run lint` — 0 errors (3 pre-existing warnings in unrelated files: `epics/page.tsx`,
  `review/page.tsx`).
- `npm run build` — succeeds; `/approvals` route compiles at 1.78 kB First Load JS.
- `tsc --noEmit` — clean.
- Started real backend (`uvicorn app.main:app`) + frontend (`next dev`) and verified against them
  directly: found a stale `uvicorn` process from earlier in the session still squatting on port
  8000 serving pre-Day-13 code (my new server failed to bind and silently exited — caught by
  checking the log, not assumed to have worked); killed it, restarted cleanly, confirmed
  `GET /api/approvals/pending` returns real JSON from the new router, and the frontend's Next.js
  proxy correctly reaches it (`{"approvals":[]}`) with correct SSR output (title + loading state).

## Test Results

```
pytest tests/ -q
→ 2583 passed, 0 failed, 55 skipped, 17 deselected, 10 warnings in 76.40s

mypy app/ --strict
→ 32 errors, all pre-existing (identical to the Day 12 baseline), 0 new
```

Verified 0 residual `pending_approvals` rows after the full suite run (14 new backend tests:
7 `test_approval_gate.py` + 7 `test_approvals_api.py`, all with `try/finally` cleanup).

## Verdict
✅ GREEN FLAG — DAY 13 COMPLETE. Ready for Day 14 (Git Push Workflow — branch/commit/PR creation,
registers into this same approvals system for the push-approval gate).
