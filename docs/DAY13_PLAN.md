# Day 13 Implementation Plan — Human Approval UI
Researched and grounded 2026-07-21 (REPO-FIRST + real langgraph API verification before design).

Source: `docs/FLEET_ENHANCEMENT_PLAN.md` lines 984-1025.

## Research: real, installed LangGraph API (v1.2.7), verified empirically, not assumed

Ran a minimal live test against the installed package (not just read `repos/langgraph`'s source):

```python
g.compile(checkpointer=InMemorySaver())
r1 = compiled.invoke({"x": 0}, config={"configurable": {"thread_id": "t1"}})
# r1 == {..., "__interrupt__": [Interrupt(value={...}, id="...")]}
snap = compiled.get_state(cfg)   # snap.interrupts is the live "is this thread paused" signal
r2 = compiled.invoke(Command(resume={"approved": True}), config=cfg)
```

**Critical finding, confirms a design constraint**: on resume, the **entire node body re-runs from
the top** — a counter incremented before `interrupt()` in the test node went from 1 to 2 across
the pause/resume cycle. Any code before an `interrupt()` call must be safe to re-execute, or must
not exist (call `interrupt()` as the first thing in the node). This also means any DB write meant
to record "a pause just happened" must NOT live inside the node body before `interrupt()` — it must
happen in the calling code, exactly once, after `invoke()` returns and `"__interrupt__"` is present
in the result (or after `get_state().interrupts` is non-empty) — never inside the paused node itself.

**A second constraint, decisive for scope**: `base_graph.py`'s `run_agent_graph()` builds a fresh
graph per call and takes `tool_handlers` as an argument — Python closures, often bound to a
specific `worktree_path`/`repo_path` (e.g. `backend_dev.py`'s handlers). Resuming from a cold HTTP
request (a `POST /api/approvals/{id}/approve` call, potentially on a different request/process)
would require reconstructing those exact closures from serialized primitives — a real, solvable
problem, but a *different and separate* piece of work from the approvals UI itself, and adopting it
per-agent (backend_dev, qa, reviewer, ...) is a rollout decision, not something this single day can
respons­ibly force onto the 72-agent-shared hot path. **`app/pipeline/graph.py` does not have this
problem** — its nodes (`pm_node`/`architect_node`/`decomposer_node`/`human_review_node`) rebuild
their own handlers from primitive `state` fields (e.g. `state["repo_path"]`, a plain string) on
every invocation, so its existing checkpointer + `interrupt()`/`Command(resume=...)` machinery
(already built, already proven correct in Day 12's smoke test) is the one real, resumable-from-cold
approval gate that exists in this codebase today.

## Scope decision

Day 13 builds a **generic approvals system** (tracking table, audit log integration, list/get/
approve/reject API, frontend page) as infrastructure any future interrupt() call site can register
into — and wires it to the one real, already-working interrupt() call site
(`pipeline/graph.py`'s `human_review_node`, exercised via `launch_planning_pipeline`/
`resume_planning_pipeline`) as its first real consumer, rather than reusing the plan's literal
`git push` example (that's explicitly Day 14's job, `git_push_tool.py` doesn't exist yet) or
retrofitting `base_graph.py`'s hot path (a separate, larger, riskier piece of work). This is not a
narrower scope than asked — it's the same infrastructure the plan describes, demonstrated against
a real flow instead of a synthetic one, so Day 14's git-push approval gate can register into the
exact same system without new plumbing.

The existing `POST /{id}/pipeline/approve`/`/pipeline/reject` endpoints (Day 0-era, tested in
Day 12) are untouched — they remain the plan-approval-specific path. The new
`/api/approvals/*` endpoints are the generic, cross-flow layer: `POST /api/approvals/{thread_id}/approve`
internally calls the same `resume_planning_pipeline()` that `/pipeline/approve` already calls (reused,
not duplicated), so both paths produce identical, already-proven resume behavior.

## New: `pending_approvals` table (migration 015)

`id`, `thread_id` (str, indexed — `f"task-{task_id}"`, matching `pipeline/graph.py`'s existing
LangGraph thread_id convention), `task_id` (int, nullable, indexed), `agent_name`, `action`
(str — e.g. `"plan_review"`), `details` (JSONB — display payload: subtask count, risk level, brief
summary), `status` (`pending|approved|rejected`, indexed), `created_at`, `decided_at`, `decided_by`.

## New: `app/fleet/approval_gate.py`

Pure tracking/indexing helpers — no `interrupt()`-calling logic here, since the actual pause
mechanics already exist and work correctly in `pipeline/graph.py`; this module is the generic layer
sitting above it:
- `record_pending(thread_id, action, details, agent_name="", task_id=None) -> PendingApprovalRecord`
  — called once, from `launch_planning_pipeline()`, exactly at the point it already detects
  "graph is waiting at human_review" (confirmed by reading that function in Day 12 — it already has
  this exact detection branch, just didn't index it generically before)
- `list_pending() -> list[PendingApprovalRecord]`
- `get_pending(thread_id) -> PendingApprovalRecord | None`
- `record_decision(thread_id, approved, decided_by="user") -> PendingApprovalRecord | None`

## New: `backend/app/api/approvals.py`

- `GET /api/approvals/pending` — lists `pending_approvals` rows with `status="pending"`
- `GET /api/approvals/{thread_id}` — one row + its `details` payload, 404 if not found
- `POST /api/approvals/{thread_id}/approve` — resolves `task_id` from the row, calls the existing
  `resume_planning_pipeline(task_id, approved=True)` (via `BackgroundTasks`, matching the existing
  pattern), `approval_gate.record_decision(...)`, `audit_log.record_approval(...)` (already has
  exactly this method — reused, not duplicated)
- `POST /api/approvals/{thread_id}/reject` — same with `approved=False`
- 404 for unknown `thread_id`, 409 if already decided (mirrors Day 9's `enhancement_requests`
  approve/reject 404/409 pattern)

## Frontend: `apps/web/app/approvals/page.tsx`

Generic approvals list (action type, agent, risk/details preview, approve/reject buttons) +
NavBar link with a live pending-count badge — same shape as Day 9's `/fleet` page, reused pattern.

## Tests

- `tests/test_approval_gate.py` — `record_pending`/`list_pending`/`get_pending`/`record_decision`
  against a real Postgres round-trip, `try/finally` cleanup, matching the established pattern.
- `tests/test_approvals_api.py` — drives a real pipeline run through the FastAPI `TestClient` with
  mocked LLM (same pattern as Day 12's smoke test) into `awaiting_approval`, then exercises the NEW
  `/api/approvals/*` endpoints (not the old `/pipeline/approve`) end-to-end, proving they produce
  the same real resume behavior: task transitions to `ready_for_review`, `launch_manager` gets
  scheduled, the `pending_approvals` row flips to `approved`, and the audit log has the decision.

## Build order
1. Migration 015 + `PendingApproval` model.
2. `approval_gate.py` + unit tests.
3. Wire `record_pending()`/`record_decision()` into `launch_planning_pipeline`/`resume_planning_pipeline`.
4. `backend/app/api/approvals.py` + tests (reusing Day 12's mocked-pipeline-through-TestClient pattern).
5. Frontend page + NavBar link.
6. Full suite + mypy, update `PROJECT.md`/Control Center, write
   `docs/reports/FLEET_DAY13_TEST_REPORT.md`, commit.
