# Gap-Closure Report — Days 11–13 Audit
Date: 2026-07-21

## Why this audit happened

Per explicit user request, before starting Day 14: "check 11 to 13 is there anything is missing."
Rather than re-checking test pass/fail status (already green), the audit specifically asked: **is
every module built in Days 10–13 actually called from real production code, or just built, tested
in isolation, and registered — but never exercised?** This is exactly the class of gap Day 12
already found once (`fleet_manager`/`capability_registry`/`agent_bus` existed, were unit-tested,
self-registered by every agent, but nothing in the live task-flow ever called them).

## Method

- Fresh full suite + mypy run (baseline: 2583 passed, 32 pre-existing mypy errors).
- Residual-data check across all Day 10–13 tables (`prompt_versions`, `versioned_lessons`,
  `agent_benchmarks`, `pending_approvals`) — all 0 rows, confirming test cleanup discipline held.
- `grep` for TODO/FIXME/stub markers in every Day 11–13 file — none found.
- **The real check**: `grep -rln "from app.fleet.X"` for each of `prompt_registry`,
  `regression_detector`, `versioned_memory`, `failure_ladder`, `budget_manager`,
  `benchmark_manager`, `tool_discovery` across `app/` (excluding each module's own file and its
  tests) — to see who, if anyone, actually calls each one.
- Cross-checked findings against each day's own plan doc (`docs/DAY10_PLAN.md`,
  `docs/DAY11_PLAN.md`) to distinguish "the plan explicitly promised this wiring and it's missing"
  from "this was always standalone infrastructure, adoption is a separate decision."

## Findings

### 1. `versioned_memory.publish()` (Day 11) — never called, contrary to the plan's own design section

`grep` confirmed zero callers outside its own test file. Day 11's own plan doc
(`docs/DAY11_PLAN.md`) identified `_extract_and_store_lesson()` (`base_graph.py`) as "the exact
call site Day 11's own plan doc identified as the target," and described `versioned_memory.py` as
"the durable, versioned lifecycle layer on top" of `LessonStore` — implying lessons should flow
into both. They never did; `_extract_and_store_lesson()` only ever called
`get_lesson_store().add(lesson)`.

**Severity**: real — the entire merge-on-conflict lesson lifecycle (10 tests, fully working in
isolation) had received zero real lessons from any actual agent run since it was built.

### 2. `versioned_memory.archive_expired()` (Day 11) — plan explicitly promised background-loop wiring, never delivered

Day 11's plan doc, Module 3 design section, states verbatim: `archive_expired()` should be "called
from the same background-loop slot pattern already used for retention/reindex in main.py's
lifespan." `grep app/main.py` for `archive_expired` returned nothing. This is the clearest of the
five findings — a design decision documented in my own plan and never implemented.

### 3. `benchmark_manager.store_baseline()` (Day 10) — never called automatically

No scheduled or triggered process ever computes a benchmark or stores a baseline for any real
agent. Day 10's plan doc did not explicitly commit to automatic scheduling (it deferred "fixture
repos" as a separate, narrower nice-to-have), so this is not a broken promise in the same way as
finding #2 — but it has a real, concrete consequence: `regression_detector.compare_to_baseline()`
treats "no stored baseline" as "no regression" by design (`baseline_score is None` →
`is_regression=False`). Since no agent has ever had a baseline, **`prompt_registry.deploy()`'s
regression gate — built and tested in Day 11 — has been a permanent no-op for every real agent**;
it would never actually block a deploy today, regardless of how badly an agent had regressed.

### 4. `tool_discovery.py` (Day 10) — never consulted anywhere

Confirmed by grep: zero callers outside its own tests. Lowest severity — Day 10's plan didn't
commit to wiring it into any specific call site, so this is "built, correct, unused" rather than a
broken promise.

### 5. `approval_gate.record_pending()` (Day 13) — restart edge case

`record_pending()` always inserted a fresh row, never checking for or superseding a prior
undecided row for the same `thread_id`. Restarting a task via `POST /tasks/{id}/restart` while it's
paused at `human_review` (a real, reachable code path — `restart_task()` force-resets status
regardless of current state) would leave the old row permanently stuck as `"pending"`, no longer
reachable via a real decision, and duplicated in `list_pending()`'s results.

## Fixes applied (user approved fixing all before Day 14)

1. **`base_graph.py`**: `_extract_and_store_lesson()` now calls
   `get_versioned_memory_store().publish(topic, lesson.lesson, agent_name=role_name)` — gated on
   `get_settings().voyage_api_key` being non-empty.
2. **`main.py`**: new `_versioned_lesson_archive_loop()`, wired into the lifespan alongside the
   existing reindex/retention/fleet-scan loops, once-per-day cadence.
3. **`main.py`**: new `_benchmark_baseline_loop()` (new config
   `BENCHMARK_BASELINE_INTERVAL_HOURS`, default 24) — sweeps `capability_registry`, stores an
   initial baseline for any agent with real `MetricsCollector` runs but none yet; skips agents
   with no data; never overwrites an existing baseline.
4. **`fleet_manager.py`**: `select()` gains an opt-in `verify_tool_availability: bool = False`
   parameter (default preserves all existing behavior exactly) that skips candidates whose
   declared tools aren't resolvable via `tool_discovery.check_availability()`. Enabled at its one
   real call site, `run_manager()` (wired in Day 12), via `verify_tool_availability=True`.
5. **`approval_gate.py`**: `_record_pending()` now flips any existing `"pending"` row for the same
   `thread_id` to `"superseded"` before inserting the new one.

## A second real bug, found while fixing gap #1 — not assumed away

Wiring `versioned_memory.publish()` unconditionally into `_extract_and_store_lesson()` (which runs
on every agent completion, `enable_lesson` defaulting `True` across roughly 2500 existing tests)
was verified against the **full test suite**, not just the new gap-closure tests in isolation —
and this surfaced 3 real failures in Day 11's own `test_versioned_memory.py`. Root cause: other
tests' mocked runs (e.g. `test_hierarchy_chain.py`) wrote real, zero-vector-embedded rows into the
shared `versioned_lessons` table as a side effect of the new wiring; `versioned_memory.py`'s own
similarity search (`_find_most_similar_published()`) then picked up that contaminating data during
Day 11's OWN tests, spuriously triggering the merge code path and exhausting a deterministic mock
iterator sized for the non-merge path (`RuntimeError: coroutine raised StopIteration`).

Fixed by gating the new call on a real embedding key (finding #1's fix) — a zero-vector embedding
can never be found again by similarity search anyway (the same "meaningless without a key" logic
already used inside `app/memory/store.py`), so skipping it entirely is both the environmentally
correct behavior for this key-less dev/test setup and the fix for the contamination.

A **third**, smaller instance of the same class of bug was then found in the gap-closure work's
own new test file (`test_benchmark_baseline_loop.py`): the real `_benchmark_baseline_loop()`
sweeps every agent in the process-wide `capability_registry`, so running it inside a test creates
real baseline rows for whatever real agents (e.g. `"pm"`, `"architect"`, `"decomposer"`) happen to
have accumulated `MetricsCollector` data from earlier tests in the same pytest session. Fixed by
snapshotting existing baseline agent names before/after each test's loop invocation and cleaning up
anything incidental beyond the test's own fixture agent.

## Test Results

```
pytest tests/ -q
→ 2596 passed, 0 failed, 55 skipped, 17 deselected, 10 warnings in 78.51s

mypy app/ --strict
→ 32 errors, all pre-existing (identical to the Day 13 baseline), 0 new
```

13 new tests: `test_lesson_versioned_memory_wiring.py` (2), `test_lesson_archive_loop.py` (2),
`test_benchmark_baseline_loop.py` (4), `test_fleet_manager.py`'s new `TestVerifyToolAvailability`
class (4), `test_approval_gate.py`'s new supersede test (1).

Verified 0 residual rows across `prompt_versions`, `versioned_lessons`, `agent_benchmarks`, and
`pending_approvals` after the full suite run, including after discovering and fixing the second
round of test contamination described above.

## Verdict
✅ GREEN FLAG — GAP-CLOSURE COMPLETE. Ready for Day 14 (Git Push Workflow).
