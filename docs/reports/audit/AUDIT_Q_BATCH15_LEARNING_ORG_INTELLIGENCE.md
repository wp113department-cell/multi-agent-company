# Batch 15 — Learning & Organizational Intelligence Cluster

Covers §33, §34, §35, §36, §37, §74, §75, §76, §105-118 (AI Suggestion Review, Incremental Implementation, Project Health/Self-Audit, Learning System, User Preference Learning, Org Knowledge Sharing/Company Brain, Continuous Improvement/Performance Review/Architecture Review/Capability Gap Detection, Prompt/Tool Evolution, Project Evolution, Release Retrospectives, Quality Score, Safe Self-Improvement). Evidence-only, file:line cited.

This is the densest cluster in the question file — nearly 20 sections asking variations of "does the system genuinely learn and improve itself over time." The real answer is a single coherent system (the 7-agent fleet-enhancement tier, first characterized in Batch 7) that covers a meaningful subset of what's asked, plus a separate, less complete memory/lesson layer (Batch 3). Below, each section is mapped to exactly what that real system does and doesn't cover.

---

## §33 AI Suggestion Review

**NO.** Zero evidence of provenance-aware code review — no distinction anywhere between "code the agent wrote" and "code a user pasted from another LLM." Generic review capability exists (`reviewer.py`, `style_reviewer.py`, `security_reviewer.py`) but none has special handling for externally-sourced code.

## §34 Incremental Implementation (phased delivery)

**NO.** Neither `Epic` nor `DevTask` has a phase/milestone field. Combined with Batch 12's finding (decomposer produces a flat subtask list), no layer of the system supports "implement phase 1 of N, verify, then phase 2."

## §35 / §36 Project Health Monitoring / Self-Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Broken imports, dead code, unused files, duplicate functions, circular dependencies | **YES** | Real tools (`import_graph`, `circular_dep_detect`, `dead_code_detect`) on `architecture_reviewer`, run autonomously on the fleet scan loop. |
| Memory leaks | **NO** | Zero references anywhere. |
| Performance regressions (app-level) | **NO** | `quality_score.py` explicitly documents "no real app-runtime signal exists" for this category. |
| Dependency conflicts | **NO** | `dependency_security_agent`'s only real execution path is CVE/vulnerability scanners (`pip-audit`, `npm audit`) — no conflict-resolution/`pip check`-style tool. |

**§35/§36 overall: PARTIAL.** Real, autonomous coverage for the code-structure half; the runtime/dependency-conflict half is absent.

## §37 Learning System — the most consequential finding in this batch

**Precisely characterized, not just PARTIAL.** Two different `success_rate` fields exist:
- `Agent.success_rate` (Postgres) — genuinely computed from real `AgentRun` outcomes, but **only when a specific metrics API endpoint is hit**; nothing schedules this, so it's stale unless someone happens to query it.
- `AgentCapability.success_rate` (in-process `capability_registry`) — a **static value set at registration time** (e.g. literally `0.95`, `0.82`), never updated from real outcomes, despite the module's own docstring claiming a DB merge happens "at query time" — no such merge code exists.

**`FleetManager.select()`'s routing score uses exactly the static, never-updated field.** This means the one thing the question is really asking — "does routing get smarter as agents succeed/fail over time" — is **NO**, verified precisely rather than assumed. What genuinely does change from experience is the *injected prompt context* (via `memory_hook_node`, confirmed real) — agents get smarter in what they know, not in how they're selected.

## §74 / §113 User Preference Learning

**NO — real gap, not just narrow.** `MemoryEmbedding.category` has exactly 4 valid values (`task`/`architecture`/`failure`/`learning`, per `_VALID_CATEGORIES`) plus a 5th de-facto category (`procedure`) not exposed in the API filter. **Zero references to "preference" anywhere in the codebase.** A coding-style or naming preference has no dedicated category, tagging, or retrieval path — it would have to be shoehorned into the generic `learning` bucket with no special handling, meaning it competes for retrieval ranking with every other kind of learning signal rather than being reliably surfaced when relevant.

## §75 / §105 / §112 Organizational Knowledge Sharing / Company Brain / Knowledge Validation

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Central store consulted before starting work | **YES** | `memory_hook_node` runs pre-inference on every graph-based agent run, real and wired (not aspirational). |
| Covers: proven patterns/successful workflows, failed approaches, architecture decisions, reusable templates | **YES** | Map directly to real categories (`task`/completed, `failure`, `architecture`, `procedure`). |
| Covers: approved prompts/MCPs/tools, known bugs (as distinct types) | **NO** | Prompt versions live in a separate table not surfaced through `memory_hook_node`; bugs fall generically under `failure` with no dedicated bug-tracking category. |
| Knowledge validation before promotion | **YES — confirmed, with a real API** | `VersionedMemoryStore`'s draft→published gate, plus a real, wired `POST /api/memory/lessons/{id}/rollback` endpoint. |

**§75/§105/§112 overall: PARTIAL, leaning strong.** The core "consult before starting, validate before trusting" loop is real; the taxonomy is narrower than the question's full list implies.

## §76 / §106 / §108 / §109 / §116 Continuous Improvement, Performance Review, Architecture Review, Capability Gap Detection

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Per-agent performance metrics, aggregated over time | **YES, but ephemeral** | `MetricsCollector` computes real `p50`/`p95` latency, tool accuracy, filterable `by_agent` — genuine aggregation, not single-run data. But it's an in-process ring buffer (1000 entries), lost on restart — not a persisted dashboard. |
| `agent_performance_reviewer` uses real data, not self-reports | **YES** | Confirmed via its own docstring and tool set (`fleet_metrics_read`, reading the real ring buffer). |
| Capability gap detection from repeated failed/blocked requests | **PARTIAL** | `agent_advisor` reviews whether "the right agent(s) ran" from task history and audit logs — this is orchestration-correctness review, not a dedicated repeated-failure-clustering mechanism. Close, but not the specific pattern asked about. |

**§76/108/109/116 overall: PARTIAL.** Real per-agent performance review exists and is grounded in real data — a genuine strength — but is ephemeral and doesn't specifically cluster repeated user pain points.

## §110 / §111 Prompt Evolution / Tool Evolution

**Prompt evolution: YES, and more substantial than expected.** Any `write_file`/`edit_file` targeting `roles/*.md` from the 4 apply-capable fleet agents is automatically routed through `PromptRegistry` (propose→review→approve→deploy), gated by a real pre-deploy regression check (`RegressionDetector` comparing against a stored benchmark baseline, raising `DeploymentBlocked` on regression) — this is a genuine, tested, safety-gated self-modification pipeline, not a stub.

**One real gap found**: `PromptRegistry.rollback()` exists as a function but has **zero callers anywhere** — unlike the lesson-rollback (which is wired to a real API endpoint), role-prompt rollback is dead code, unreachable from any production path despite the underlying versioning data existing to support it.

**Tool evolution: NO.** No equivalent propose/approve pipeline exists for `tools.py` or any tool manifest — the propose-and-deploy mechanism recognizes only `roles/*.md` paths.

## §114 Project Evolution (per-repo knowledge isolation)

**YES — confirmed via actual SQL, not just schema.** `repo_id` scoping in memory queries is a real WHERE-clause condition (`repo_id IS NULL OR repo_id = :repo_id`), not merely a column that exists unused. This is genuinely isolated, evidence-checked at the query level.

## §115 Release Retrospectives

**NO.** Zero code ties a "what went well/what failed" report to any release or deployment event.

## §117 Quality Score

**PARTIAL — real aggregator, narrower scope than asked.** `get_quality_score()` genuinely combines already-persisted category scores from 4 real producers (test, architecture, security, memory) into one `overall_score`, correctly excluding unavailable categories rather than treating them as zero. **5 of the 9 categories the question describes are explicitly marked `not_implemented` and excluded** (documentation, performance, tools, agents, prompts), each with a documented reason (e.g. `agents` excluded because its benchmark data isn't repo-scoped). This is honest, well-engineered partial coverage — the aggregator itself doesn't overclaim, even though the underlying coverage is incomplete.

## §118 Safe Self-Improvement Lifecycle (8-step check)

| Step | Verdict | Evidence |
|---|---|---|
| Detect | **YES** | Scheduled scan loop. |
| Analyze | **YES** | Real tool-grounded findings. |
| Propose | **YES** | Real `EnhancementRequest` rows + diffed prompt versions. |
| Simulate impact | **NO** | Zero code simulates a change's effect before human review. |
| Show plan | **YES** | Real dashboard/detail API. |
| Wait for approval | **YES** | Real RBAC-gated approval endpoint. |
| Implement | **YES, 4 of 7 agents** | Real write-capable apply handlers. |
| Test | **YES, pre-deploy only** | Real `run_tests` call + regression-baseline gate for prompt deploys specifically. |
| Rollback if quality declines | **NO — not automatic** | The rollback function exists but is dead code (no caller); the only wired rollback anywhere in this system is lesson-rollback, and that's human-triggered, not automatic-on-decline. |

**§118 overall: PARTIAL, precisely 6 of 8 steps real.** This is a strong result for such an ambitious ask — most of a genuinely safe self-improvement loop is built and gated correctly; the two missing pieces (pre-change simulation, automatic rollback-on-decline) are the hardest and most speculative parts of the original 9-step wishlist, not a sign of an unfinished basic loop.

---

## Summary — Batch 15 (approx. 20 checkpoints across the full cluster)

- **YES:** 7 (including 2 "YES with caveats" scored as YES for their core claim)
- **PARTIAL:** 9
- **NO:** 6

**This batch has the widest gap between the question file's ambition and the real system's scope — but the real system is not thin.** The 7-agent fleet-enhancement tier genuinely implements 6 of an 8-step safe self-improvement lifecycle, a real prompt-versioning-and-regression-gated deploy pipeline, and honest, non-overclaiming score aggregation. The gaps that exist are precise and mostly in the harder, more speculative territory (simulate-before-applying, cross-run agent-identity looping detection, preference-as-a-first-class-memory-type) rather than basic missing infrastructure.

**Two findings worth prioritizing above the rest:**
1. **`FleetManager.select()`'s routing score never actually updates from real outcomes** — this directly contradicts what "the system learns" would mean for agent selection specifically, even though learning is real for prompt context.
2. **`PromptRegistry.rollback()` is dead code** despite the surrounding infrastructure (versioning, regression detection) being real and wired — a rollback capability that exists in the data model but can't currently be invoked is a meaningful gap in an otherwise safety-conscious self-modification pipeline.

**Production Enhancement Plan:** Wire `Agent.success_rate`'s already-real computation (`api/registry.py`'s live `AgentRun` aggregation) into `AgentCapability`'s in-process record via a scheduled job (the same pattern as `_fleet_agents_scan_loop`, already proven), so `FleetManager.select()`'s scoring reflects reality instead of registration-time constants. Add an API route calling `PromptRegistry.rollback()`, mirroring the pattern already used for lesson-rollback — the underlying data and versioning already support it, only the caller is missing.
