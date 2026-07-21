# Fleet Day 12 Test Report — E2E Smoke Test, Failure Recovery Ladder, Event Compliance, Hierarchy Chain
Date: 2026-07-21

## What was built

Per `docs/DAY12_PLAN.md`, written after a codebase-first + REPO-FIRST research pass (checked
`repos/swe-agent` for the plan's own cited pattern source, and read `app/pipeline/graph.py`,
`app/agents/manager.py`, `app/api/agents.py`, `app/fleet/fleet_checkpoint.py`,
`app/fleet/agent_registry.py`, `app/db/models.py`'s `VALID_TRANSITIONS` in full before designing
anything).

### Key finding: two separate LangGraph graphs, and what's actually wired vs. not

`app/pipeline/graph.py` (epic-level `pm→architect→decomposer→human_review`, real
`AsyncPostgresSaver` checkpointer + `interrupt_before`) and `app/agents/base_graph.py`
(per-agent `run_agent_graph()`, no checkpointer, used by all 72+ agents) are distinct. The real
live flow — `POST /tasks` → `POST /{id}/run` → pipeline pauses at `human_review` →
`POST /{id}/pipeline/approve` → `resume_pipeline` → `asyncio.create_task(launch_manager(...))` →
`run_manager()` → direct `run_qa`/`run_reviewer` calls — is **fully wired and reachable today**,
but **had zero test coverage anywhere in the codebase** (confirmed by grep for
`launch_manager`/`launch_planning_pipeline`/`resume_planning_pipeline` across `tests/`). Separately,
`fleet_manager.select()`, `capability_registry` lookups, and `agent_bus`
(`fleet_events.publish`) all exist, are unit-tested in isolation, and every agent self-registers
into them via `_register()` — but **nothing in the live path ever called them**. Decision, to keep
blast radius small on a well-tested, heavily-used core path: add small, additive instrumentation
into `run_manager()` rather than restructure its working dispatch logic.

## Part 1 — Smoke Test (`tests/test_day12_smoke_test.py`, 4 tests)

Drove a real task through the FastAPI `TestClient` (no `ANTHROPIC_API_KEY` in this environment, so
LLM calls are mocked with a generic "return a tool_use block for whatever `submit_*` tool is in
this call's tool list" side effect — works uniformly across the main `call_llm` turn and the
planner/reflection calls, since those two gracefully degrade to safe defaults on non-JSON text,
verified by reading their try/except blocks first):

1. `POST /tasks` → `POST /{id}/run` → pipeline completes PM→Architect→Decomposer and pauses —
   verified via the real `/subtasks` endpoint returning real decomposer-produced subtasks.
2. `POST /{id}/pipeline/approve` → verified `launch_manager` (patched, `patch()` auto-detects it's
   `async def` and uses `AsyncMock`) is scheduled via `asyncio.create_task(...)` with the correct
   `task_id`.
3. `run_manager()`'s own orchestration tested directly (not via HTTP), with
   `run_backend_dev`/`run_qa`/`run_reviewer` mocked at their **home modules**
   (`app.agents.backend_dev.run_backend_dev`, etc.) — not `app.agents.manager`'s local-import call
   site, the same lesson already documented in `test_prompt_registry.py`/`test_versioned_memory.py`
   for why patching a calling module's local import silently doesn't work.
4. Same, with a QA-fails-then-passes `side_effect`, verifying the existing bounded retry loop
   (`max_retries`) actually retries and succeeds.

**Scope decision**: `run_backend_dev`/`run_qa`/`run_reviewer` already have dedicated test coverage
elsewhere (`test_session2_migration.py`, `test_dispatcher.py`,
`tests/pending/test_specialist_agents.py`) — re-simulating their full LLM tool-calling personas
through a real git worktree here would re-test already-covered internals rather than the actual
wiring gap (HTTP → pipeline → approve → manager dispatch) this file exists to close.

A real bug/design smell was found and verified empirically rather than fixed reflexively:
`pipeline/graph.py`'s `human_review_node` has both `interrupt_before=["human_review"]` (graph-level)
**and** an inner `interrupt(...)` call inside the node body — redundant on paper, but the smoke
test confirms `resume_pipeline()`'s `Command(resume=...)` call correctly produces `stage == "done"`
on approval, so the existing behavior is correct despite the redundant-looking construct. Documented
in the plan doc rather than "fixed" without a concrete failure to justify touching working code.

## Part 2 — Failure Recovery Ladder (`app/fleet/failure_ladder.py`, 15 tests)

Verified what already existed before writing anything (`fleet_checkpoint.py`, `agent_registry.py`,
`VALID_TRANSITIONS`, `run_agent_graph()`'s exception handler, all read in full):

| State | Before Day 12 | What Day 12 did |
|---|---|---|
| Checkpoint | Real, complete | Re-exported under a ladder-discoverable name — no new logic |
| Rollback | Real, complete | Same |
| Resume | Missing | New: wraps `restore_checkpoint()`, raises if not found (distinct intent from Rollback) |
| Retry | Missing at the ladder level | New: `should_retry()` bounded decision function (swe-agent's `forward_with_handling()` pattern — reuses existing `settings.max_retries`, no duplicate config) |
| Escalate | Implicit side effect only | Made explicit: wraps `agent_registry.fail_task()` + a `health_updated` event |
| Abort | **Unreachable** — `"failed"` was a defined terminal status with zero incoming transitions | Closed: `"failed"` added as a valid target from every in-progress status in `VALID_TRANSITIONS` |
| Human Review | Missing | New: reuses the existing `"blocked"` transition + `review_requested()` event — NOT a LangGraph `interrupt()` pause (that's Day 13's scope) |

**Wiring decision**: rather than add a new bounded retry loop inside `run_agent_graph()` (the hot
path for all 72+ agents — high risk for the value), the existing, already-tested per-subtask retry
loop in `run_manager()` was identified as the real "Retry" mechanism already in production. Wired
`escalate()`/`request_human_review()` into its per-subtask retry-exhaustion branch, and `abort()`
into its whole-epic-halt branch. Added a much lower-risk, purely additive stall-detection hook
(`n_stalls >= max_stalls` after `graph.invoke()` returns normally, no exception involved) into
`base_graph.py`'s post-graph section → `escalate()` then `request_human_review()`.

## Part 3 — Event Compliance (`tests/test_event_compliance.py`, 3 tests)

Static AST scan of every `publish(<constructor>(...))` call site under `app/`. Asserts the observed
`FleetEventType` values are a **subset** of the canonical 8, not equal to them — `task_created` and
`memory_created` had zero call sites anywhere before this session (confirmed by grep), and the
plan's own stated rationale ("any event type NOT in this set → fails") is about preventing *ad-hoc*
types, which a subset check catches without being fragile to legitimate temporary gaps in which
canonical types happen to be in active use on a given day.

## Part 4 — Hierarchy Chain (`tests/test_hierarchy_chain.py`, 3 tests)

Added the actual `fleet_manager.select(required_capability=...)` +
`publish(task_created(task_id=..., title=..., agent_name="manager"))` calls into
`run_manager()`'s subtask dispatch loop — additive, alongside the existing direct dispatch, doesn't
change which function actually runs for a subtask.

Verified all 6 real chain steps against the two real integration points (not one aspirational
single chain, since the codebase doesn't have one):
1–2. `fleet_manager.select()` + `capability_registry` lookup — real, tested directly.
3. `agent_bus` publishes `TaskCreated` — verified via a real `FleetBus` subscriber wrapping
   `bus.publish` to capture actual emitted events (not just asserting a mock was called), driven
   through a real `run_manager()` call.
4–6. verification_layer / reflection_node / lesson_node / `AgentResult` — verified via a direct
   `run_agent_graph()` call with a stateful mock LLM (`_HierarchyChainLLM`) that correctly
   satisfies reflection's `{"satisfied": true}` JSON and lesson extraction's real `{"lesson": ...}`
   JSON (unlike Part 1's simpler generic mock, which would leave the lesson text empty and never
   trigger `LessonStore.add()` — caught by an initial test failure, not assumed correct upfront).

"knowledge_graph" is excluded — confirmed by search there is no such module anywhere in the
codebase; the plan's vocabulary there is aspirational, and faking a check against it would be
worse than being honest about the gap.

## Files changed

- `backend/app/fleet/failure_ladder.py` (new)
- `backend/app/agents/manager.py` — ladder wiring + fleet_manager/agent_bus additive instrumentation
- `backend/app/agents/base_graph.py` — stall-path ladder wiring
- `backend/app/db/models.py` — `VALID_TRANSITIONS` gains `"failed"` as a reachable target
- `backend/tests/test_day12_smoke_test.py`, `test_failure_ladder.py`, `test_event_compliance.py`,
  `test_hierarchy_chain.py` (all new)
- `docs/DAY12_PLAN.md` (new)

## Test Results

```
pytest tests/ -q
→ 2569 passed, 0 failed, 55 skipped, 17 deselected, 7 warnings in 64.07s

mypy app/ --strict
→ 32 errors, all pre-existing (identical to the Day 11 baseline), 0 new
```

## Verdict
✅ GREEN FLAG — DAY 12 COMPLETE. Ready for Day 13 (Human Approval UI — LangGraph `interrupt()` +
`Command(resume=...)` for full agent-run-level approval flows).
