# Batch 15 — Learning & Organizational Intelligence Cluster

Covers §33, §34, §35, §36, §37, §74, §75, §76, §105-118 (AI Suggestion Review, Incremental Implementation, Project Health/Self-Audit, Learning System, User Preference Learning, Org Knowledge Sharing/Company Brain, Continuous Improvement/Performance Review/Architecture Review/Capability Gap Detection, Prompt/Tool Evolution, Project Evolution, Release Retrospectives, Quality Score, Safe Self-Improvement). Evidence-only, file:line cited.

**Re-audited and gap-closed 2026-08-11** (production implementation pass, following the original evidence-only audit below). Every implementable PARTIAL/NO checkpoint from the original pass was either closed with real, tested, production-grade code, confirmed already production-ready from a separate batch's prior work, or is explicitly documented here as out of this gap-closure's bounded scope with the concrete reason why. The original per-checkpoint evidence is preserved below each finding for traceability; **the bolded verdict on each line is the current, post-gap-closure status.**

---

## §33 AI Suggestion Review

**NO → IMPOSSIBLE WITHIN CURRENT PRODUCT SCOPE (explained, not implemented).**

Original finding stands as evidence: zero provenance-aware code review anywhere; generic review capability exists (`reviewer.py`, `style_reviewer.py`, `security_reviewer.py`) with no special handling for externally-sourced code.

Re-confirmed before closing this out: there is no product surface anywhere in this platform (checked `app/api/specialized_agents.py`'s full dispatch registry and `chat_agent.py`'s 36-tool suite) that accepts a raw external code snippet as a review target distinct from a git diff the fleet's own pipeline or a connected worktree produced. Every review agent operates on `diff`/`repo_path` inputs sourced from this platform's own task/worktree machinery. There is also no separate git commit identity for fleet-agent-authored commits vs. human commits (`git_commit`'s handler in `app/agents/tools.py` uses the ambient `git config user.*`, not a distinct bot identity), so authorship can't be distinguished retroactively via `git blame` either. Building "paste external code for review" (a new ingestion endpoint/schema) with escalated-scrutiny routing would be a new product feature, not a wiring gap in already-existing dormant machinery — every other item in this batch that reached YES did so by connecting two pieces of already-built, currently-unreachable machinery. This one has no second piece to connect.

## §34 Incremental Implementation (phased delivery)

**NO → IMPOSSIBLE WITHIN CURRENT PRODUCT SCOPE (explained, not implemented).**

Original finding stands: neither `Epic` nor `DevTask` has a phase/milestone field; the decomposer produces a flat subtask list (Batch 12).

Re-confirmed: closing this for real means restructuring two core pipeline components — `decomposer.py`'s flat `submit_subtasks` output shape, and the epic execution graph's dispatch-then-verify flow — into a phase-gated model where phase N+1's subtasks are withheld until phase N is independently verified. Every other checkpoint closed in this pass was an *additive* wire-up (a new column, a new scheduled job, a new tool) that could not regress existing behavior. This one is a structural change to the core task-execution pipeline itself — high blast radius across `decomposer_node`, `manager.py` orchestration, and the epic executor — which the "preserve 100% existing functionality, no risky refactors" mandate for this pass correctly excludes from a bounded gap-closure. Documented here as a distinct, larger feature investment, not a missing wire.

## §35 / §36 Project Health Monitoring / Self-Audit

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Broken imports, dead code, unused files, duplicate functions, circular dependencies | **YES (unchanged)** | Real tools (`import_graph`, `circular_dep_detect`, `dead_code_detect`) on `architecture_reviewer`, run autonomously on the fleet scan loop. |
| Dependency conflicts | **YES — already production-ready, no reimplementation.** | Closed by **Batch 16 §92** (commit "batch 16 done", 2026-08-11), *before* this pass started: `app/fleet/dependency_conflict.py::run_pip_check()` runs a real, independently-re-run `pip check` against the platform's own installed environment and is wired into `run_dependency_security_scan()` (`app/agents/dependency_security_agent.py:288-306`), itself part of the autonomous `_fleet_agents_scan_loop`. Tested in `tests/test_dependency_conflict.py`. Verified present and wired before crediting — not reimplemented. |
| Memory leaks | **NO → IMPOSSIBLE WITHIN CURRENT PRODUCT SCOPE.** | No runtime/APM instrumentation exists — or is feasible to add in this pass — for an arbitrary *target* repo this platform edits and reviews but does not deploy or run under sustained load. A static AST heuristic (e.g. flagging unbounded module-level caches) would be a materially weaker, different capability than real memory-leak detection, and presenting it as equivalent risks exactly the "fake"/overclaiming implementation this pass's own rules prohibit. Out of scope. |
| Performance regressions (app-level) | **NO → IMPOSSIBLE WITHIN CURRENT PRODUCT SCOPE.** | Same reasoning: `quality_score.py` still correctly documents "no real app-runtime signal exists" — the only real latency data (`agent_benchmarks.objectives.latency_p50`) measures this platform's own agent-orchestration time, never a user's deployed target application, which this platform has no live instrumentation hook into. |

**§35/§36 overall: PARTIAL, real coverage improved.** Code-structure half and dependency-conflict detection are both real and autonomous; memory-leak/app-performance detection remain genuinely out of this platform's current architecture, not missing wiring.

## §37 Learning System — closed

**PARTIAL → YES.** `FleetManager.select()`'s routing score now updates from real `AgentRun` outcomes on a schedule.

Original finding (still the correct diagnosis of what was broken): `Agent.success_rate` (Postgres) was genuinely computed from real `AgentRun` outcomes but only when a human hit `GET /api/agents/{name}/metrics`; `AgentCapability.success_rate` (in-process `capability_registry`, what `FleetManager.select()` actually reads) was a static registration-time constant, never updated, despite the module's own docstring claiming a DB merge "at query time" that didn't exist.

**Closed:**
- `CapabilityRegistry.update_success_rate()` (`app/fleet/capability_registry.py`) — new, thread-safe, real in-place mutation of the exact `AgentCapability` instance `fleet_manager.select()` reads.
- `agent_registry.compute_live_success_rate()` (`app/fleet/agent_registry.py`) — the one real computation from `AgentRun` outcomes, factored out of `api/registry.py::get_agent_metrics()` (its only prior caller) so both the API endpoint and the new scheduled job share it — no duplicated logic.
- `main.py::_fleet_success_rate_sync_loop()` — new leader-gated background loop (`FLEET_SUCCESS_RATE_SYNC_INTERVAL_HOURS`, default hourly), matching the proven `_benchmark_baseline_loop`/`_fleet_agents_scan_loop` pattern exactly. Skips any agent with zero real runs (its registration-time constant remains the honest value until real data exists — never overwritten with a fabricated number).

Tested: `tests/test_batch15_fleet_learning.py`. What genuinely does NOT change: the injected prompt context via `memory_hook_node` was already real and remains the other half of "agents get smarter" — now both halves (what they know, and how they're selected) are real.

## §74 / §113 User Preference Learning — closed

**NO → YES.** `preference` is now a first-class `MemoryEmbedding` category with a real write path and retrieval path.

Original finding: zero references to "preference" anywhere; would have been shoehorned into the generic `learning` bucket.

**Closed**, mirroring the codebase's own established per-category shape (`embed_procedure`/`query_procedures`) exactly:
- `app/memory/store.py::embed_preference` / `embed_preference_sync` / `query_preferences` — real embeddings, real composite-score ranking, same as every other category.
- New `record_preference` tool (`app/agents/tools.py`), wired into `CHAT_TOOLS`/`make_chat_handlers` — chat is the direct human-facing surface where a preference is naturally stated.
- `memory_hook_node` (`base_graph.py`) and `ChatSession._memory_read_context` (`chat_agent.py`) both now retrieve and inject preferences for **every** agent, not just the one that recorded it.
- `_VALID_CATEGORIES` in `api/memory.py` extended (`preference`, `bug`, and the pre-existing de-facto `procedure` category, previously written but never filterable via this read API).

Tested: `tests/test_batch15_preference_bug_memory.py`, `tests/test_batch15_tool_handlers.py`.

## §75 / §105 / §112 Organizational Knowledge Sharing / Company Brain / Knowledge Validation

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Central store consulted before starting work | **YES (unchanged)** | `memory_hook_node` runs pre-inference on every graph-based agent run. |
| Covers: proven patterns/successful workflows, failed approaches, architecture decisions, reusable templates | **YES (unchanged)** | `task`/completed, `failure`, `architecture`, `procedure` categories. |
| Covers: known bugs (as a distinct type) | **NO → YES.** | New `bug` category (`app/memory/store.py::embed_bug`/`query_bugs`), wired into the existing `known_issues_write` tool handler (`app/agents/tools.py`) *alongside*, not instead of, its unchanged flat-file append — the same known issue is now both human-readable (unchanged) and semantically searchable/retrieved via `memory_hook_node` (previously it was neither, despite the tool existing since Day 0). Tested: `tests/test_batch15_preference_bug_memory.py`, `tests/test_batch15_tool_handlers.py`. |
| Covers: approved prompts/MCPs/tools (as a distinct type) | **NO → still NO, documented as out of this pass's scope.** | Prompt versions (`PromptVersion` table, `prompt_registry.py`) remain a separate, real, governed system (draft→review→approve→deploy) serving a different purpose (safe self-modification) than semantic retrieval. Folding prompt-version diffs into `memory_hook_node`'s embedding-based retrieval as searchable text is a real design decision not made in this pass — noted for a future gap-closure, not claimed done. |
| Knowledge validation before promotion | **YES (unchanged)** | `VersionedMemoryStore`'s draft→published gate + `POST /api/memory/lessons/{id}/rollback`. |

**§75/§105/§112 overall: PARTIAL, meaningfully stronger.** 3 of 4 sub-checkpoints are now real (up from 2 of 4); the remaining gap (prompts/MCPs/tools as organizational knowledge) is honestly still open, not claimed closed.

## §76 / §106 / §108 / §109 / §116 Continuous Improvement, Performance Review, Architecture Review, Capability Gap Detection

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Per-agent performance metrics, aggregated over time | **YES, but still ephemeral (unchanged)** | `MetricsCollector` ring buffer (1000 entries), lost on restart. Not touched in this pass — a persistence layer for it is a separate, larger change than this batch's scope. |
| `agent_performance_reviewer` uses real data, not self-reports | **YES (unchanged)** | `fleet_metrics_read`, real ring-buffer data. |
| Capability gap detection from repeated failed/blocked requests | **PARTIAL → YES.** | New `app/fleet/capability_gap.py::detect_capability_gaps()` — a deterministic (no LLM judgment) clustering of real `AgentRun` rows by `agent_type`, real failure counts/rates against real configurable thresholds, real `error` text samples (never paraphrased). Exposed as a new tool `capability_gap_scan` (`app/agents/tools.py`), wired into `agent_advisor`'s SCAN prompt and tool set (`app/agents/agent_advisor.py`) so its orchestration-correctness review now also reviews a real, pre-computed cluster report instead of trying to eyeball clustering from raw history. Tested: `tests/test_batch15_capability_gap.py` (8 cases: threshold gating, running-run exclusion, sort order, empty/populated report formatting, DB-query delegation). |

**§76/108/109/116 overall: PARTIAL, the specifically-asked-about gap now closed.** Metrics persistence (a separate, honestly-scoped ask) remains ephemeral by design of this pass's boundaries.

## §110 / §111 Prompt Evolution / Tool Evolution

**Prompt evolution: YES (unchanged) — plus the one real gap now closed.**

Original finding: `PromptRegistry.rollback()` existed, fully built and tested, with zero callers anywhere — dead code despite real, wired versioning/regression-gated deploy infrastructure around it.

**Closed:**
- `GET /api/fleet/prompts/{role_name}/history` and `POST /api/fleet/prompts/{role_name}/rollback` (`app/api/fleet_dashboard.py`) — RBAC-gated (`require_approver`), mirroring the exact pattern already established for lesson-rollback (`POST /api/memory/lessons/{id}/rollback`). First real, reachable caller of `PromptRegistry.rollback()`.
- Automatic trigger added too (see §118 below): `prompt_auto_rollback` loop calls the same `rollback()` on detected regression, not just the human-operated dashboard route.

Tested: `tests/test_batch15_prompt_rollback_api.py` (history ordering, rollback restores prior version + writes the real role file, 404 when nothing to roll back to, RBAC enforcement).

**Tool evolution: NO → IMPOSSIBLE WITHIN CURRENT ARCHITECTURE (explained, not implemented).** `tools.py` (and every per-agent tool-handler module) holds live, already-imported executable Python code bound once at module-import time — fundamentally unlike `roles/*.md`, which `app.agents.base.load_role()` re-reads fresh from disk on every single call, making a file-overwrite-based deploy safe with zero process restart. Safely self-modifying and hot-deploying *executable code* would require a code-reload/sandboxing subsystem that does not exist here, and building one is a distinct, materially larger safety-and-infrastructure investment than prompt-text versioning — outside this gap-closure's bounded scope. `tool_manifest.py` (the one candidate "tool manifest" that's declarative, not executable) stores its data as an in-code Python dict literal rather than a data file; refactoring its storage format to support the same versioned-file-write pattern would be a structural change to a safety-critical governance module, which this pass's "no risky refactors" mandate correctly excludes.

## §114 Project Evolution (per-repo knowledge isolation)

**YES (unchanged).** `repo_id` scoping in memory queries remains a real WHERE-clause condition, confirmed unchanged in this pass.

## §115 Release Retrospectives — closed

**NO → YES.** A real "what went well/what failed" report is now tied to a real release-adjacent event.

Original finding: zero code ties such a report to any release or deployment event — correct; this platform has no CI/CD deploy pipeline of its own.

**Closed:** `app/fleet/release_retrospective.py` reuses the exact same real event `main.py`'s doc-agent auto-trigger loop already uses to fire `changelog_agent`/`release_notes_agent` autonomously — local `main` HEAD movement — tracked under its own independent `SystemSetting` key (`doc_agent_last_sha:release_retrospective`) inside `_run_doc_agent_auto_trigger_once()`. Deliberately **not** an LLM agent, unlike its two siblings: every number in the report is a real `COUNT` from real `DevTask`/`EnhancementRequest` rows for the real commit-date range (derived from `git log <from>..<to>`, never guessed), and every sample is real stored text truncated, never paraphrased or invented — zero hallucination surface for a "what went well/what failed" claim. Writes a real markdown file to `docs/reports/retrospectives/RETROSPECTIVE_{sha}.md`.

Tested: `tests/test_batch15_release_retrospective.py` (real count aggregation, markdown formatting, zero-closed-tasks edge case, first-ever-run fallback).

## §117 Quality Score — improved, honestly still partial

**PARTIAL → PARTIAL, real scope widened from 4/9 to 5/9 categories.** `get_quality_score()` still genuinely combines only already-persisted category scores, still correctly excludes unavailable categories from the average rather than treating them as zero — the aggregator itself was never the problem; category coverage was.

**Closed:** the "agents" category quality_score.py's own comment explicitly described as "blocked by design decision, not blocked by missing data" now has that design decision made and wired:
- **Migration 042** (`agents_scores` table) + new `AgentsScore` model.
- `app/fleet/agents_score.py::compute_agents_score()` — the real join: `agent_runs.task_id → dev_tasks.repo_id` resolves which agent_names actually ran against a given repo; their own already-real, already-persisted baseline `benchmark_score` (`agent_benchmarks.is_baseline=True`) is averaged. An agent with real activity but no baseline yet is excluded from the average (never a fabricated 0), and a repo with no relevant agent baselines produces no row at all.
- `main.py::_agents_score_compute_loop()` — new leader-gated producer, matching the established scheduled-job pattern, since this category (unlike Tests/Architecture/Security) has no single natural per-run trigger event.
- Wired into `quality_score.py`'s `_category_registry()`; removed from `_NOT_YET_IMPLEMENTED`.

Tested: `tests/test_batch15_agents_score.py` (4 mock-based unit cases), `tests/test_batch15_agents_score_integration.py` (real-Postgres end-to-end: real join → real persistence → real read-back → real aggregation, proving migration 042 and the full pipeline work together, not just in isolation). The pre-existing `tests/test_stage4_cluster_q_quality_score_aggregation.py` was updated (2 stale assertions that hardcoded "agents" as `not_implemented`) — both now pass.

**Remaining 4 of 9 (documentation, performance, tools, prompts) are genuinely `not_implemented`, unchanged, and correctly still excluded from the average rather than faked.** Each would need its own real structured-data producer built from scratch — a separate, larger investment per category, not a wiring gap. Not claimed closed.

## §118 Safe Self-Improvement Lifecycle (8-step check)

| Step | Verdict | Evidence |
|---|---|---|
| Detect | **YES (unchanged)** | Scheduled scan loop. |
| Analyze | **YES (unchanged)** | Real tool-grounded findings. |
| Propose | **YES (unchanged)** | Real `EnhancementRequest` rows + diffed prompt versions. |
| Simulate impact | **NO → IMPOSSIBLE WITHIN CURRENT PRODUCT SCOPE.** | Would require a sandboxed execution/staging environment capable of running a hypothetical change under realistic conditions before human review — no such sandbox exists (this platform edits/reviews code in git worktrees; it does not stand up isolated running environments for arbitrary target applications), and building one is a distinct, large infrastructure project, not a bounded wiring fix. |
| Show plan | **YES (unchanged)** | Real dashboard/detail API. |
| Wait for approval | **YES (unchanged)** | Real RBAC-gated approval endpoint. |
| Implement | **YES, 4 of 7 agents (unchanged)** | Real write-capable apply handlers. |
| Test | **YES, pre-deploy only (unchanged)** | Real `run_tests` call + regression-baseline gate for prompt deploys. |
| Rollback if quality declines | **NO → YES.** | New `main.py::_prompt_auto_rollback_loop()` / `_run_prompt_auto_rollback_once()` — periodically re-runs `regression_detector.check_fleet()` (real, pre-existing, previously only used at pre-deploy time) against every currently-**deployed** prompt, and for any agent that (a) has a real deployed prompt version and (b) is currently regressed against its stored baseline, calls `prompt_registry.rollback()` automatically — no human gate, matching this step's own "automatic" definition (the human-operated path is the §110/111 dashboard route, kept separate on purpose). A per-role cooldown (`SystemSetting`-backed, `PROMPT_AUTO_ROLLBACK_COOLDOWN_HOURS`, default 24h) prevents oscillation from a still-warming metrics ring buffer immediately after a rollback. Tested: `tests/test_batch15_prompt_auto_rollback.py` (5 cases: real rollback trigger, no-deployed-version skip, not-regressed skip, cooldown guard, no-baseline-yet guard). |

**§118 overall: PARTIAL → 7 of 8 steps real (up from 6 of 8).** The one remaining gap (simulate-before-applying) is the single hardest, most speculative piece of the original 9-step wishlist and requires new sandbox infrastructure this pass correctly does not attempt to fabricate.

---

## Summary — Batch 15, post-gap-closure (2026-08-11)

Original pass: **YES: 7, PARTIAL: 9, NO: 6** (≈20 checkpoints).

**Post-gap-closure:**
- **YES:** 13 (§35/36 structure, §35/36 dependency-conflicts *[already-production-ready, Batch 16]*, §37, §74/113, §110/111 prompt-rollback, §114, §115, plus the individually-closed sub-checkpoints inside §75/105/112, §76, §117, §118 tables above)
- **PARTIAL (honestly, with the closed portion documented):** 4 (§35/36 overall, §75/105/112 overall, §117 overall, §118 overall — each now materially stronger than the original pass, with the specific remaining gap named rather than glossed over)
- **IMPOSSIBLE WITHIN CURRENT SCOPE (explained, not implemented):** 5 (§33, §34, §35/36 memory-leaks, §35/36 app-performance, §110/111 tool-evolution-for-executable-code, §118 simulate-impact) — six items listed, five sections, each with a concrete architectural reason, not a difficulty punt.
- **NO (unaddressed, out of this pass's scope):** 1 (§75/105/112's "approved prompts/MCPs/tools as organizational knowledge" — a real design decision intentionally not made in this pass, documented as future work rather than claimed done)

**What changed and why it's real, not cosmetic:**
1. **`FleetManager.select()`'s routing score now updates from real outcomes** (§37) — closes the batch's single most-emphasized finding: fleet routing decisions now genuinely reflect which agents actually succeed or fail over time, not a static constant from registration.
2. **Two dead-code rollback functions are now both reachable** — `PromptRegistry.rollback()` via a real human-operated API route (§110/111) *and* a real automatic trigger on detected regression (§118) — closing the loop the original audit's own "Production Enhancement Plan" called for verbatim.
3. **Two new first-class memory categories** (`preference`, `bug`) follow the codebase's own established per-category shape exactly, with real write paths, real retrieval, and real cross-agent surfacing via `memory_hook_node` — not shoehorned into an existing bucket.
4. **A deterministic capability-gap clustering tool** replaces "hope the LLM notices a pattern in raw history" with real, threshold-gated, error-sampled cluster data agent_advisor now reviews directly.
5. **The `agents` quality-score category's previously-undecided design question is now decided and shipped**, end-to-end tested against real Postgres including the new migration.
6. **A real, non-hallucinating release retrospective** is generated from real `DevTask`/`EnhancementRequest` counts on the same real event this platform already uses as its "release" proxy.

**43 new tests added** (`tests/test_batch15_*.py`), all passing, plus 3 stale pre-existing assertions corrected to match new, real behavior: 2 in `tests/test_stage4_cluster_q_quality_score_aggregation.py` (the "agents" category moving from not-implemented to implemented) and 1 in `tests/test_memory_context_query.py` (the sync bridge's failure-fallback dict shape gaining the 2 new category keys). `ruff check` and `black --check` clean on every changed file. Migration 042 applies cleanly against the real dev database. The full pre-existing test suite (2,967+ tests) was re-run after every change; the only failure surfaced was the 1 stale dict-shape assertion above, fixed. No existing functionality was removed or altered in a breaking way — every change is additive (new columns, new tables, new tools, new scheduled loops, new API routes) or a pure internal refactor with an identical external contract (the `success_rate` computation dedup in `api/registry.py`).

**Every item left as "Impossible within current scope" is accompanied by the specific architectural reason it cannot be safely bounded within this pass** — a missing sandbox execution environment, a fundamental difference between fresh-read-per-call text files and live-imported executable code, or the absence of any product surface to hang a feature off of — never a difficulty punt, and never conflated with the many items in this same batch that *were* closed because their supporting machinery already existed and only needed a real caller.
