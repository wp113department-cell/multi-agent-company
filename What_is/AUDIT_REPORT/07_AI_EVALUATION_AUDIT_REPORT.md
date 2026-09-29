# Audit 07: Master AI Evaluation Audit

**Spec:** `files/Audit/07_MASTER_AI_EVALUATION_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_07_AI_EVALUATION.json`

## Result

🟡 **YELLOW: the measurement infrastructure is real and now accurate (two defects fixed), but it can't yet produce live quality numbers. No LLM credit means no real runs, no baselines, and a regression gate that is wired but dormant.**

**AI Evaluation score: 72 / 100.** About 25 points of that depend on infrastructure that is real and tested but has **not yet gated anything in production**, because it needs real agent runs. The live checks are listed in `PENDING_TESTS_API_KEYS.md` §L (L4–L7).

## 1. Metrics pipeline integrity (executed)

`evidence/metrics_pipeline_probe.py` drives the **real** `run_agent_graph` (only the Anthropic HTTP call is faked: a tool call, then a submit) and reads `MetricsCollector` afterwards:

```
RunMetrics: status=completed tokens_in=300 tokens_out=60 verification_pct=1.0
  tool read_file     success=True duration_ms=2.81
  tool submit_probe  success=True duration_ms=0.03
result.read_ok (graph-enforced) = True
```

Tokens, per-tool success and duration, verification coverage and status all reach `RunMetrics`. July's "looked wired but measured nothing" bug has not come back.

**Defect found by this probe (AIEVAL-07-001, fixed):** only the main `call_llm` node counted tokens. Five auxiliary LLM calls were invisible: **reflection** (runs on the agent's own Sonnet/Opus model **every turn** with the full conversation), critique, planning (2 calls), replanning, context summarisation and lesson extraction. Proven on the old code: a run with all features on made **8 calls and recorded 2 (25%)**. Budget enforcement (`MAX_TOKENS_PER_AGENT_RUN`, the daily cost budget), `cost_estimate`, and the cost-based benchmark objective all under-counted. Now every call is added to the run totals (Haiku-tier calls are priced at the run's tier: a deliberate over- rather than under-estimate for a cost limit). Test: `tests/test_audit07_aux_llm_token_accounting.py` (fails on the old code, passes on the new).

## 2. Benchmark objectives (verified in `fleet/benchmark_manager.py:183-241`)

| Objective | Computed from | Verdict |
|---|---|---|
| `latency_p50` | real run durations (`MetricsCollector.p50_latency_ms`) | ✅ |
| `tool_accuracy` | real per-tool success flags | ✅ (1.0 when no tool calls, documented) |
| `verification_coverage` | per-run `verification_pct` from `enforce_in_result` keys actually satisfied | ✅ |
| `retry_success` | **only runs with retries > 0** | ✅ as designed |
| `compile_success` | only `run_tests` / `run_linter` calls | ✅ |
| `hallucination_rate` | share of runs where `reflection_node` judged its own output unsatisfactory | ⚠️ **a proxy, not a detector.** It measures the model's self-doubt, not factual error. A confidently wrong agent scores well, and an over-cautious one scores badly. Combined with the separate citation check (invented file/line/symbol references), it is a reasonable signal, not ground truth. |
| `benchmark_score` | weighted by `BENCHMARK_WEIGHT_*` settings | ✅ config-driven, no hardcoded weights |

## 3. Baselines and the regression gate: real but dormant

| Check | Result |
|---|---|
| Baseline loop runs automatically | ✅ `_benchmark_baseline_loop` in the lifespan, `BENCHMARK_BASELINE_INTERVAL_HOURS`, off the event loop (`to_thread`) |
| Never stores a "vacuously perfect" baseline | ✅ skips agents with no real runs |
| Append-only history | ✅ prior baseline flipped to `is_baseline=False`, never deleted |
| `gate_deploy()` in the prompt-deploy path | ✅ `prompt_registry.deploy()` → `gate_deploy()` (`prompt_registry.py:335`); the real caller is the self-improvement APPLY phase, which routes role-prompt edits through propose → deploy (`tools.py:7311-7340`) |
| No baseline → "no regression" | ✅ deliberate; this is why the gate is **dormant today**: no LLM credit → no real runs → no baselines |
| Weakness | Low: the *first* baseline can come from a single run (`by_agent(n=1)`), which is noisy. Recommend a minimum sample size. |

## 4. Eval suite

| Check | Result |
|---|---|
| Coverage | 11 fixed tasks across planning (sprint_planner, business_analyst), review (style, security, performance, tech-debt), design (database_architect, security_architect), coding (bug_fix), docs (user_story_generator) and meta-eval: representative categories |
| Scoring | **deterministic, structural only**: status not blocked, summary present, `verified=True`, expected fields present, story-count bounds. The tasks' `quality_checks` (natural-language rubrics) are read and **ignored** (`eval_runner.py:85`, `noqa: F841`): they need an LLM judge. Reported honestly, not faked. |
| Runs automatically? | **No.** The suite is marked `slow`; `pytest.ini` excludes `slow` and CI never passes `-m slow`. Evals have never gated a merge. Plus CI itself is blocked (audit 06). |
| Live run | **BLOCKED (LLM credit)**: `PENDING_TESTS_API_KEYS.md` L4/L5 |

## 5. Model routing

| Check | Result |
|---|---|
| Tier fit | Opus for architect, decomposer, planner, manager, executive, research, security_architect, rag_engineer, architecture_reviewer (design-heavy). Sonnet for coding and review. Haiku for env_checker and triage. Sensible; no obviously mis-tiered agent. |
| Advisory | Reflection runs on the **agent's own tier** every turn. Moving it to Haiku could cut real cost substantially; measure first (L7). |
| Hot reload | ❌ → ✅ **fixed (AIEVAL-07-002)**: `reload()` had no caller, so edits to `agent_models.json` needed a restart despite the file's own header. Now reloaded on file change (one `stat` per route); a half-saved invalid file keeps the previous table instead of silently rerouting every agent to built-in defaults. Test: `test_audit07_model_router_hot_reload.py`. |
| Explicit route for every agent | ✅ (audit 02) |

## 6. Findings

| ID | Sev | Status | Finding |
|---|---|---|---|
| AIEVAL-07-001 | **High** | FIXED | Auxiliary LLM calls (reflection every turn on the main model, critique, planning, replanning, summarisation, lesson) not counted: budgets and cost saw ~25% of real tokens in a full-feature run |
| AIEVAL-07-002 | Medium | FIXED | Model routing hot reload never triggered; invalid mid-edit file would have reset routing to defaults |
| AIEVAL-07-003 | Medium | BLOCKED (credit) | Eval suite never executed automatically (`slow` excluded everywhere); quality rubrics need an LLM judge |
| AIEVAL-07-004 | Medium | BLOCKED (credit) | Regression gate dormant until real runs create baselines |
| AIEVAL-07-005 | Low | ACCEPTED | `hallucination_rate` is a self-doubt proxy; first baseline may come from a single run |

## Verdict

**READY in code. NOT yet evidence-producing:** a real quality number needs LLM credit (L4–L7).
