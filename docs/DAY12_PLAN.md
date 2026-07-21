# Day 12 Implementation Plan — End-to-End Pipeline Validation + Failure Recovery Ladder
Researched and grounded 2026-07-21 (REPO-FIRST + codebase-first verification before any design).

Source: `docs/FLEET_ENHANCEMENT_PLAN.md` lines 911-980.

## Codebase research findings (verified via direct reads, not assumed)

**There are two separate LangGraph graphs, and the plan's Part 1/Part 4 conflate them:**
1. `app/pipeline/graph.py` — epic-level orchestration (`pm → architect → decomposer → human_review`),
   compiled with a REAL checkpointer (`AsyncPostgresSaver` via `init_checkpointer()`, `MemorySaver`
   fallback) and `interrupt_before=["human_review"]` + an inner `interrupt(...)` call inside
   `human_review_node`. This is redundant (the graph already halts before the node runs on the
   first pass, so the inner `interrupt()` call is dead code until resume) — flagged as a design
   smell to verify empirically during the smoke test, not something to theorize about upfront.
2. `app/agents/base_graph.py` — per-agent-run graph (`run_agent_graph`/`build_agent_graph`), used
   by all 72+ individual agents, compiles with **no checkpointer** (confirmed in Day 9 planning via
   `inspect.signature()`).

**The real, live task-flow wiring** (confirmed by reading `api/agents.py`, `pipeline/graph.py`,
`agents/manager.py` in full): `POST /tasks` → `POST /{id}/run` (`launch_planning_pipeline`) →
`run_planning_pipeline()` → compiled `pipeline/graph.py` graph → `pm → architect → decomposer →
human_review` (pauses) → `POST /{id}/approve` → `resume_planning_pipeline` →
`asyncio.create_task(launch_manager(...))` → `app.agents.manager.run_manager()`, which directly
imports and calls `run_qa`/`run_reviewer` by function call. **This whole chain is real and already
wired end-to-end** — Part 1's smoke test is achievable against it, not aspirational.

**What is NOT wired, contrary to the plan's Part 4 hierarchy-chain description**: `fleet_manager.select()`,
`capability_registry` lookups, and `agent_bus` (`fleet_events.publish`) all exist, are unit-tested
in isolation, and every agent self-registers into them via `_register()` — but grep confirms
**nothing in `manager.py`/`api/agents.py`/`pipeline/graph.py` ever calls them**. The Executive
agent (`app/agents/executive.py`, real, calls `run_agent_graph`) is also never invoked from the
live path — it's a standalone entry point today. "knowledge_graph" does not exist as a module
anywhere; the plan's vocabulary is aspirational there (closest real analogs:
`app/repo_tools/context_builder.py`, `memory_context` in `pipeline/state.py`).

**Decision**: rather than restructure `manager.py`'s working dispatch logic, Part 4 adds **small,
additive, non-invasive instrumentation** — a `fleet_manager.select()` call and a
`publish(task_created(...))` call inserted alongside the existing direct dispatch in
`run_manager()` — so the hierarchy chain becomes genuinely exercised in the live path (verifiable
by a real test) without changing what actually decides which function runs. This keeps blast
radius on a well-tested, heavily-used core path minimal.

**Failure Recovery Ladder — what's real vs. missing** (read `fleet_checkpoint.py`, `agent_registry.py`,
`db/models.py`'s `VALID_TRANSITIONS`, and `run_agent_graph()`'s existing exception handler in full):

| State | Status | Real mechanism |
|---|---|---|
| Checkpoint | ✅ exists | `fleet_checkpoint.save_checkpoint()` |
| Rollback | ✅ exists | `fleet_checkpoint.rollback_to()` |
| Resume | ❌ missing | closest analog: `pipeline/graph.py`'s `resume_pipeline()` (pipeline-level, not per-agent-checkpoint-level) |
| Retry | ❌ missing | `retry_count` field exists in `AgentRunState` but is never incremented anywhere; `n_stalls`/`max_stalls` only ever stops the graph, never retries |
| Escalate | ⚠️ partial | `run_agent_graph()`'s existing top-level exception handler already calls `agent_registry.fail_task()` (state=ERROR, unhealthy at 3 failures) — real, but not exposed as a deliberate, nameable ladder rung |
| Abort | ❌ missing | `VALID_TRANSITIONS` (`db/models.py`) has a `"failed"` terminal status but **nothing ever transitions into it** — confirmed by inspection, not assumed |
| Human Review | ⚠️ partial | `"blocked"` is a valid transition target from every in-progress status already, but no ladder-level function sets it + emits `review_requested()` together as one action |

**swe-agent's `AbstractAgent.run()`** (`repos/swe-agent/sweagent/agent/agents.py`, the plan's own
cited pattern source): `while not step_output.done: step_output = self.step(); self.save_trajectory()`
— trajectory saved after every step (cheap, unconditional persistence, the closest analog to
"Checkpoint"). Retry is bounded and two-tier: `forward_with_handling()` does a per-step bounded
requery on `FormatError` (`n_format_fails < self.max_requeries`), while a separate `RetryAgent`
wrapper does whole-attempt retries on top. This directly informs the Retry design below: reuse the
existing `settings.max_retries` (already in config, was previously described as "pipeline-level"
but is generically named and unused elsewhere) rather than adding a duplicate config field.

## Part 1: Smoke Test

Drive a real task through the FastAPI `TestClient` (not direct function calls — the existing
`tests/pending/test_pipeline_e2e.py` already covers direct-call PM→Architect→Decomposer with a
real API key; this smoke test covers the full HTTP-level flow with mocked LLM calls, since no
`ANTHROPIC_API_KEY` is configured in this environment):
`POST /tasks` → `POST /{id}/run` → (pipeline pauses at human_review) → `POST /{id}/approve` →
`launch_manager` → `run_qa`/`run_reviewer`. Log every stage transition. Fix any real bugs found
(starting candidate: the `interrupt_before` + inner `interrupt()` redundancy in `human_review_node`
— verify empirically whether resume actually works correctly before touching it).

## Part 2: Failure Recovery Ladder — `app/fleet/failure_ladder.py`

Thin, testable wrappers over what already exists, plus the 4 genuinely-new rungs:
- `checkpoint()`/`rollback()` — re-export `fleet_checkpoint.save_checkpoint`/`rollback_to` under
  ladder-discoverable names (no new logic)
- `resume(checkpoint_id)` — wraps `fleet_checkpoint.restore_checkpoint`, raises if not found
  (distinct intent from rollback: continues forward, doesn't imply reverting bad progress)
- `should_retry(retry_count, max_retries=None) -> bool` — pure decision function, defaults to
  `settings.max_retries` (existing config field, reused not duplicated)
- `escalate(agent_name, reason, trace_id="")` — calls `agent_registry.fail_task()` (the same
  mechanism `run_agent_graph()`'s exception handler already uses) + publishes `health_updated`
  with `health="degraded"` — makes the existing implicit behavior an explicit, testable rung
- `abort(task_id, reason, trace_id="")` — sync facade (isolated-engine-per-call `asyncio.run()`
  pattern, matching Days 10-11) calling `transition_task(db, task_id, "failed")` + publishing
  `task_failed`. Requires adding `"failed"` as a valid target from in-progress statuses in
  `VALID_TRANSITIONS` (`db/models.py`) — currently unreachable, a real gap closed here.
- `request_human_review(task_id, agent_name, reason, trace_id="")` — sync facade calling
  `transition_task(db, task_id, "blocked")` (already valid) + publishing `review_requested`. This
  is NOT a LangGraph `interrupt()`-based pause (that's `pipeline/graph.py`'s job, and full
  approval-UI wiring is explicitly Day 13's scope) — it's the ladder's "flag for a human" rung.

**Wiring into `base_graph.py`** (careful, since this is the hot path for all 72+ agents):
- Stall path (no exception, `final_state["n_stalls"] >= max_stalls` after `graph.invoke()`
  returns normally): `escalate()` then `request_human_review()` — matches the plan's own ladder
  for stalls exactly (skips retry/abort, since retrying a stalled agent from the same node with no
  new information is unlikely to help).
- Exception path (`graph.invoke()` raises): wrap in a bounded loop consulting `should_retry()`;
  on exhaustion, `escalate()` then `abort()` if `task_id` is a real numeric `DevTask.id`, else just
  `escalate()` (many agent runs — Day 9 fleet agents, Executive — have no corresponding `DevTask`
  row; abort must be a guarded, best-effort, non-fatal call, matching this file's existing
  defensive style throughout).

## Part 3: Event Compliance Test — `tests/test_event_compliance.py`

Static AST scan across every agent module: collect every `publish(...)` call's event-constructor
name, map back to `FleetEventType`, assert the observed set is exactly the 8 canonical types.
Mechanical, no design risk — the 8 types and their constructors already exist in `fleet_events.py`.

## Part 4: Hierarchy Chain Verification — `tests/test_hierarchy_chain.py`

After the additive `fleet_manager.select()` + `publish(task_created(...))` instrumentation lands
in `run_manager()` (Part 4's only production code change — everything else in this part is test
code), write an integration test (mocked LLM) asserting all 6 real chain steps: fleet_manager
selection happened, capability_registry returned a spec, `TaskCreated` was published,
`reflection_node` received a non-empty verification dict, a lesson was stored via
`_extract_and_store_lesson`, and `AgentResult`/`final_state["result"]` is non-empty. Framed
honestly against what's real — not the aspirational "knowledge_graph" step, which is out of scope
since no such module exists.

## Build order
1. Part 1 (smoke test) — foundational, may surface real bugs to fix before anything else.
2. Part 2 (failure ladder) — new module + `VALID_TRANSITIONS` extension + guarded `base_graph.py`
   wiring, tested in isolation first, then full-suite-verified (this touches every agent's hot path).
3. Part 3 (event compliance) — mechanical, fast.
4. Part 4 (hierarchy chain) — small additive wiring + integration test.
5. Full suite + mypy, update `PROJECT.md`/Control Center, write
   `docs/reports/FLEET_DAY12_TEST_REPORT.md`, commit.
