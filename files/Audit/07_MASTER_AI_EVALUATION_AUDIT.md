# MASTER AI EVALUATION AUDIT — Eval Suite, Benchmarks, Regression Gates, Hallucination Signals

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.
# This audit is allowed to RUN existing tests/evals (read-only from the
# repo's perspective — it doesn't modify source) to observe real output,
# but must not modify any file to make a test pass.

You are a Principal AI Evaluation Engineer + Principal LLM Safety Engineer.
Audit whether this system can actually measure its own agent quality, not
just produce output.

## PHASE 0 — Orientation

Read in full:
- `backend/tests/evals/` — `tasks.json`, `eval_runner.py`, `test_evals.py`
- `backend/app/fleet/benchmark_manager.py` — the 7 objectives
  (`latency_p50`, `tool_accuracy`, `verification_coverage`,
  `retry_success`, `compile_success`, `hallucination_rate`,
  `benchmark_score`), baseline storage (`agent_benchmarks` table)
- `backend/app/fleet/regression_detector.py` — `RegressionGate`,
  `DeploymentBlocked`, `gate_deploy()`
- `backend/app/fleet/metrics.py` — `RunMetrics`, `MetricsCollector`,
  including the Day 10 fix where `run_span()`'s context-manager return
  value was previously discarded (verify the fix — `_metrics =
  _span.__enter__()` — is still correctly in place and metrics are
  genuinely populated on real runs, not silently empty again)
- `backend/app/agents/base_graph.py` — `reflection_node` and
  `reflection_unsatisfied_count` (the hallucination-rate proxy signal)
- `backend/app/fleet/prompt_registry.py` — version lifecycle +
  `deploy()`'s dependency on `regression_detector.gate_deploy()`

## PHASE 1 — Metrics Pipeline Integrity

- Confirm `RunMetrics` fields are ACTUALLY populated from real
  `run_agent_graph()` executions — trace `record_tokens()`,
  `record_tool()` (with real `duration_ms`), `confidence`, `retries`,
  `verification_pct` from `final_state` all the way from
  `base_graph.py` into `MetricsCollector`. This class of "looked wired but
  measured nothing" bug has occurred before in this project (Day 10's own
  finding) — do not trust that it's fixed just because PROJECT.md says so;
  find the current code and confirm.
- If a live DB/test environment is available, run a small number of real
  or mocked agent invocations and confirm `MetricsCollector.all_runs()`
  actually reflects them afterward.

## PHASE 2 — Benchmark Objective Correctness

For each of the 7 benchmark objectives, verify the actual computation
against real (not assumed) data sources:
- `latency_p50` — computed from real wall-clock run durations?
- `tool_accuracy` — what does this actually measure? Confirm the metric
  isn't a placeholder returning a constant.
- `verification_coverage` — cross-check against `VerificationConfig`'s
  `enforce_in_result` actually being satisfied per run, not just presence
  of a config.
- `retry_success` — confirmed scoped to only retried runs, not all runs
  (a documented design intent — verify in code).
- `compile_success` — confirmed derived specifically from
  `run_tests`/`run_linter` tool_calls, not any arbitrary tool call.
- `hallucination_rate` — this is a PROXY metric via
  `reflection_unsatisfied_count`, not a real hallucination detector. Assess
  honestly: is this proxy reasonable, or could it produce misleadingly
  low/high scores? State the limitation clearly in the report rather than
  treating it as a solved problem.
- `benchmark_score` — confirm the composite is actually config-weighted
  (`BENCHMARK_WEIGHT_*` fields), not hardcoded weights.

## PHASE 3 — Baseline & Regression Gate Audit

- Confirm `store_baseline()` is actually invoked automatically (the
  `_benchmark_baseline_loop()` background loop found missing and added in
  the Days 11-13 gap-closure) — check `main.py`'s lifespan for the loop and
  confirm the interval config (`BENCHMARK_BASELINE_INTERVAL_HOURS`) is
  respected.
- Confirm `store_baseline()` never overwrites an agent's FIRST baseline
  silently in a way that would hide a real regression from ever being
  detected (verify the append-only/history-preserving behavior).
- Confirm `regression_detector.gate_deploy()` is actually called from
  `prompt_registry.deploy()` before any prompt version goes live — trace
  this specific call chain, since PROJECT.md notes `prompt_registry.deploy`
  itself has few/no real callers yet; assess whether that means the
  regression gate is currently dormant infrastructure (not a bug, but a
  real limitation to report) rather than actively protecting production
  today.
- For an agent with NO baseline yet (new agent, or baseline loop hasn't
  run), confirm `gate_deploy()`'s "no baseline = no regression" fallback is
  a deliberate, safe default and not silently permissive in a dangerous
  way.

## PHASE 4 — Eval Suite Audit

- Run (or read closely) `backend/tests/evals/tasks.json` — are the 5 fixed
  eval tasks representative of real agent categories (planning, review,
  analysis) or too narrow?
- Confirm `eval_runner.py`'s scoring logic is deterministic where it claims
  to be, and clearly flagged as LLM-graded where it isn't.
- Confirm the `slow`/`pytest -m slow` marker correctly excludes real-LLM
  eval tests from the default fast suite (per `pytest.ini`), and that this
  doesn't mean evals silently never run in CI — check whether CI ever
  invokes the slow marker, or whether evals are effectively never executed
  automatically (report this as a finding either way, don't just assume
  it's fine).

## PHASE 5 — Model Routing Evaluation

- Cross-check `backend/app/fleet/agent_models.json` model tier assignments
  (Opus/Sonnet/Haiku) against each agent's actual task complexity as
  described in its role file. Flag any obviously mismatched assignment
  (e.g. a complex architecture-design agent routed to Haiku, or a trivial
  read-only-audit agent routed to Opus) as a cost/quality tuning
  opportunity — this is advisory, not a hard defect.
- Confirm `model_router.py`'s hot-reload actually re-reads the JSON file
  rather than caching stale routes indefinitely.

## PHASE 6 — Final Report

1. Metrics pipeline integrity verdict (with evidence trace)
2. Per-objective correctness assessment (including honest limitations of
   the hallucination proxy)
3. Baseline/regression gate real-world activation status (dormant vs.
   active) — be explicit and honest here, this materially affects the
   production-readiness score
4. Eval suite coverage assessment
5. Model routing tuning suggestions (advisory, non-blocking)
6. Prioritized fix list (Critical → Low, file:line)
7. AI Evaluation Layer Production-Readiness score (0-100), with an explicit
   note on how much of this score depends on infrastructure that is real
   but not yet actively gating anything in production

Do not write code. Do not modify files. You may execute existing
`pytest`/eval commands read-only to observe behavior. Evidence or NOT FOUND
only.
