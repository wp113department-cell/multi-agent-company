# 07 — Master AI Evaluation Audit (Metrics, Benchmarks, Regression Gate, Eval Suite, Model Routing)

- **Audit ID:** 07
- **Baseline commit:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530) — **baseline drift, see note**: HEAD advanced twice while the audit series ran (`ecd4905a` "Production audit 12" → `33bbd03c` "Production audit 13", 12:07:59 +0530). Among this audit's cited files, audit 12 touched `api/fleet_dashboard.py` (prompt history/rollback routes) and audit 13 touched `api/specialized_agents.py` (+10) and `main.py` (+36, inserted far below every cited line). All citations below were taken from on-disk content AFTER both commits and are stable on the current worktree.
- **Run date:** 2026-10-02
- **Method:** read-only static verification (full reads of the eval suite, benchmark manager, regression detector, metrics collector, model router, prompt registry; targeted traces of `run_agent_graph` instrumentation, gate call chains, and lifespan loop registration) plus one live read-only test run: `pytest tests/evals/test_evals.py tests/test_metrics_wiring.py tests/test_benchmark_manager.py tests/test_benchmark_baseline_loop.py tests/test_regression_detector.py tests/test_gap50_prompt_registry_wiring.py tests/test_prompt_registry.py` → **55 passed, 4 deselected (slow/LLM), 0 failed, 21.36s**. No project file was modified (`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`).
- **Scope per brief:** metrics pipeline integrity, per-objective correctness of the 7 benchmark objectives, baseline/regression-gate activation status (dormant vs active), eval suite coverage, model routing; 0–100 score with an explicit caveat on how much of it depends on real-but-not-yet-gating infrastructure.
- **Brief delta (not a finding):** the brief describes "the 5 fixed eval tasks"; `backend/tests/evals/tasks.json` on disk now contains **11 tasks** (`eval_001…eval_011`) covering planning, business analysis, style/performance/security review, tech-debt, DB design, user stories, bug-fix and self-evaluation. The suite was expanded after the brief was written; this audit assesses the 11-task reality.

---

## 1. Executive Summary

The AI-evaluation layer is **real, wired, and mostly honest**: `RunMetrics` is genuinely populated from real `run_agent_graph()` executions (the Day-10 `_metrics = _span.__enter__()` fix is still in place at `base_graph.py:3813`, and a live mocked-LLM test run proves values flow into `MetricsCollector`); all 7 benchmark objectives are computed from real recorded data with **config-driven** weights summing to exactly 1.00; the baseline-population loop **auto-runs** (leader-elected lifespan task, 24h default, first-baseline-only); and the regression gate is **active in production** — not dormant — with real callers in three paths (role-prompt `deploy()`, the Manager's subtask gate, and an automatic prompt auto-rollback loop) plus a labeled CI job. Model routing genuinely hot-reloads.

**One Medium finding:** `eval_runner.py` loads each task's `quality_checks` but **never evaluates them** (`# noqa: F841` — the only reference in the codebase), so for the 6 tasks with empty `expected_fields` (eval_006…eval_011) scoring collapses to three generic checks, and for all 11 tasks the declared quality criteria are documentation, not measurement — eval scores overstate conformance to the tasks file's own contract.

**Four Low findings:** real-LLM evals are **never executed automatically** (no `-m slow` anywhere in CI); the gate ecosystem is **fail-open when the in-process metrics window is empty** (a zero-run "current" window scores a perfect 1.0, so a cold process can never be blocked); the `hallucination_rate` objective consumes only the self-declared reflection proxy while the stronger independent `citation_hallucinations` signal (#443) is recorded but unused by the benchmark; and agent-count docstrings have drifted (60/68/72 claimed vs 65 registry entries / 86 routing-table entries).

**AI Evaluation Layer Production-Readiness: 85 / 100 — Verdict: READY.** Explicit caveat: roughly 10–15 points of this score rest on the distinction between "the machinery is real and invoked" and "the machinery automatically gates quality in CI" — the metrics/benchmark/gate machinery is real and invoked in production paths, but the LLM eval suite itself never runs automatically, and gates fail open whenever the checking process has no recent runs of the target agent (details in §4 and §5).

---

## 2. Metrics Pipeline Integrity — **VERIFIED** (evidence trace)

The class of bug the brief worries about ("looked wired but measured nothing", Day 10's own finding) is **absent**. Full trace, chokepoint by chokepoint:

| Stage | Code evidence | Status |
|---|---|---|
| Span opens with the real `RunMetrics` handle | `base_graph.py:3805-3813` — `_span = run_span(role_name, task_id="", trace_id=tid)` then `_metrics = _span.__enter__()`; the comment at 3806-3808 explicitly warns the context manager and the metrics object are different objects (the exact Day-10 failure) | Fix present |
| Run registered in collector | `metrics.py:622-649` `run_span()` → `collector.start_run(...)` appends to ring + `_index` before yield | Real |
| Tokens + cost | `base_graph.py:4160-4164` copies `final_state` totals into `_metrics.record_tokens(...)`; `_recompute_cost()` (metrics.py:197-214) prices at the run's own routed tier via `model_router.route(agent_name).tier` + `cost_rates_for_tier` | Real |
| Tool calls with real duration/success | `base_graph.py:2842-2861` — `_duration_ms = (time.monotonic() - _t0) * 1000`; `_ok` derived from the real handler output (not prefixed `[ERROR]`/`[POLICY`); `_m.record_tool(name, _ok, duration, err)` | Real |
| Confidence / retries / reflection / citations | `base_graph.py:4165-4172` — `confidence`, `retry_count`, `reflection_unsatisfied_count`, `citation_hallucination_count` all copied from `final_state` | Real |
| Verification % | `base_graph.py:4173-4176` — fraction of True booleans in `final_state["verification"]`; that dict is grounded in tool evidence: `set_by` sets True only on a real successful tool call (with `command_patterns` match, 2863-2873), `reset_by` clears (2875-2877), and at submit the `enforce_in_result` contract **overrides** the model's claimed result field with the actually-verified value (2894-2906) | Real |
| Self-calibration check | `base_graph.py:4180-4186` → `check_confidence_calibration()` (metrics.py:667-693), thresholds config-driven | Real |
| Span close / timing | `base_graph.py:4192-4193` `_span.__exit__(None,None,None)` (completed); exception path `base_graph.py:4438-4442` `__exit__(type(exc), exc, traceback)` → status failed; `execution_time_ms` set from `time.monotonic()` in both branches (metrics.py:642, 646) | Real |
| Durable mirror | `base_graph.py:4346-4359` — `finish_agent_run_sync(..., tool_accuracy, verification_pct, confidence, retries, citation_hallucination_count)` writes the same values to the `agent_runs` row | Real |
| Live proof | Ran `tests/test_metrics_wiring.py` (read-only): `test_real_run_populates_metrics_collector` PASSED — a real (mocked-LLM) `run_agent_graph` run asserts `m.tokens_in == final_state["tokens_in"]`, `cost_estimate_usd > 0`, `verification_pct == 0.5`; `test_tool_calls_are_recorded_for_benchmark_tool_accuracy` PASSED — `record_tool` populates `tool_calls` and `avg_tool_accuracy()==1.0` | Passed |

**Verdict: genuinely populated on real runs — not silently empty.** One inherent limitation (documented, not a defect): `MetricsCollector` is a per-process 1000-entry ring, explicitly described by the code itself as "in-process-only, ephemeral … reset on restart, invisible across processes" (`base_graph.py:3818-3827`) — this is the root of EVAL-07-103 below.

## 3. Per-Objective Correctness (all 7, `benchmark_manager.py`)

| Objective | What it actually computes | Real source | Verdict |
|---|---|---|---|
| `latency_p50` | Upper-middle element of sorted positive `execution_time_ms` values (`metrics.py:310-319`); normalized: 1.0 at/below `benchmark_latency_target_ms` (30,000ms), 0.0 at 2× (`benchmark_manager.py:172-181`) | Real wall-clock from `run_span` | Real; integer-index p50 approximation (fine) |
| `tool_accuracy` | Mean over runs (with ≥1 tool call) of per-run `successes/total` from `record_tool`; `None → 1.0` when no tool calls (documented benign default, 190-193) | Real per-call success flags | Real, not a placeholder constant |
| `verification_coverage` | Mean of per-run `verification_pct` (195-197); per-run grounded by `set_by`/`reset_by` tool evidence + `enforce_in_result` override at submit — i.e. it measures checks that actually ran, not config presence | Real verification dict | Real |
| `retry_success` | Scoped to retried runs only: `[m for m in runs if m.retries > 0]`, else vacuous 1.0 (199-204) | Real retry counts | Matches documented design intent |
| `compile_success` | Only `run_tests`/`run_linter` tool calls (`_COMPILE_TOOLS` at line 25; filter at 206-213) | Real tool calls | Correctly scoped |
| `hallucination_rate` | Fraction of runs where `reflection_unsatisfied > 0` (218-222) — **proxy**, honestly labeled in-code ("Approximation, not ground truth") | Self-judgment from `reflection_node` | Reasonable-but-limited proxy — see limitations below |
| `benchmark_score` | Config-weighted sum: 0.15·latency + 0.20·tool + 0.20·verification + 0.15·retry + 0.15·compile + 0.15·(1−hallucination); weights from `BENCHMARK_WEIGHT_*` (`config.py:1343-1368`), summing to exactly 1.00 | Real objectives | **Config-driven, not hardcoded** |

**Honest hallucination-proxy limitations (as the brief requires, stated not solved):**
1. It increments only when the reflection LLM explicitly answers `{"satisfied": false}` — a JSON parse failure or missing key defaults to **satisfied** (`base_graph.py:2038-2042`), so malformed/refused output **under-counts** hallucinations.
2. It is the model's **own opinion of its own tool output** — self-report bias, not an independent fact check.
3. It conflates "missed edge cases / not production-ready" (the reflection prompt's questions) with factual hallucination.
4. A stronger, independent per-claim signal already exists and is recorded — `citation_hallucinations` (#443's `verify_file_line_citations`, real file:line/function existence checks at `base_graph.py:2908+`, stored at 4170-4172 and mirrored to `agent_runs`) — but `benchmark_manager` never consumes it (EVAL-07-104).

## 4. Baseline & Regression Gate — Activation Status: **ACTIVE** (not dormant)

**Baseline population loop is real and automatic:**
- `_benchmark_baseline_loop` (`main.py:394-438`), registered in the lifespan as a **leader-elected** background task (`main.py:1706-1710`, `_run_as_leader("loop:benchmark_baseline", ...)`); interval `BENCHMARK_BASELINE_INTERVAL_HOURS` default **24h**, 0 disables (`config.py:1373-1376`); first iteration sleeps the interval (411-412).
- **Never overwrites an existing baseline:** the loop only stores when `report.baseline_score is None` (`main.py:425`) and skips agents with zero in-process runs entirely (`collector.by_agent(cap.name, n=1)` guard, 422-423). `store_baseline()` itself flips any prior baseline row to `is_baseline=False` and inserts a new row — history is append-only (`benchmark_manager.py:249-254`, `models.py:900-918`). Verified live: `test_baseline_loop_stores_baseline_for_agent_with_real_runs`, `test_baseline_loop_skips_agent_with_no_runs`, `test_baseline_loop_does_not_overwrite_existing_baseline`, `test_baseline_loop_disabled_when_interval_zero` — all PASSED.

**The deploy gate has real callers (the brief's "few/no real callers" premise is outdated):**
1. **Role-prompt deploys:** `PromptRegistry.deploy()` calls `get_regression_detector().gate_deploy(row.role_name)` before writing anything and before the status transition (`prompt_registry.py:335-337`). Real caller: `_propose_and_deploy_role_prompt` (`tools.py:7316-7352`) — the shared APPLY-phase write/edit handler for `roles/*.md` used by all 4 write-capable fleet-enhancement agents (`make_fleet_apply_handlers`, 7355-7415). On `DeploymentBlocked` it returns a `[BLOCKED]` message and performs **no disk write**. Verified live: `test_deploy_is_blocked_by_regression_detector`, `test_gap50…surfaces_blocked_message_and_no_write`, and all 4 apply-phase callers parametrized tests — PASSED.
2. **Manager subtask gate (T2-B5):** `manager.py`'s advisory quality gates include a 4th, free regression gate — `_run_regression` → `check_agent(agent_name)` for the actual dev agent (e.g. `backend_dev`) of each subtask (`manager.py:1261-1279`), executed off-loop via `asyncio.to_thread` (explicitly noted at 1262-1265); a blocked gate contributes a real block reason (`manager.py:1382-1389`) and a persisted performance advisory finding (1403-1424).
3. **Automatic prompt auto-rollback loop:** every `PROMPT_AUTO_ROLLBACK_INTERVAL_HOURS` (default 4h; 24h per-role cooldown, `config.py:1539-1553`), `_run_prompt_auto_rollback_once` (registered leader-elected at `main.py:1744-1748`) runs `check_fleet()`, and for any regressed role with a deployed prompt version **automatically rolls the prompt back** (`main.py:546-612`), with SystemSetting-backed cooldown and a `health_updated` event. An operator-invoked rollback route also exists (`api/fleet_dashboard.py:301-318`, approver-gated).
4. **CI:** the labeled "Regression gate" job (`.github/workflows/ci.yml:85-106`) runs `test_regression_detector.py` by name, with its own honest documented limitation (ephemeral CI Postgres has no production baseline history, 97-105).
5. **Consumer:** `prompts_score.py:52-102` computes a repo-scoped prompt pass-rate via `check_agent()`, correctly excluding no-baseline roles instead of counting them as passes.

**No-baseline fallback:** `build_regression_report` returns `is_regression=False` when no baseline exists (`benchmark_manager.py:68-76`) — a **deliberate, documented** "no data yet is neutral" default (also in `main.py:396-399`), paired with the population loop above so real baselines appear after the first 24h cycle for any agent with real runs. Not silently permissive in a dangerous way: the gate governs one write path (role prompts) plus advisory subtask findings, and the fallback is explicitly reasoned in-code.

### EVAL-07-103 — Regression gate fails open when the in-process current window is empty
- **Severity:** Low · **File:** `backend/app/fleet/benchmark_manager.py` · **Confidence:** High
- **Finding:** `compare_to_baseline()` computes "current" from the caller process's in-memory ring (`run_benchmark` → `collector.by_agent(agent, 20)`). With **zero runs** (fresh process/restart/deploy, or agent ran in a different worker), every no-data branch resolves to its benign default — latency 1.0, tool 1.0, verification 1.0, retry 1.0, compile 1.0, hallucination 0.0 — so `benchmark_score = 1.0` (weights sum to exactly 1.00) and the diff against any stored baseline can never flag a regression. "No current data" is therefore treated as "perfect current behavior" rather than "unknown". Combined with the (deliberate) no-baseline fallback, all gate paths pass unless the **checking process itself** holds ≥1 recent run of the target agent AND the drop exceeds the 10% threshold. `MetricsCollector` is per-process and reset on restart, and the leader-election wrapper means only one process's ring feeds the loops.
- **Evidence:** `benchmark_manager.py:172-181` (None→1.0 latency), `190-193` (tool None→1.0), `195-204` (empty runs→1.0), `218-222` (empty→0.0); live: `test_run_benchmark_with_no_runs_uses_benign_defaults` PASSED; ring semantics: `metrics.py:271-308` + `base_graph.py:3818-3827` ("reset on restart, invisible across processes"); loop guard `main.py:422-423`.
- **Production impact:** after a restart or on a worker that hasn't run the target agent, the regression gate provides no protection (always passes) even when a real fleet regression exists — protection is provisional on in-process history, not a durable guarantee. Fail-open only; no false blocking.
- **Recommendation:** distinguish "no current runs" from "perfect score" in `_compute_objectives`/`compare_to_baseline` (e.g. return an explicit `insufficient_data` state that callers treat as neutral/skip instead of a pass, or compute the current window from the durable `agent_runs`/`AgentBenchmark` history rather than the ring). Effort: M.

## 5. Eval Suite Coverage (Phase 4)

- **11 tasks** (`tasks.json`): `sprint_planner`, `business_analyst`, `style_reviewer`, `tech_debt_agent`, `performance_reviewer` (with `expected_fields` + story-count checks), and `bug_fix`, `security_reviewer`, `security_architect`, `database_architect`, `user_story_generator`, `evaluation_agent` (findings-style, empty `expected_fields`). Categories cover planning, review, analysis, fix and self-evaluation — broader than the brief's "5 tasks" expectation; no obvious category gap.
- **Scoring is purely deterministic** (string containment of `expected_fields` in the serialized result, summary length, `verified` flag, story count) — there is **no LLM-graded scoring anywhere**, so no mislabeled "LLM grading" exists. Dispatch goes through the real 65-entry registry via `_load_agent_fn` (`eval_runner.py:52-56`), and fast tests verify every eval agent exists in `_REGISTRY` (`test_all_agent_names_in_registry` PASSED).
- **Slow-marker behavior verified live:** default run collected 59 items, **4 deselected** (the `@pytest.mark.slow` `TestAgentEvals` class) — the marker correctly keeps real-LLM evals out of the fast suite (`pytest.ini:6-8`). But CI **never invokes the slow marker or the eval runner** (grep across `.github/workflows/`: zero matches for `slow`/`eval_runner`/`tests/evals`; `ci.yml` runs only `pytest tests/` with the same `-m "not slow"` addopts) — so the entire LLM eval suite only runs by hand (EVAL-07-102).

### EVAL-07-101 — `eval_runner` declares `quality_checks` but never evaluates them
- **Severity:** Medium · **File:** `backend/tests/evals/eval_runner.py` · **Confidence:** High
- **Finding:** `_score_result()` loads each task's `quality_checks` into a local and immediately abandons it — `quality_checks: list[str] = task.get("quality_checks", [])  # noqa: F841` (line 85) is the **only** reference to `quality_checks` in the entire codebase (grep over `backend/`). Scoring therefore never enforces any declared quality criterion (e.g. "findings should reference real files under `backend/app/api/`", "diagnosis should identify the missing None check"). For eval_006…eval_011, which define `expected_fields: []`, the only executed checks are three generic ones (not `blocked`, summary > 10 chars, `verified` flag) — the declared checks were the substantive criteria and they are dead strings. The suite's own scores (and the slow tests' `>= 0.5/0.6` thresholds) overstate conformance to `tasks.json`'s contract; a real quality regression those checks were written to catch would pass silently. The `expected_fields` check is also substring containment in the serialized JSON, so a field name appearing anywhere (e.g. inside an error string) passes.
- **Evidence:** `eval_runner.py:85` (`# noqa: F841`), 92-139 (executed checks only); `tasks.json` `quality_checks` blocks (`eval_001` line 10-14 … `eval_011`); no test asserts quality-check execution (`test_evals.py` fast tests validate only file shape/registry).
- **Production impact:** evaluation-validity, not runtime: the eval score is a weaker measurement than its own definition claims, so it can green-light agents whose outputs miss the documented quality bar. No production behavior is affected (the suite is not a deploy gate today).
- **Recommendation:** implement the checks (JSON-aware, per-task predicates) or rename/strip the field so the file stops promising measurements that never happen; add a fast unit test for `_score_result` itself (currently untested). Effort: M.

### EVAL-07-102 — Real-LLM eval suite never runs automatically (no CI invocation)
- **Severity:** Low · **File:** `.github/workflows/ci.yml`, `backend/pytest.ini` · **Confidence:** High
- **Finding:** `pytest.ini:8` excludes `slow` by default, and **no workflow anywhere invokes `-m slow`, `tests/evals/test_evals.py -m slow`, or `python -m tests.evals.eval_runner`** (grep of `.github/workflows/`: zero matches; `ci.yml:83` runs the default suite only). The 11-task LLM eval suite therefore executes only when a human manually sets `USE_GROQ=true GROQ_API_KEY=…` and runs pytest/CLI — agent prompt changes (which deploy through the regression-gated registry) are never eval-gated automatically.
- **Evidence:** grep `slow|eval_runner|tests/evals` in `.github/` → 0 matches; local run shows the 4 eval tests deselected; `eval_runner.py:6-16` documents manual invocation only.
- **Production impact:** drift in agent output quality is caught only by manual runs; CI green does not mean evals pass. Bounded (no runtime impact).
- **Recommendation:** add a scheduled (nightly) workflow running the slow eval suite or `eval_runner` with the Groq key (initially non-blocking/report-only, matching the tech-debt scan's posture at `ci.yml:108-121`). Effort: S.

### EVAL-07-104 — `hallucination_rate` objective ignores the stronger `citation_hallucinations` signal
- **Severity:** Low (advisory) · **File:** `backend/app/fleet/benchmark_manager.py` · **Confidence:** High
- **Finding:** the composite consumes only the self-declared reflection proxy (`m.reflection_unsatisfied > 0`, lines 218-222) while `RunMetrics.citation_hallucinations` — a per-claim, code-checked, independently verified signal (#443; recorded at `base_graph.py:4170-4172`, mirrored to `agent_runs` at 4356-4359) — is never read by any objective. The reflect-proxy also under-counts on JSON parse failure (defaults to satisfied, `base_graph.py:2038-2042`).
- **Evidence:** `benchmark_manager.py:215-222`; `metrics.py:137-145` (field + rationale); grep shows no `citation_hallucinations` use in `fleet/benchmark_manager.py`.
- **Production impact:** the objective overestimates hallucination-freedom exactly in the cases the model is least reliable at self-reporting; benchmark_score's 0.15 hallucination weight is the most proxy-dependent term.
- **Recommendation:** add `citation_hallucinations` to the composite (or as its own objective, e.g. runs-with-failed-citations rate) once baseline volume exists; keep the reflection proxy as a secondary. Effort: S.

### EVAL-07-105 — Agent-count docstrings drifted across the eval/routing files
- **Severity:** Low · **File:** `backend/app/fleet/agent_models.json`, `backend/app/fleet/model_router.py`, `backend/tests/evals/eval_runner.py` · **Confidence:** High
- **Finding:** three different counts claim authority over the same concept: `agent_models.json:2` says "for all 72 Gridiron agents" (the file actually contains **86** explicit agent entries); `model_router.py:1` says "all 68 Gridiron agents"; `eval_runner.py:41-44` says the registry has "60 entries" (actual `_REGISTRY` = **65**, verified by importing it). Doc-only; no routing behavior depends on the counts.
- **Evidence:** live count via interpreter (`len(_REGISTRY)` = 65; JSON entries = 86, of which 75 sonnet / 9 opus / 2 haiku + DEFAULT); the three doc lines above.
- **Production impact:** operators directing model changes by these headers get inconsistent signals about the fleet size; no functional effect.
- **Recommendation:** state one authoritative count source (the registry) or drop hard numbers from headers; refresh all three together. Effort: S.

## 6. Model Routing (Phase 5 — advisory)

- **Hot-reload is real:** `ModelRouter._reload_if_changed` (`model_router.py:212-244`) stats `agent_models.json` on **every `route()` call** and reloads when mtime changes; a file caught mid-edit (invalid JSON) **keeps the previous table** instead of dropping to built-in defaults (231-242). `route()` also checks in-memory overrides (temporary agents) before the static table (246-253). Not a stale-cache.
- **Current tiers:** 75 sonnet / 9 opus (`architect`, `architecture_reviewer`, `decomposer`, `executive`, `manager`, `planner`, `rag_engineer_agent`, `research`, `security_architect`) / 2 haiku (`env_checker_agent`, `groq_adapter`); `DEFAULT` = `claude-sonnet-5`. No obviously wrong-direction assignment found (no complex design agent on haiku; no trivial agent on opus).
- **Advisory cost/quality tuning candidates (non-blocking, not findings):** read-mostly/short-output agents currently on sonnet are the clearest haiku candidates — `changelog_agent`, `readme_agent`, `release_notes_agent`, `cleanup_agent`, `accessibility_agent`, `docs`; conversely `security_reviewer` (whose findings can block in the Manager gate) is sonnet while its sibling `security_architect` is opus — a deliberate but worth-revisiting asymmetry; `sprint_planner` (planning-adjacent) sits one tier below `planner` (opus) — revisit only if sprint-plan quality metrics justify it.

## 7. Prioritized Fix List

| # | ID | Sev | Fix | File:line | Effort |
|---|---|---|---|---|---|
| 1 | EVAL-07-101 | Medium | Enforce (or strip) `quality_checks`; add a `_score_result` unit test | `eval_runner.py:85` (+ `tasks.json`) | M |
| 2 | EVAL-07-103 | Low | Treat empty current window as `insufficient_data`, not perfect 1.0 (or aggregate current from durable history) | `benchmark_manager.py:172-244` | M |
| 3 | EVAL-07-102 | Low | Scheduled nightly slow-eval workflow (report-only first) | `.github/workflows/ci.yml` | S |
| 4 | EVAL-07-104 | Low | Fold `citation_hallucinations` into the hallucination objective | `benchmark_manager.py:215-222` | S |
| 5 | EVAL-07-105 | Low | Reconcile agent-count docstrings (65 registry / 86 JSON entries) | `agent_models.json:2`, `model_router.py:1`, `eval_runner.py:41-44` | S |

## 8. Score & Verdict

**AI Evaluation Layer Production-Readiness: 85 / 100 — READY.**

- Genuinely-verified core: metrics population (live-proven), 7 config-weighted objectives on real data, auto baseline loop (leader-elected, 24h, first-baseline-only, append-only history), and a regression gate with **three real production call paths + auto-rollback + CI job** — the layer is not dormant infrastructure.
- Deductions: the eval suite's declared quality checks are unenforced (Medium) and the suite never runs automatically; the gate ecosystem is fail-open without in-process run history; the hallucination term under-uses an available independent signal.
- Explicit caveat (as requested): the "gating" portion of this score is real but **conditional** — prompt deploys and Manager subtask findings are genuinely blocked when a measured regression exists, but protection requires the checking process to hold recent runs of the target agent, and no CI/scheduled system evaluates agent-output quality end-to-end. If the eval suite were made automatic and the gate's empty-window semantics fixed, this layer would score in the low 90s.
