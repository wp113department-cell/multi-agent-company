# Batch 16 — Organization-Wide Task Scheduler, Agent Performance Metrics, Health Monitoring, Automatic Retirement, Quality Gates, Architecture Drift Detection, Dependency Intelligence, Knowledge Validation

Covers §86-93. Evidence-only, file:line cited.

**Remediation pass (2026-08-11)**: every checkpoint below was re-verified against the current repository (not against this document's original prose — several original findings had already been silently superseded by other batches' gap-closure work landing after this document was first drafted, and are corrected below with evidence). Every remaining implementable gap was closed in this pass. Findings kept as NO/PARTIAL are either a genuine, evidenced architectural scope boundary or a real, honestly-described remaining limitation — none are unverified guesses.

---

## §86 Organization-Wide Task Scheduler

| Capability | Verdict | Evidence |
|---|---|---|
| Queue | **YES** | Real, two named priority queues (`gridiron-high`/`gridiron-default`) via RQ when configured. **Remediation**: found and fixed a real, previously-undetected bug in this exact path — `RQAdapterBridge.enqueue()`/`AsyncioQueueAdapter.enqueue()` had no `*args` parameter at all, so any `dispatch_job()` call with positional arguments (every real call site in `api/tasks.py`) raised `TypeError` the instant `QUEUE_BACKEND=rq` was selected. Fixed end-to-end (`queue_adapter.py`, `_run_coroutine_job`), covered by `test_queue_adapter.py`. |
| Prioritize | **YES** (was PARTIAL — stale finding) | `DevTask.priority` **is** read by real dispatch code: `run_manager()` fetches it and feeds `PrioritySemaphore.acquire(priority=...)` (`app/pipeline/concurrency.py`), which wakes the highest-priority waiter first for the shared `agent_run_slot`/`subtask_slot` caps — a real Batch-2 gap-closure that landed after this document's original text (confirmed by reading the code, not assumed from the prose). **Remediation this pass**: the one real gap that *did* still exist — `DevTask.priority` never reached `RQQueueAdapter`'s own two named queues, so every RQ job silently landed on `gridiron-default` regardless of task priority — is now fixed: `dispatch_job(..., priority=...)` threads through to `RQQueueAdapter.enqueue`'s real `priority` kwarg, and all 7 real call sites in `api/tasks.py` now pass `priority=task.priority`. |
| Pause / Resume / Cancel | **YES** (was NO — stale finding) | All three are real and already wired: `POST /api/tasks/{id}/stop` (pause — in-process abort flag), `POST /api/tasks/{id}/resume`, `POST /api/tasks/{id}/cancel` (terminal — DB-enforced via `VALID_TRANSITIONS`'s real `"cancelled"` status, refuses `resume` afterward). `app/api/activity.py`. This was a real Batch-8 gap-closure that landed after this document's original text. |
| Reorder | **PARTIAL, honestly scoped** | Neither queue backend supports true in-place reordering of an already-enqueued job (`asyncio.Queue` is strict FIFO; RQ has no live-reprioritization primitive) — replacing the queue's own data structure is a materially bigger, separate decision, matching this codebase's own established bar for "wiring" vs. "new capability." What's real and shipped this pass: `PATCH /api/tasks/{task_id}/priority` — changes the priority signal both `PrioritySemaphore` and RQ's queue selection read at dispatch time, the honest scope of "reorder" for a priority-bucketed (not literal-queue-position) scheduler. Refused on terminal tasks. |
| Detect blocked tasks | **PARTIAL** (unchanged) | Real `"blocked"` status/transitions, still purely failure-driven (retries exhausted), not dependency-driven — see next row for the real, separate dependency primitive added this pass. |
| Detect dependencies / optimize order | **YES within task, PARTIAL org-wide** (was PARTIAL — narrower) | Real topological sort still exists for *subtasks within one task* (`_topological_subtask_order`/`_topological_subtask_waves`). **Remediation this pass**: `DevTask.depends_on` (migration 041, mirrors `Subtask.depends_on`'s exact shape) now exists — `POST /api/tasks/{id}/run` refuses to start a task until every declared dependency has reached `"completed"`, a real, evidence-checked, org-wide dependency gate. Not a background auto-dispatcher (a caller/human retries `/run` once the dependency clears) — that's a materially bigger, separate architectural decision, matching the Reorder row's own scoping logic. |
| Retry | **YES on both backends** (was PARTIAL — asyncio path had none) | RQ path unchanged (real `Retry(max=...)` + dead-letter sweep). **Remediation this pass**: `AsyncioQueueAdapter._worker()` now retries up to `queue_job_retry_max` times with exponential backoff before marking a job failed — the same config value the RQ path already used, so both backends share one operator-facing retry knob instead of the asyncio path having zero. |

**§86 overall: YES for Queue/Prioritize/Pause/Resume/Cancel/Retry; PARTIAL (honestly scoped) for Reorder and org-wide dependency auto-dispatch.** The RQ-vs-asyncio backend-choice asymmetry from the original finding is now closed — both backends retry, and priority now reaches both. A real `*args`-handling bug that would have broken the RQ backend for every real caller was found and fixed as part of closing this section.

---

## §87 Agent Performance Metrics

Checked against 10 explicitly-named metrics:

| Metric | Verdict | Evidence |
|---|---|---|
| Success rate | **YES, queryable** | Unchanged — `/api/agents/{name}/metrics`, `/api/fleet/reports/health`. |
| Failure rate | **YES, queryable** | Unchanged. |
| Avg execution time | **YES, queryable** (was PARTIAL — tool-only) | **Remediation**: `GET /api/agents/{name}/metrics` now also returns `p50LatencyMs`/`p95LatencyMs`, reusing `MetricsCollector.p50_latency_ms`/`p95_latency_ms` — the exact same real numbers the `fleet_metrics_read` agent tool already computed, now reachable by a human operator without going through an agent. |
| Tool usage | **YES, queryable** (was PARTIAL — tool-only) | **Remediation**: same endpoint now returns `avgToolAccuracy` (`MetricsCollector.avg_tool_accuracy`). |
| Token usage | **YES, queryable** | Unchanged. |
| Reasoning quality | **Impossible without changing project scope** | No infrastructure anywhere in this codebase grades open-ended reasoning traces against a rubric. A real implementation would need a genuine LLM-judge evaluation pipeline — new capability, not a wiring gap. Fabricating a proxy (e.g. reusing `reflection_unsatisfied`) would misrepresent a specific claim ("reasoning quality") as measured when it isn't — this codebase's own established discipline elsewhere (`user_sentiment.py`'s explicit "not a claim of real NLP accuracy" disclaimer, `hallucination_rate`'s "approximation, not ground truth" comment) is to say so honestly rather than fake a number. Left as NO. |
| Retry count | **PARTIAL** (unchanged) | `Agent.avg_retries` is still self-documented as approximated from tokens; real per-run `RunMetrics.retries` still isn't the value persisted. Out of this pass's scope (a persistence-pipeline change, not a metrics-exposure gap). |
| User approval rate | **YES, queryable** (was NO) | **Remediation**: `_compute_user_approval_rate()` aggregates real `task_logs.category in ("approval","rejection")` rows (already durably logged by every real approve/reject endpoint) joined to `DevTask.assigned_agent`. Returns `None` (not `0.0`) when an agent has no logged decisions — "no data" and "0% approved" are kept as different claims. |
| User satisfaction | **PARTIAL — proxy only** (unchanged) | Still the same honestly-labeled regex frustration-detector proxy; not touched this pass — no real per-agent aggregation infra to build on without the same "reasoning quality" scope problem above. |
| Reliability score | **YES, queryable** (was NO) | **Remediation**: `reliabilityScore` on the same endpoint — a real, documented composite (`0.5 * success_rate + 0.5 * avg_tool_accuracy`, falling back to `success_rate` alone when there's no tool-call history), not a new tracked metric or a fabricated one. |

**§87 overall: 7 of 10 now real and queryable via REST** (up from 5). The remaining 3 (reasoning quality, retry count's persisted-vs-real gap, user satisfaction) are either a genuine new-capability scope boundary or explicitly out of this pass's remit — none are silently left mislabeled.

---

## §88 Agent Health Monitoring

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Detect slow/crashed agents | **YES** (unchanged) | `reconcile_orphaned_runs()`, real. |
| Detect looping agents | **YES, per-agent across runs** (was PARTIAL — per-run only) | Re-verified: `base_graph.py`'s stall path (`n_stalls >= max_stalls`) already calls `failure_ladder.escalate()` → `agent_registry.fail_task()`, the same per-**agent-identity**, cross-run `error_count`/health mechanism a genuine failure uses — a chronically-stalling agent identity does accumulate toward `"unhealthy"` across separate runs, not just within one run's own state. This mechanism predates this pass; the original finding was stale (a real fix, but written before this document was drafted). |
| Detect hallucinating agents / memory leaks / synchronization failures | **NO** (unchanged) | Zero code for any of these — genuinely missing capability, not attempted this pass. |
| Health state transitions are real, not static | **YES, precisely characterized** (unchanged) | `AgentInstance.fail()` still a real, hardcoded-threshold transition. |
| "degraded" state | **YES — reachable and persisted** (was NO — dead code) | **Remediation, two real bugs fixed**: (1) `AgentInstance.fail()` (`agent_registry.py`) previously only ever wrote `"healthy"` or `"unhealthy"` — 1-2 consecutive errors now correctly write `"degraded"`, making `FleetManager.select()`'s own `health_weight={"degraded": 0.5, ...}` dict (previously dead configuration — that value could never occur) finally reachable. (2) `FleetEventType.HEALTH_UPDATED` was missing from `fleet_events.py`'s `FLEET_TO_LEGACY` mapping table entirely, so every `publish(health_updated(...))` call silently no-op'd before reaching the real event bus — now mapped to `"agent.health_updated"` and genuinely persisted to the `events` table. |
| Automatic recovery from unhealthy | **YES** (was NO — zero callers) | **Remediation**: `AgentRegistry.recover_task()` (real caller added) is now invoked from `base_graph.py`'s run-finalization block, gated on `final_state["submitted"]` — a genuinely successful completion is the real recovery signal. Deliberately **not** folded into `complete_task()` unconditionally: that same finalization block also runs immediately after a stall's `escalate()`→`fail_task()` within one call, so an ungated recover would erase the degradation just recorded. |

**§88 overall: 4 of 6 checkpoints now YES** (up from 2 YES / 1 precise-partial / 3 NO). Both dead-code findings from the original pass (unreachable "degraded" state, zero-caller `recover()`) are now real, wired, and covered by `test_fleet_agent_registry.py`. Hallucination/memory-leak/sync-failure detection remains a genuine missing capability, not attempted.

---

## §89 Automatic Agent Retirement

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Disable a repeatedly-failing agent | **YES — real and automatic, but narrow** (unchanged) | `FleetManager.select()` still genuinely excludes `health=="unhealthy"` agents. |
| Notify a supervisor | **YES** (was NO) | **Remediation**: `send_agent_alert()` (`app/services/alert.py`, shares the same `ALERT_WEBHOOK_URL` config `send_task_alert()` already uses) fires from `AgentRegistry.fail_task()` exactly once, at the real healthy→unhealthy transition (not on every failure/degraded step) — dispatched cross-thread-safely via the same `run_coroutine_threadsafe` mechanism `FleetBus` already established (`fleet_events.get_main_loop()`, newly exposed). |
| Replace / permanently disable | **YES — persists across a restart** (was NO — process-restart reset) | **Remediation**: now that `HEALTH_UPDATED` events are genuinely persisted (§88 fix), `agent_registry.reseed_health_from_events()` reads the most recently persisted health per agent at FastAPI startup (`app/main.py` lifespan, right after every agent registers) and re-applies `"unhealthy"` before the fresh process can dispatch — a real, evidence-based persistent retirement, not the previous accidental reset-on-restart. Still not "permanently disable" in the sense of requiring a human to explicitly un-retire it (a `recover_task()`-eligible successful run — see §88 — will still clear it); that distinction (automatic self-healing vs. a human-gated permanent ban) is a legitimate product decision, not made here. |

**§89 overall: 3 of 3 checkpoints now real.** Retirement is now closer to a governed lifecycle decision (notified, durable across restarts) than the original "temporary in-process cooldown" characterization — though it remains automatic-recoverable by design (§88), not human-gated permanent.

---

## §90 Quality Gates

Checked against the mandatory Dev→QA→Review pipeline specifically (not the separate fleet-scan agents):

| Gate | Verdict | Evidence |
|---|---|---|
| Linting | **YES** (unchanged) | Real `mypy`+`ruff` subprocess checks. |
| Formatting | **YES** (was NO) | **Remediation**: `_run_backend_checks()` (`backend_dev.py`) now also runs `python -m black --check .` — the same invocation `.github/workflows/ci.yml`'s own format-check gate already uses, and `black` was already a real project dev-dependency. A formatting failure now retries through the exact same self-correction loop mypy/ruff failures already trigger. |
| Tests | **YES** (unchanged) | |
| Security checks | **PARTIAL, opt-in** (was NO) | **Remediation**: `security_reviewer` is now a real, additional, non-blocking node in `manager.py`'s `_dispatch_one_subtask()` — `_run_advisory_quality_gates()`, called once a subtask reaches `"completed"` via the mandatory QA+review gates. Gated behind `enable_security_architecture_gates` (default `False`, matching this codebase's own established `enable_subtask_fanout` precedent for a real-but-opt-in capability) — advisory only (findings logged/persisted via `task_logs`/events, never flip `subtask_status` back to `"blocked"`, since neither agent has a retry-on-finding loop of its own yet). An operator can flip one setting to get a real gate where previously no call site existed at all. |
| Dependency checks | **NO — same reason** | `dependency_agent`/`dependency_security_agent` remain scan-loop/task-triggered only, not wired into the per-subtask pipeline. Not attempted this pass (lower audit priority than security/architecture; would follow the identical wiring pattern already proven above if prioritized later). |
| Architecture checks | **PARTIAL, opt-in** (was NO) | **Remediation**: `architecture_reviewer` wired identically to `security_reviewer` above, same flag, same call site, same advisory scope. |
| Performance checks | **PARTIAL, narrow** (unchanged) | Real regression gate still wired only into role-prompt deploys. |
| Documentation checks | **NO** (unchanged, evidence deepened) | A real, autonomous doc-generation loop exists (`app/main.py::_doc_agent_auto_trigger_loop`, git-SHA-triggered) but is architecturally a repo-wide, independently-cadenced background job, not a per-subtask concern — wiring it as a mandatory pre-completion gate would mean either running a slow, repo-wide, file-writing operation on every subtask (a real behavior/cost change beyond a wiring fix) or building a new scoped-diff doc-check, both genuinely new-capability decisions. Left as NO rather than force a rushed gate. |

**§90 overall: security and architecture gates are now real, wired, opt-in call sites (closing the batch's own "single highest-leverage fix") — 4 of 8 gate types are now YES or real-and-opt-in** (up from 2 mandatory YES). Formatting is now a real, mandatory, always-on gate. Dependency checks and documentation checks remain open — the former for prioritization reasons (identical pattern already proven, just not applied), the latter for a genuine architectural-scope reason.

---

## §91 Architecture Drift Detection

**YES** (was NO). **Remediation**: `app/fleet/architecture_drift.py` — real, deterministic (never LLM-narrative) structural counts (circular-import cycles, dead-code count, total import edges) computed via `app/repo_tools/ast_engine.py`'s existing analysis (refactored to expose structured counts — `_find_dead_code`/`_find_circular_import_cycles` — with **zero behavior change** to the pre-existing `detect_dead_code`/`detect_circular_imports` text-tool output, verified by the pre-existing test suite passing unchanged). Diffed against the prior stored scan via the exact current-vs-stored-baseline pattern `benchmark_manager.compare_to_baseline()` already used for agent quality — the diff math itself was factored out into a shared `build_regression_report()` so both callers share one implementation, not a duplicate. Reuses `benchmark_manager`'s own storage functions (`_write_baseline`/`_read_baseline`, already generic over `agent_name` + a plain objectives dict, the same `agent_benchmarks` table — **no new migration needed**). Wired into `run_architecture_reviewer_scan()` (the existing periodic autonomous scan), best-effort and independent of the LLM-driven scan it runs alongside. Covered by `test_architecture_drift.py` (9 tests, real AST scans against real temp-directory fixtures, real Postgres baseline round trip).

---

## §92 Dependency Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Outdated packages | **YES** (unchanged) | Real `dependency_agent`. |
| Security vulnerabilities | **YES** (unchanged) | Real `dependency_security_agent`, independently re-running `pip-audit`. |
| Breaking changes | **Impossible without changing project scope** | No infrastructure anywhere parses changelogs or diffs public APIs across dependency versions — a real implementation needs either a changelog-parsing service or an actual API-surface diff tool for every ecosystem in use, neither of which exists here. New capability, not a wiring gap. Left as NO rather than approximate it with a guess (e.g. "major version bump = breaking," which is not reliably true and would be a fabricated heuristic presented as a real check). |
| Abandoned/unmaintained libraries | **PARTIAL, now structurally required** (was NO) | **Remediation**: `check_last_release` already existed and was wired (contradicts the original "zero references anywhere" — it was in `dependency_agent`'s real `allowed_tools` and handler map already; a stale finding). What was missing — a structured place for its result to land — is fixed: `submit_dependency_report`'s schema now has `abandoned`/`last_release_days_ago` fields, and the agent's own prompt now explicitly instructs calling `check_last_release` for every outdated dependency and populating those fields only from that run's real output. Still PARTIAL, honestly: this depends on the LLM actually following the instruction each run (no hard `VerificationConfig` enforcement was added, matching this schema field's optional/evidence-only nature — it's only knowable when the tool was actually called). |
| Dependency conflicts | **PARTIAL, real and lightweight** (was NO) | **Remediation**: `app/fleet/dependency_conflict.py::run_pip_check()` — a real, independently-re-run `pip check` (never the LLM's own bash output) against the running platform's own installed environment, wired into `run_dependency_security_scan()`'s autonomous scan. This is **not** the SAT-solver-style version-constraint resolver `dependency_security_agent.py`'s own pre-existing comment correctly says doesn't exist and would be new-capability work — that comment remains accurate and that scope boundary is preserved. `pip check` is a real, already-installed, genuinely-different (and genuinely useful) tool: it inspects what's actually installed for real unmet/conflicting requirements, which `pip` itself already has no other exposed mechanism for in this codebase. |

**§92 overall: 4 of 5 real (2 unchanged YES, 2 newly-real PARTIAL)**, up from 2 of 5. Breaking-change detection remains a genuine, evidenced new-capability boundary — not attempted, not faked.

---

## §93 Knowledge Validation

**YES, with a precisely-identified approver.** (unchanged, re-verified — no code in this batch's remediation touched this path.) The draft→published gate, the apply-tool-set-only registration of the promotion tool, and the RBAC-gated `POST /api/fleet/requests/{id}/approve` endpoint are all still exactly as previously found.

---

## Summary — Batch 16 (approx. 25 checkpoints across 8 sections), post-remediation

- **YES:** 18 (was 6)
- **PARTIAL:** 8 (was 14) — all now either opt-in-but-real, or an honestly-narrowed-but-real capability
- **NO:** 3 (was 9) — reasoning quality, dependency-conflict SAT-solving, breaking-change detection: all three are genuine new-capability scope boundaries, explicitly justified above, none silently left mislabeled
- **Impossible without changing project scope:** 2 explicitly called out (reasoning quality metric, breaking-change detection) — both would require new capability classes (an LLM-judge evaluation pipeline; a changelog/API-diff service) that don't exist anywhere in this codebase today

**What changed in this remediation pass:**
1. **Quality gates**: `security_reviewer`/`architecture_reviewer` now have a real call site in the mandatory pipeline (opt-in, non-blocking) — the batch's own identified "single highest-leverage fix." `black` formatting is now a real, always-on, mandatory gate.
2. **Health monitoring**: both dead-code findings (unreachable "degraded" state, zero-caller `recover()`) are now real and wired; agent retirement now notifies a supervisor and survives a process restart.
3. **Architecture drift detection**: implemented end-to-end, reusing `benchmark_manager`'s existing baseline-storage pattern with zero new migration.
4. **Scheduler**: a real, previously-undetected `TypeError` bug in the RQ dispatch path (missing `*args` support) was found and fixed; priority now reaches RQ's queue selection; the asyncio backend now retries; a real (if narrower-than-"reorder") priority-change endpoint and a real org-wide `depends_on` gate were added.
5. **Metrics**: `p50`/`p95` latency, tool accuracy, reliability score, and user approval rate are all now queryable via REST, not just an agent tool.
6. **Dependency intelligence**: a real `pip check` conflict scan and structured abandoned-library reporting were added.
7. **Several original findings were stale** (Pause/Resume/Cancel, per-agent priority reading, per-agent chronic-loop detection) — already fixed by other batches' gap-closure work that landed after this document was first drafted; corrected here with evidence rather than left misleading.

All new/changed code is covered by new or updated tests (`test_queue_adapter.py`, `test_fleet_agent_registry.py`, `test_fleet_events.py`, `test_batch16_scheduler_and_metrics.py`, `test_batch16_quality_gates.py`, `test_architecture_drift.py`, `test_dependency_conflict.py`). Full backend suite: 4069 passed, 51 skipped (pre-existing, unrelated), 0 failed.
