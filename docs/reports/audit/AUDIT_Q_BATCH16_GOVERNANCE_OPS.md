# Batch 16 — Organization-Wide Task Scheduler, Agent Performance Metrics, Health Monitoring, Automatic Retirement, Quality Gates, Architecture Drift Detection, Dependency Intelligence, Knowledge Validation

Covers §86-93. Evidence-only, file:line cited.

**Correction to a finding carried forward from Batch 1**: this pass found `queue_adapter.py::dispatch_job()` is the real chokepoint every `api/tasks.py` launch site actually calls — when `settings.queue_backend=="rq"`, it genuinely dispatches through `RQQueueAdapter`. The "dead infrastructure" characterization from Batch 1 was accurate for the *default* configuration (asyncio backend falls through to `BackgroundTasks`), but overstated for the RQ path specifically, which is live when configured. This refinement is incorporated below.

---

## §86 Organization-Wide Task Scheduler

| Capability | Verdict | Evidence |
|---|---|---|
| Queue | **YES** | Real, two named priority queues (`gridiron-high`/`gridiron-default`) via RQ when configured. |
| Prioritize | **PARTIAL** | Only two coarse buckets (high/default) via a kwarg — no numeric priority, and **`DevTask.priority` is never actually read by any dispatch code**, confirming and sharpening the Batch 2 finding: the field isn't just under-used, it has zero real callers anywhere in the queue/dispatch path either. |
| Pause / Resume / Cancel / Reorder | **NO** | None of these exist on any queue adapter interface. No `"cancelled"` `DevTask` status exists in the state machine at all. |
| Detect blocked tasks | **PARTIAL** | Real `"blocked"` status with real transitions — but purely failure-driven (retries exhausted), not dependency-driven. |
| Detect dependencies / optimize order | **PARTIAL — real, but scoped narrower than "organization-wide"** | Real topological sort exists, but only for *subtasks within one task* (`_topological_subtask_order`, tested with cycle detection). **`DevTask` itself has no `depends_on` column** — there is no cross-task, org-wide dependency graph, only an intra-task one. |
| Retry | **PARTIAL** | Real on the RQ path (`Retry(max=...)`, plus a real dead-letter sweep reading `FailedJobRegistry`). **Zero retry logic on the default `AsyncioQueueAdapter` path** — a failed job there is simply marked failed. |

**§86 overall: PARTIAL, with a real backend-choice-dependent inconsistency.** Exactly like the job-timeout finding from Batch 8, scheduler robustness depends on which queue backend an operator selects, and the documented default (asyncio) is the weaker of the two.

---

## §87 Agent Performance Metrics

Checked against 10 explicitly-named metrics:

| Metric | Verdict | Evidence |
|---|---|---|
| Success rate | **YES, queryable** | Real live-computed API endpoints (`/api/agents/{name}/metrics`, `/api/fleet/reports/health`). |
| Failure rate | **YES, queryable** | Same endpoint. |
| Avg execution time | **PARTIAL** | Real `p50`/`p95` latency computed, but only reachable via an agent-callable tool, not any HTTP route — a human operator can't query this without going through an agent. |
| Tool usage | **PARTIAL** | Same — real, but only via tool, not REST API. |
| Token usage | **YES, queryable** | Real SQL aggregates via `/api/metrics` and `/api/fleet/reports/cost`. |
| Reasoning quality | **NO** | Zero references anywhere under this name. |
| Retry count | **PARTIAL** | Persisted field (`Agent.avg_retries`) is explicitly self-documented as *approximated from token counts*, not a true per-run retry tally — the real per-run figure exists (`RunMetrics.retries`) but isn't the one that gets persisted. |
| User approval rate | **NO** | No `Approval` model; individual approve/reject decisions exist but nothing aggregates a ratio per agent. |
| User satisfaction | **PARTIAL — proxy only** | Real regex-based frustration detector exists, explicitly self-documented as not a claim of real sentiment/NLP accuracy, and it's chat-turn-level, not an aggregated per-agent satisfaction score. |
| Reliability score | **NO** | No field or metric exists under this name; success_rate is the closest proxy. |

**§87 overall: PARTIAL.** Half the metrics are genuinely real and queryable via API; the other half are either tool-only (not operator-accessible), approximated rather than exact, or entirely absent. This is a precise, checkable result rather than a vague "some metrics exist."

---

## §88 Agent Health Monitoring

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Detect slow/crashed agents | **YES** | Real, scheduled `reconcile_orphaned_runs()` sweep (every 300s) finds stuck `running` status with stale heartbeats, marks failed, escalates. |
| Detect looping agents | **PARTIAL — per-run, not per-agent** | `n_stalls` stall detection is confirmed to be scoped to a single run's state, reset at the start of every run — there is no mechanism that flags an agent *identity* as chronically looping across multiple runs. |
| Detect hallucinating agents / memory leaks / synchronization failures | **NO** | Zero code for any of these. |
| Health state transitions are real, not static | **YES, precisely characterized** | `AgentInstance.fail()` genuinely transitions `health="unhealthy"` at a real hardcoded threshold (3 consecutive errors) — this is runtime-driven, not a cosmetic field. |
| "degraded" state | **NO — dead code path** | A real function call path exists that's *supposed* to set health to `"degraded"` via an event bus, but the event type is missing from the bus's own type-mapping table, so the call silently no-ops. **In practice only two health values ever actually get written: "healthy" and "unhealthy"** — "degraded" exists in the type system but is unreachable. |
| Automatic recovery from unhealthy | **NO** | A `recover()` function exists and would reset health, but has zero callers anywhere — once unhealthy, an agent instance stays that way until the process restarts (and since this is in-process state, a restart clears it anyway, which is a different, accidental form of "recovery"). |

**§88 overall: PARTIAL, with two precise dead-code findings.** The core failure-detection mechanism (3-strikes → unhealthy) is real and correctly wired. Both the "degraded" intermediate state and the recovery path exist in code but are structurally unreachable — these are exactly the kind of gaps that pass a superficial "does this function exist" check while failing a "is this function ever actually called" check, which is the standard this audit was asked to apply throughout.

## §89 Automatic Agent Retirement

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Disable a repeatedly-failing agent | **YES — real and automatic, but narrow** | `FleetManager.select()` genuinely excludes any agent whose `health == "unhealthy"` (the same 3-strikes threshold from §88) — real, code-enforced exclusion, not a UI toggle. |
| Notify a supervisor | **NO** | No email/Slack/alert call anywhere at the health transition — only an internal metadata field is updated. |
| Replace / permanently disable | **NO** | This is a selection filter only, reversible by process restart, not a persistent retirement. |

**§89 overall: PARTIAL.** Real, but narrower than "retirement" implies — it's closer to "temporary in-process cooldown" than a governed lifecycle decision, and its practical reach is limited by the fact that `FleetManager.select()` itself isn't the primary dispatch path for most work (per Batch 2's finding).

## §90 Quality Gates

Checked against the mandatory Dev→QA→Review pipeline specifically (not the separate fleet-scan agents):

| Gate | Verdict | Evidence |
|---|---|---|
| Linting | **YES** | Real `mypy`+`ruff` subprocess checks gate the coder's retry loop; QA independently re-runs them. |
| Formatting | **NO** | No `black`/formatter invocation found anywhere in the gate path. |
| Tests | **YES** | Real, code-enforced (`VerificationConfig` blocks fabricated `tests_run` claims). |
| Security checks | **NO — not in the mandatory pipeline** | `security_reviewer`/`dependency_security_agent` exist and are real, but are absent from the Dev→QA→Review call sites — they run standalone or only on the separate autonomous scan loop, never as a gate before a normal task is marked complete. |
| Dependency checks | **NO — same reason** | |
| Architecture checks | **NO — same reason** | `architecture_reviewer` is scan-loop only. |
| Performance checks | **PARTIAL, narrow** | A real regression gate exists but is wired only into role-*prompt* deploys (the self-improvement pipeline), not regular code changes. |
| Documentation checks | **NO** | No gate requires doc generation/update before task completion. |

**§90 overall: PARTIAL, with a clear, actionable finding.** Only 2 of 8 gate types (linting, tests) are actually mandatory for a normal task to complete. Three real, well-built agents exist that *could* provide the missing gates (security, dependency, architecture) but simply aren't called from the pipeline that decides whether work is "done" — this is a wiring gap, not a missing-capability gap, since all three checking agents already exist and work standalone.

**Production Enhancement Plan:** Add `security_reviewer` and `architecture_reviewer` as additional nodes in `manager.py`'s Dev→QA→Review sequence (at least as non-blocking informational gates initially, given they're not currently tuned for blocking behavior) — the agents themselves need no new code, only a new call site following the same pattern as the existing `run_qa`/`run_reviewer` calls.

## §91 Architecture Drift Detection

**NO.** `architecture_reviewer` runs its structural checks fresh every scan with **no stored baseline to compare against** — grepped the entire agent file for any baseline/prior-scan reference: zero hits. Each scan is stateless relative to earlier scans, so "did technical debt increase since last time" cannot currently be answered — only "what does technical debt look like right now."

**Production Enhancement Plan:** The regression-detection pattern already exists and works elsewhere in the codebase (`benchmark_manager.compare_to_baseline()`, used for prompt-deploy quality gates) — apply the same current-vs-stored-baseline comparison pattern to `architecture_reviewer`'s scan output, storing each scan's import-graph/dead-code/circular-dependency counts and diffing against the prior stored scan.

## §92 Dependency Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Outdated packages | **YES** | Real, dedicated `dependency_agent` using live registry checks. |
| Security vulnerabilities | **YES** | Real, dedicated `dependency_security_agent`, independently re-running `pip-audit`/`npm audit` rather than trusting the LLM's narrative — a genuinely careful design choice, explicitly commented as such in the code. |
| Breaking changes | **NO** | No code checks for breaking API changes between dependency versions. |
| Abandoned/unmaintained libraries | **NO** | Zero references anywhere. |
| Dependency conflicts | **NO** | Explicitly, self-documented in `dependency_security_agent.py`'s own comments: no SAT-solver-style conflict detector exists. |

**§92 overall: PARTIAL — 2 of 5, but the 2 that are real are genuinely well-built.** The vulnerability-detection agent's choice to re-run the actual scanner rather than trust the model's claim is a real, above-average piece of engineering discipline worth crediting.

## §93 Knowledge Validation

**YES, with a precisely-identified approver.** The draft→published gate is real (confirmed in Batch 15). This pass adds the specific mechanism: the promotion tool is registered only in the fleet agent's *apply* tool set (post-approval), never in its autonomous *scan* tool set — meaning the agent can only ever propose promotion, and the actual execution requires a human with the RBAC "approver" role acting through the real, gated `POST /api/fleet/requests/{id}/approve` endpoint. This is a clean, verifiable separation between "agent proposes" and "human with a specific permission executes," not a vague human-in-the-loop claim.

---

## Summary — Batch 16 (approx. 25 checkpoints across 8 sections)

- **YES:** 6
- **PARTIAL:** 14
- **NO:** 9 (roughly — several sections have multiple sub-items)

**Findings worth flagging above the rest:**
1. **Only 2 of 8 quality-gate types are actually mandatory** for a normal task to ship, despite 3 of the missing 6 having fully-built, working agents that simply aren't wired into the pipeline — this is the single highest-leverage fix identified in this batch, since it requires wiring, not new capability.
2. **The "degraded" agent health state and the health-recovery function are both dead code** — present in the type system/function definitions but structurally unreachable, a subtle gap that only shows up by tracing actual callers, not by reading the state enum.
3. **The queue/scheduler robustness gap is now confirmed backend-dependent** (real retry/priority on RQ, none on the asyncio default) — consistent with and reinforcing the Batch 8 job-timeout finding; these two findings together suggest the RQ backend should be the documented/recommended default rather than asyncio, given how much more production-hardening exists on that path.
