# Day 10 Implementation Plan — budget_manager + benchmark_manager + tool_discovery
Prepared: 2026-07-21 (research/planning session — implementation next session)

## Source of truth
- `docs/FLEET_ENHANCEMENT_PLAN.md` lines 824–865 (Day 10 summary)
- `files/agent_enhancement.md` lines 544–616 (§9 Benchmark Management, §11 Resource
  Budgeting, §13 Tool Discovery — richer than the plan doc's summary)

## The most important finding: this can't be built on top of what exists yet — the metrics substrate is empty

Checked `app/fleet/metrics.py`'s `RunMetrics`/`MetricsCollector` (the obvious place budget and
benchmark data should come from) against every place in the codebase that could plausibly
populate it. **None of these fields are ever set outside `metrics.py`'s own defaults**:
`tokens_in`, `tokens_out`, `cost_estimate_usd`, `verification_pct`, `memory_retrieved`,
`memory_written`, `confidence`, `retries`, `failures`. `run_span()` is entered/exited around
every `run_agent_graph()` call (`base_graph.py:817-819`), so `execution_time_ms` and `status`
are real — but nothing ever calls `span.record_tokens(...)` or sets any of the other fields.
**Every run recorded by `MetricsCollector` today has `tokens_in=0, tokens_out=0,
cost_estimate_usd=0.0`, `verification_pct=0.0`.**

This means: before budget_manager can enforce a token/cost limit, or benchmark_manager can
compute `tool_accuracy`/`verification_coverage` trends, the data they'd check against doesn't
exist. **Day 10's first, foundational task is wiring real data into `RunMetrics`** — not
optional infrastructure, a blocking prerequisite. Concretely, in `base_graph.py`'s
`run_agent_graph()` (the single choke point every agent already passes through):
- After `graph.invoke()` returns `final_state`, call
  `_span.record_tokens(final_state["tokens_in"], final_state["tokens_out"])` once, before
  `_span.__exit__(...)` — confirmed `record_tokens(tokens_in, tokens_out)` accumulates
  (`self.tokens_in += tokens_in`), and `final_state["tokens_in"]` is already the run's
  cumulative total, so calling it exactly once per run (not per-turn) is correct
- Set `_span.confidence = final_state.get("confidence", 1.0)`
- Set `_span.retries = final_state.get("retry_count", 0)`
- Compute `verification_pct` from `final_state["verification"]` (fraction of expected keys
  that are `True`) and set it directly (no setter method exists yet — it's a plain
  dataclass field)
- `tool_calls` (used by `avg_tool_accuracy`) — confirmed the real method is
  `RunMetrics.record_tool(tool_name, success, duration_ms, error=None)` (not
  `record_tool_call` — verify method names against the source before using them, don't
  guess from the field name). Confirmed via grep this is never called anywhere in
  `base_graph.py` — needs wiring into `execute_tools` after each tool call resolves

**This is real, scoped, mechanical work — a few lines in one function — but it's the
difference between budget/benchmark managers that actually work and ones that silently do
nothing.** Verify with a real test: run a mocked agent graph, assert `MetricsCollector`
recorded non-zero tokens/verification after the run.

## Repo-first research done today

- **`repos/swe-agent/sweagent/agent/models.py`** (`InstanceStats`) + `reviewer.py` — the
  exact two-tier budget pattern: `per_instance_cost_limit` (this one run) and
  `total_cost_limit` (cumulative), each raising a distinct, specific exception
  (`InstanceCostLimitExceededError`, `TotalCostLimitExceededError`) rather than one generic
  "over budget" error. Directly shapes `budget_manager.py`'s two-tier design below.
  `InstanceStats` (`instance_cost`, `tokens_sent`, `tokens_received`, `api_calls`) is
  structurally identical to our own `RunMetrics` — validates that `RunMetrics` is the right
  substrate once it's actually populated (see above), not a design that needs to change.
- **`repos/aider/aider/models.py`** — `max_chat_history_tokens` is a *context-window* budget
  (how much history to keep in the prompt), a different concern already handled by our own
  `context_token_budget` param in `base_graph.py`. Confirmed this is *not* what Day 10's
  budget_manager should duplicate — Day 10 is about spend/resource limits, not context
  window management.
- **composio's provider pattern** (from Day 9's research, re-applied here) — tool schemas
  normalized once, referenced by every provider. Confirms `tool_discovery.py` should be a
  thin *index* over data that already exists (see below), not a second source of truth.

## Codebase grounding — what already exists vs. what's actually new

| Need | Status |
|---|---|
| Per-run cost/token/time data (`RunMetrics`) | ⚠️ Structure exists, **fields never populated** — see above, this is Day 10's real first task |
| Pre-flight cost *estimation* before a task starts | ✅ Exists — `app/pipeline/cost_controller.py::estimate_epic_cost` (historical-average based, gates human approval above `cost_approval_threshold`). **Different from Day 10's budget_manager**: this estimates *before* a run; Day 10 needs to enforce *during/after* a run against real spend. Don't duplicate — budget_manager is a live enforcer, cost_controller is a pre-flight estimator; they're complementary, not overlapping. |
| Concurrency caps (`MAX_CONCURRENT_AGENTS`) | ✅ Fully implemented — `app/pipeline/concurrency.py`, `asyncio.Semaphore`-based (`epic_slot`, `agent_run_slot`, `subtask_slot`), config-driven (`max_concurrent_agent_runs` etc. already in `config.py`). **budget_manager should not reimplement this** — it's the token/cost/time/memory dimensions that are actually missing. |
| Static tool→risk/permission registry | ✅ `app/fleet/tool_manifest.py` — `TOOL_MANIFEST: dict[str, ToolManifestEntry]`, 191 entries, plus the real `verify_agent_contract()`/`is_high_risk()` functions Day 7 already validated against |
| Per-agent tool usage + capability tags | ✅ `app/fleet/capability_registry.py` — every agent's `AgentCapability.tools`/`.capabilities` is already populated at `_register()` time. **`tool_discovery.py` should be built as a thin index combining these two existing registries**, not by re-scanning agent source files via AST at startup (the plan's literal suggestion) — that data is already collected, scanning source again would be redundant and a second, driftable source of truth |
| Benchmark fixture repos, regression comparison | ❌ Nothing exists — genuinely new |
| Memory-usage tracking | ❌ Nothing exists. No `psutil` dependency currently in `requirements.txt` — use stdlib `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` instead of adding a new dependency for what the spec treats as a secondary budget dimension |

## budget_manager.py — design

Per `agent_enhancement.md` §11, 5 dimensions: tokens, API cost, execution time, concurrent
tasks (already handled — see above), memory usage.

```
backend/app/fleet/budget_manager.py
  class BudgetExceeded(Exception):
      dimension: str          # "tokens" | "cost" | "time" | "memory"
      scope: str              # "run" | "daily"
      limit: float
      actual: float

  class BudgetManager:
      def check_run(self, metrics: RunMetrics) -> None:
          """Raise BudgetExceeded if this single run is over its per-run limits
          (MAX_TOKENS_PER_AGENT_RUN, per-run time limit). Called right after a
          run_agent_graph() call completes, using the now-real RunMetrics."""

      def check_daily(self, agent_name: str | None = None) -> None:
          """Raise BudgetExceeded if cumulative spend today (across MetricsCollector's
          ring buffer, filtered to today's runs, optionally per-agent) exceeds
          COST_BUDGET_DAILY_USD. Mirrors swe-agent's total_cost_limit."""

  def get_budget_manager() -> BudgetManager  # singleton, same pattern as get_metrics_collector()
```

New config (never hardcoded): `MAX_TOKENS_PER_AGENT_RUN`, `COST_BUDGET_DAILY_USD`,
`MAX_RUN_TIME_SECONDS`, `MAX_MEMORY_MB` — all in `config.py` + documented in `.env.example`,
following the exact pattern of the existing `cost_approval_threshold` etc.

**Enforcement point**: wire into `run_agent_graph()`'s post-graph section (`base_graph.py`,
right after the metrics-recording fix above) — on `BudgetExceeded`, the task's policy is
"blocked, downgraded, deferred, or escalated" per `agent_enhancement.md` §11. Simplest,
correct-for-Day-10 version: set `final_state["status"] = "blocked"` and emit a
`HealthUpdated`-style event (reuse the existing fleet event bus) rather than building a new
escalation pathway — Day 12's failure-recovery-ladder work is where the fuller
Escalate/Human-Review states get formalized; don't scope-creep into that here.

## benchmark_manager.py — design

Per §9: maintain fixture repos per agent type, run regression benchmarks, compare vs
historical baseline, publish trends, store history. Plan's 7 measurable objectives —
grounded against what's actually computable once the metrics-wiring fix lands:

| Objective | Source |
|---|---|
| `latency_p50` | ✅ `MetricsCollector.p50_latency_ms()` — already implemented, already real (execution_time_ms is genuinely populated today) |
| `tool_accuracy` | ✅ `MetricsCollector.avg_tool_accuracy()` — implemented, but depends on `tool_calls` being recorded via `RunMetrics.record_tool(...)`, confirmed never called in `base_graph.py` — needs the same wiring fix as tokens |
| `verification_coverage` | ⚠️ Needs the `verification_pct` wiring fix above |
| `retry_success` | ⚠️ Needs `retries` wiring — then: did a run that retried still end up `submitted=True`? |
| `compile_success` | ❌ New signal — for code-writing agents, whether `run_tests`/type-check tool calls in that run returned clean. Derive from `tool_calls` records where `tool_name` is a known verification tool (`run_tests`, `run_linter`) and `success=True` |
| `hallucination_rate` | ❌ New, and genuinely hard to automate — no existing signal claims vs. evidence. **Scope this conservatively for Day 10**: a simple proxy (fraction of runs where `reflection_node`'s `satisfied=False`) rather than a real hallucination detector — flag as an approximation in the code comment, don't oversell it |
| `benchmark_score` | Composite — weighted combination of the above 6, weights from config (not hardcoded) |

```
backend/app/fleet/benchmark_manager.py
  class BenchmarkResult:
      agent_name: str
      objectives: dict[str, float]   # the 7 above
      timestamp: str

  class BenchmarkManager:
      def run_benchmark(self, agent_name: str, n: int = 20) -> BenchmarkResult:
          """Compute the 7 objectives from MetricsCollector.by_agent(agent_name, n)."""

      def compare_to_baseline(self, agent_name: str) -> RegressionReport:
          """Compare current BenchmarkResult to the last stored baseline. Flag which
          objectives regressed beyond a configurable threshold."""

      def store_baseline(self, agent_name: str, result: BenchmarkResult) -> None:
          """Persist as the new baseline once a human/CI approves it."""
```

**"Fixture repos per agent type"** (§9's first bullet) — re-read carefully: this is about
having *reusable test scenarios* per agent archetype (a debugger-type agent needs a
known-broken-code fixture; a docs agent needs a fixture repo with missing docs), not
literally cloning external repos. Given Day 10's scope and time, **defer building actual
fixture scenarios to when benchmark_manager is exercised against a real agent** — for Day 10
itself, build the measurement/comparison/storage machinery against *real production run
data* (already available once the metrics wiring fix lands) rather than inventing synthetic
fixtures no one asked for yet. Flag fixture-repo scaffolding as a nice-to-have, not the core
deliverable.

**Storage**: given Day 11 wires `versioned_memory.py`'s lesson lifecycle onto the DB, and
given benchmark baselines are conceptually similar (a versioned "this is the accepted
standard" record), consider a small new table now (`agent_benchmarks`) rather than storing
JSON files on disk — keeps it queryable and consistent with how the rest of the fleet OS
persists state. Simple schema: `agent_name`, `objectives` (JSONB), `is_baseline` (bool),
`created_at`.

## tool_discovery.py — design

Per §13's flow: Tool Registry → Capability Scan → Compatibility Check → Availability Check →
Dynamic Registration. Built as a thin index over the two registries that already exist —
**not** by re-scanning agent source files (the plan's literal suggestion; redundant given
`capability_registry` already captures this at `_register()` time):

```
backend/app/fleet/tool_discovery.py
  def discover_tools(capability: str) -> list[ToolSpec]:
      """Union of .tools across every AgentCapability with this capability tag
      (capability_registry.all()), each looked up in TOOL_MANIFEST for full spec.
      'What tools are available for security-scanning tasks?'"""

  def check_compatibility(tool_name: str, agent_name: str) -> bool:
      """Is tool_name in capability_registry.get(agent_name).tools? If TOOL_MANIFEST
      says high-risk, does the agent's own risk_level (from AGENT_CONTRACT) cover it —
      reuses the exact logic Day 7 already validated in tool_manifest.verify_agent_contract()."""

  def check_availability(tool_name: str) -> bool:
      """Best-effort static check: is tool_name in TOOL_MANIFEST or one of the shared
      top-level tool functions in tools.py? NOT a live handler probe (building a handler
      requires a repo_path and has side effects) — document this limitation explicitly,
      don't overclaim it proves a working handler exists."""

  def register_tool(spec: ToolSpec) -> None:
      """Add a new tool at runtime — appends to an in-process overlay dict, doesn't
      mutate the static TOOL_MANIFEST. 'Plugin adds a tool without restart.'"""
```

`ToolSpec` dataclass: `name`, `description`, `permission_level`, `allowed_risk_levels`,
`handler_path` (best-effort — the module name where the tool's spec/handler lives, derived
from which agent files reference it, not literally introspected).

## Tests

`tests/test_metrics_wiring.py` — the foundational fix: mock `run_agent_graph`'s internals
(or run it for real against a mocked LLM, same pattern every other Day 0-9 test uses), assert
`MetricsCollector` records non-zero `tokens_in`/`tokens_out`/`verification_pct` after a real
run. **This must pass before anything else in Day 10 is meaningful.**

`tests/test_budget_manager.py` — mock over-limit scenario (per the plan's own success
criterion): construct a `RunMetrics` with tokens over `MAX_TOKENS_PER_AGENT_RUN`, assert
`check_run()` raises `BudgetExceeded` with the right dimension; same for daily cumulative
cost; assert normal runs under budget don't raise.

`tests/test_benchmark_manager.py` — seed `MetricsCollector` with known synthetic runs,
assert each of the 7 objectives computes the expected value; test `compare_to_baseline`
correctly flags a regression when a new result is worse than a stored baseline beyond
threshold.

`tests/test_tool_discovery.py` — `discover_tools("security_review")` returns
`security_reviewer`'s tools; `check_compatibility("bash", "quality_auditor")` reflects the
real contract; `register_tool()` makes a new tool immediately discoverable without restart.

## Build order

1. **Metrics wiring fix first** (`base_graph.py`) — verify with a real test before building
   anything else on top of it
2. `tool_discovery.py` (no dependency on the metrics fix — build/test this first if you want
   an early win while thinking through the metrics wiring)
3. `budget_manager.py` (depends on the metrics fix)
4. `benchmark_manager.py` (depends on the metrics fix; new `agent_benchmarks` table +
   migration if going the DB-storage route)
5. Full suite + mypy, update `PROJECT.md`/Control Center, `docs/reports/FLEET_DAY10_TEST_REPORT.md`, commit
