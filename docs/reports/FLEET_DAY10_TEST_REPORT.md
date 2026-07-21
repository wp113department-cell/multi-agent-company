# Fleet Day 10 Test Report — budget_manager, benchmark_manager, tool_discovery
Date: 2026-07-21

## What was built

Per `docs/DAY10_PLAN.md` (researched and grounded 2026-07-21 before implementation). Three new
Fleet OS infrastructure modules — but the first and most important thing built was a fix to a
foundational bug discovered during planning, without which the other two would have measured
nothing.

### The foundational fix: RunMetrics was never populated, since Day 0

`app/fleet/metrics.py`'s `RunMetrics`/`MetricsCollector` looked fully built — `tokens_in`,
`tokens_out`, `cost_estimate_usd`, `verification_pct`, `confidence`, `retries`, `tool_calls`, all
with real methods (`record_tokens()`, `record_tool()`). But in `app/agents/base_graph.py`,
`run_span()` is a `@contextmanager`; the code did:

```python
_span = run_span(role_name, task_id="", trace_id=tid)
_span.__enter__()   # return value discarded
```

`_span.__enter__()` returns the actual `RunMetrics` instance, but nothing captured it — `_span`
held the context-manager wrapper object, not `RunMetrics`. Every run recorded since Day 0 had
zeroed-out metrics regardless of what actually happened. Fixed by capturing
`_metrics = _span.__enter__()` as a separate variable, then after `graph.invoke()`:

- `_metrics.record_tokens(final_state["tokens_in"], final_state["tokens_out"])`
- `_metrics.confidence = final_state["confidence"]`
- `_metrics.retries = final_state["retry_count"]`
- `_metrics.verification_pct` computed from the mean of boolean values in `final_state["verification"]`
- `_metrics.reflection_unsatisfied` (new — see below)

And inside `execute_tools`, real per-call timing (`time.monotonic()`) + `_metrics.record_tool(name, success, duration_ms, error)` via `get_metrics_collector().get(trace_id)`.

Verified with `tests/test_metrics_wiring.py` (3 tests) using a real (mocked-LLM) `run_agent_graph()`
call — asserting against the run's own reported totals, not hardcoded turn counts — **before**
building budget_manager or benchmark_manager on top of it.

### A second real gap found and closed: hallucination_rate had no underlying signal

`benchmark_manager`'s 7th objective needed `reflection_node`'s `satisfied` judgment, but that
value was computed locally inside `reflection_node` and discarded every run — never returned into
state. Added `reflection_unsatisfied_count: int` to `AgentRunState` (optional field, `total=False`,
zero breakage to existing callers), incremented it in `reflection_node` when `satisfied=False`, and
wired it into `RunMetrics.reflection_unsatisfied` alongside the other Day 10 metrics. This makes
`hallucination_rate` a real (if approximate — documented as a conservative proxy) computed value,
not a stub.

### tool_discovery.py

A thin index over the two registries that already existed — `tool_manifest.py` (tool → risk /
permission data, 191 entries) and `capability_registry.py` (agent → tools it uses) — instead of
re-scanning agent source files via AST, which the plan's literal text first suggested but which
would have duplicated data already tracked correctly elsewhere.

- `discover_tools(capability) -> list[ToolSpec]` — union of `.tools` across every
  `AgentCapability` tagged with that capability, each resolved against `TOOL_MANIFEST`
- `check_compatibility(tool_name, agent_name) -> bool` — mirrors
  `tool_manifest.verify_agent_contract()`'s exact "declared vs. used" rule (is the tool in the
  agent's own `AgentCapability.tools`?) rather than inventing a new risk-tier-matching scheme
- `check_availability(tool_name) -> bool` — best-effort static check (manifest, overlay, or a
  top-level callable in `app.agents.tools`); explicitly NOT a live handler probe (building a
  handler needs a `repo_path` and has side effects)
- `register_tool(spec)` — appends to an in-process overlay, never mutates the static manifest
- `ToolDiscovery` is a plain class (not forced into the module-singleton pattern for tests);
  `get_tool_discovery()` provides the process singleton

14 tests in `tests/test_tool_discovery.py`.

### budget_manager.py

Two-tier live enforcement — per-run limits and daily cumulative spend — following swe-agent's
`per_instance_cost_limit`/`total_cost_limit` split (`repos/swe-agent/sweagent/agent/models.py`).
Complementary to, not a replacement for, two pieces of existing infrastructure:
`app/pipeline/concurrency.py` (concurrency caps — how many runs at once) and
`app/pipeline/cost_controller.py` (pre-flight cost *estimation* before an epic starts, gating
human approval). `budget_manager` checks *actual* spend/resource use after a run completes.

- `BudgetExceeded(dimension, scope, limit, actual)` — a dataclass-Exception; `dimension` is
  `"tokens" | "cost" | "time" | "memory"`, `scope` is `"run" | "daily"`
- `check_run(metrics: RunMetrics)` — raises on token overage, wall-clock time overage, or
  memory overage (`resource.getrusage(RUSAGE_SELF).ru_maxrss` — stdlib only, no new dependency;
  documented as a process-wide proxy, not per-run-isolated, since Python has no cheap way to
  attribute RSS to one run inside one process)
- `check_daily(agent_name=None)` — sums `MetricsCollector.all_runs()` (new accessor added to
  `MetricsCollector`) filtered to today's UTC date, optionally scoped to one agent
- New config (all in `config.py` + `.env.example`, zero hardcoding): `MAX_TOKENS_PER_AGENT_RUN`
  (100,000), `COST_BUDGET_DAILY_USD` ($25), `MAX_RUN_TIME_SECONDS` (600), `MAX_MEMORY_MB` (1024)
- Wired into `base_graph.py`'s post-graph section, after `_span.__exit__()`: on `BudgetExceeded`,
  `final_state["status"] = "blocked"` and a `health_updated` Fleet OS event is published. No new
  escalation pathway — that is explicitly Day 12's job.

10 tests in `tests/test_budget_manager.py`.

### benchmark_manager.py

7 objectives per agent, computed from real `MetricsCollector` data (each one grounded against
what's actually computable, verified with a manual sanity check before writing tests):

| Objective | How it's computed |
|---|---|
| `latency_p50` | `MetricsCollector.p50_latency_ms()` — real, already existed |
| `tool_accuracy` | `MetricsCollector.avg_tool_accuracy()` — real, was measuring nothing before the metrics fix |
| `verification_coverage` | mean of `verification_pct` across the sampled window |
| `retry_success` | of runs where `retries > 0`, fraction that ended `status == "completed"` |
| `compile_success` | of `tool_calls` where the tool is `run_tests`/`run_linter`, fraction `success=True` |
| `hallucination_rate` | fraction of runs with `reflection_unsatisfied > 0` — new signal (see above), documented as a conservative proxy |
| `benchmark_score` | config-weighted composite of the other 6 (6 `BENCHMARK_WEIGHT_*` fields + a latency-normalization target, all in config — zero hardcoded weights) |

All "no data yet" cases default to a benign value (1.0 for the "good" direction, 0.0 for
`hallucination_rate`) rather than crashing or returning `None` — consistent with how
`RunMetrics.tool_accuracy` already handles the no-tool-calls case.

Baselines persist in **Postgres**, not an in-process store — `agent_benchmarks` table
(migration 012, `AgentBenchmark` ORM model in `app/db/models.py`), because regression history
needs to survive a process restart to be useful. `store_baseline()` flips any prior baseline row
for that agent to `is_baseline=false` rather than deleting it (append-only history for audit) and
inserts the new one. DB access uses the same isolated-fresh-engine-per-call pattern established in
Day 9 (`_new_isolated_db_engine()`-equivalent) to avoid the recurring asyncio-event-loop-reuse bug.

Fixture-repos-per-agent-type (mentioned in earlier planning) are explicitly deferred: this
measures real production runs first, not synthetic scenarios, until enough real data exists to
justify building fixtures.

11 tests in `tests/test_benchmark_manager.py`, including a real Postgres round-trip
(store → flip-prior-baseline → compare) with `try/finally` cleanup of every test row —
verified 0 residual rows in `agent_benchmarks` after the full run.

## Files changed

- `backend/app/agents/base_graph.py` — metrics-wiring fix, budget enforcement wiring,
  `reflection_unsatisfied_count` plumbing
- `backend/app/fleet/metrics.py` — `RunMetrics.reflection_unsatisfied` field,
  `MetricsCollector.all_runs()` accessor
- `backend/app/fleet/tool_discovery.py` (new)
- `backend/app/fleet/budget_manager.py` (new)
- `backend/app/fleet/benchmark_manager.py` (new)
- `backend/app/db/models.py` — `AgentBenchmark` ORM model
- `backend/migrations/versions/012_agent_benchmarks.py` (new)
- `backend/app/config.py` — 4 budget fields + 8 benchmark fields (weights, latency target,
  regression threshold)
- `backend/.env.example` — matching entries with descriptions
- `backend/tests/test_metrics_wiring.py`, `test_tool_discovery.py`, `test_budget_manager.py`,
  `test_benchmark_manager.py` (all new)

## Test Results

```
pytest tests/ -q
→ 2517 passed, 0 failed, 55 skipped, 17 deselected, 4 warnings in 44.97s

mypy app/ --strict
→ 32 errors, all pre-existing (identical to the Day 9 baseline), 0 new
```

Verified no residual rows in `agent_benchmarks` after the full suite run (real DB writes, all
cleaned up in `try/finally`).

## Verdict
✅ GREEN FLAG — DAY 10 COMPLETE. Ready for Day 11 (prompt_registry, regression_detector,
versioned_memory).
