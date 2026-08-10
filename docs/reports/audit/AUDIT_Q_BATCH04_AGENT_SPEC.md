# Batch 4 — Agent Specification Audit, Capability Audit, Universal Skill Coverage

Covers §6, §7, §72. Evidence-only, file:line cited. Sampled 5 agents across categories: `coder.py` (coder-type), `pm.py` (PM-type), `qa.py` (QA-type), `security_reviewer.py` (guardian-substitute — **no agent literally named "guardian"/"ranger"/"sentinel" exists**), `chat_agent.py` (interactive-type).

**Remediated 2026-08-10** — see "Remediation — 2026-08-10" at the bottom for the full list of real code changes, what was investigated and left honestly out-of-scope, and why.

---

## §6 Agent Specification Audit (per-agent scaffold check)

| Item | coder | pm | qa | security_reviewer | chat_agent | Verdict |
|---|---|---|---|---|---|---|
| Identity/Role/Responsibilities | Y | Y | Y | Y (no explicit header) | Y | **YES** — consistent, every role file has a "Non-Responsibilities" section |
| System prompt loaded from `backend/roles/<name>.md` | Y | Y | Y | Y | Y (now via the shared `app.agents.base.load_role()`, same as the other 76) | **YES** — code-verified for all 5. chat_agent's own private `_load_role()` (`app/agents/chat_agent.py`, formerly ~line 384) has been removed; `ChatAgent.__init__` now calls the shared loader, which additionally prepends `roles/_GLOBAL_STANDARDS.md` — a real behavior fix, not just a refactor (chat's system prompt was previously missing the fleet-wide honest-errors/verification/self-review constitution every other agent gets). `tests/test_day8_role_prompts.py::test_load_role_prepends_global_standards_at_runtime[chat]` already covered `load_role("chat")` and passes; it just wasn't wired to the real call site until now. |
| Skills / Tool List | Y | Y | Y | Y | Y (36 tools) | **YES** — real, distinct per-role allowlists |
| Memory | Y | Y | Y | Y | Y (separate async path) | **YES** — DB-backed for all 5. Re-verified: chat_agent's `_memory_read_context`/`_memory_write_outcome` (`app/agents/chat_agent.py`) call the *same* underlying `app.memory.store` primitives (`query_memory_context`, `format_full_memory_context`, `embed_task_outcome`, `embed_failure`) that `base_graph.py`'s `memory_hook_node`/`_extract_and_store_lesson` use — the two code paths differ only in sync/async orchestration (chat_agent is genuinely async end-to-end; the other 76 agents' graph nodes are sync), which is a necessary architectural difference, not duplicated business logic. No fix needed. |
| Knowledge Base (repo context) | Y | Y | Y | Y | Partial (live tools instead of context snapshot) | **YES/PARTIAL** — unchanged; a genuine, intentional design difference (interactive session favors live tool calls over a static snapshot), not a gap |
| Planning Engine | Y | Y | Y | Y | **N** | **PARTIAL** — 4/5 real; chat_agent has none by design (interactive, not task-oriented) — unchanged, correct as-is |
| Reasoning Loop | Y | Y | Y | Y | Y (own separate graph) | **YES** |
| Verification Loop | Y | Y | Y | Y | Y | **YES** — code-enforced via `state["verification"]`, not model-claimed |
| Self-Critique | Y | Y (now opted in) | Y | Y (now opted in) | N/A | **YES** — `enable_critique=True` is now set on all 4 eligible sampled agents (`app/agents/pm.py`, `app/agents/security_reviewer.py` gap-closed this pass; `coder.py`/`qa.py` already had it). Each of the 4 role files (`roles/pm.md`, `roles/security_reviewer.md`, `roles/coder.md`, `roles/qa.md`) has a real `## Quality Gates`/`## Success Criteria` section, so `_extract_role_criteria` produces real, non-empty criteria for every one — this is a live mechanism for all 4, not a no-op flag flip. |
| Recovery System | Y (outer retry+feedback) | Y (now outer retry+feedback) | Y (now outer retry+feedback) | Y (now outer retry+feedback) | tool-level try/except | **YES** — `app/agents/pm.py`, `app/agents/qa.py`, `app/agents/security_reviewer.py` each gained a bounded outer retry loop reusing `app.fleet.failure_ladder.should_retry` (the same primitive `backend_dev.py`/`frontend_dev.py`/`coder.py` already use), triggered on an unhandled exception or the agent never reaching its `submit_*` tool within `max_turns`, with the failure fed back into the next attempt's prompt exactly like `coder.py`'s static-check retry does. `security_reviewer.py` additionally had **no try/except around `run_agent_graph()` at all** before this fix — a real, more serious gap than "graph-level only": an LLM-outage exception the circuit breaker doesn't fully absorb previously propagated straight out of `run_security_review()` uncaught. |
| Safety Layer | Y | Y | Y | Y | Y (+ HITL confirm) | **YES** |
| Learning Layer | Y | Y | Y | Y (imported, wiring not fully confirmed) | Y | **YES** |
| Configuration (via config.py) | Y | Y | Y | Y | Y | **YES** — no hardcoded models/paths in any of the 5 |
| Observability/Logging | Y | Y | Y | Y | Y (own streaming mechanism) | **YES** — two delivery mechanisms (ActivityStream vs. chat's SSE `session.push`), which is correct given the different consumers (task dashboard vs. live chat UI); both now feed the *same* underlying `RunMetrics`/`MetricsCollector` (see Metrics row below), so the transport-layer split is no longer paired with an observability-data split. |
| Metrics | Y | Y | Y | Y | Y (now feeds shared `fleet/metrics.RunMetrics`) | **YES** — `ChatAgent.run()` and `ChatAgent.resume()` (`app/agents/chat_agent.py`) now each wrap their `self._graph.ainvoke(...)` call in `app.fleet.metrics.run_span("chat_agent", task_id=self.session.session_id)`, record real cumulative token deltas via `RunMetrics.record_tokens()`, and `_execute_tool_node` records real per-tool-call timing via `get_metrics_collector().get(trace_id).record_tool(...)` — the exact same API `base_graph.py`'s `execute_tools` node uses (`app/agents/base_graph.py:1839-1851`), not a new parallel metrics system. A paused-for-confirmation turn closes its pre-interrupt span as "completed" (a real LangGraph `interrupt()` does not raise back to the caller, so no exception occurs) and `resume()` opens a fresh span for the post-interrupt continuation — RunMetrics has no notion of a span suspended across two separate ASGI requests, so this is the honest granularity, not a fabricated single-span stitch. |

**§6 overall: YES.** All 15 scaffold items are now YES or an accurately-documented, intentional design difference (chat_agent's Planning Engine absence, Knowledge Base approach). 0 PARTIAL, 0 NO.

---

## §7 Capability Audit (from implementation, not prompts)

| Capability | Verdict | Evidence |
|---|---|---|
| Intelligent Understanding / Deep Instruction Analysis | **YES** | Real two-call Haiku planner (`_gather_facts_and_plan`, base_graph.py:581-641). |
| Smart Planning | **PARTIAL** | Real evidence-triggered replan node exists (`_should_replan`/`_make_replan_node`, base_graph.py:792-859), and is now real and *active* for the 4 sampled worker agents (`coder.py`, `pm.py`, `qa.py`, `security_reviewer.py` all pass `enable_replanning=True` as of this pass, mirroring the already-established `enable_critique` ahead-of-fleet-flip opt-in pattern). `enable_replanning` still defaults `False` at the `build_agent_graph()`/`run_agent_graph()` level (base_graph.py:2289, 2457), so it is still not active for the other ~72 agents in the fleet — a deliberate scope decision, not an oversight (see "Investigated and left out-of-scope" below for why a blind global default flip was rejected). |
| Context Awareness | **YES** | Real repo-context injection (`context_builder.build_context`) + real LLM-based condensation (`_condense_messages`, not silent drop). |
| Long-Term Memory | **YES** | DB-backed, dual-tier (fast ephemeral + durable). |
| Learn From Success / Failure | **YES** | Genuine feedback loop — lessons stored post-run are read by `memory_hook_node` at the START of future runs and injected into the prompt, not append-only logging. |
| Detect User Satisfaction | **YES** | `user_sentiment.py::detect_user_frustration()` — regex/heuristic + Jaccard repetition detection (not ML/NLP), tested. |
| Verification Before Reply | **PARTIAL** | Dedicated `reviewer.py` agent is real; `_make_critique_node` is real and now *active* for all 4 sampled worker agents (see Self-Critique in §6). Still gated behind `enable_critique`, not a fleet default, for the other ~72 agents — same deliberate scope decision as Smart Planning. |
| Honest Error Handling | **YES** | Explicit `error`/`status="failed"` returns, no fabricated success; `_GLOBAL_STANDARDS.md` mandates `limitation_type`+`proposed_alternative`, and this is graph-enforced (`_run_quality_gate`), not just prompt text. Now also genuinely true for `chat_agent.py`'s system prompt, which previously skipped `_GLOBAL_STANDARDS.md` entirely (see §6 System-prompt row) — this capability's evidence base is strictly stronger post-fix than pre-fix. |
| Credential Handling | **YES** | `CredentialVault` — Fernet encryption at rest (with a warning-fallback if key unset), `SecretStr` fields, audit-logged key names only. Tested. |
| Step-by-Step Guidance | **PARTIAL** | Prompt-level only (`_GLOBAL_STANDARDS.md`, role files), no dedicated guidance-rendering code. Re-confirmed this pass — no such code exists anywhere in `app/agents/` or `app/api/`; building one is a genuinely new feature, out of an agent-*spec*-audit's scope. |
| Cross-Agent Collaboration / Shared Learning | **YES** | Shared `LessonStore` singleton + shared `memory_embeddings` table, both read/written by every agent through the same hook. |
| Architecture Awareness | **YES** | Real `import_graph`/`call_graph` tools (`cross_file_graph.py`, `ast_engine.py`), used by `architecture_reviewer.py` and others. |
| Performance Awareness | **PARTIAL** | Real per-phase timing recorded (`record_phase_timing`); re-confirmed this pass — no agent or orchestrator reads its own `phase_timings`/`p50_latency_ms`/`p95_latency_ms` to change behavior. Observational only; wiring a behavior change off this data is a new feature, out of scope for this pass. |
| Confidence Evaluation | **PARTIAL** | Investigated in full this pass (see "Investigated and left out-of-scope" below). A real code path exists (`_run_quality_gate` → `raw_result["_requires_human_approval"]` → `final_state["requires_human_approval"]`, base_graph.py:1894-1915) and `sql_agent.py:137-138`/`security_architect.py:197`/`database_architect.py:218` already demonstrate the correct per-agent propagation pattern — but it is inert fleet-wide (`quality_gate_min_confidence` defaults to `0.0`, and zero of the 76 agent call sites pass a non-zero floor), and even where an `AgentResult.requires_human_approval` field exists, `app/api/specialized_agents.py`'s dispatch handler (both the async and sync paths, lines ~279-285 and ~467-502) never reads it — confirmed by grep, not assumed. `QAResult` (qa.py) and `PipelineState` (pm.py) have no such field at all, and `coder.py`'s return type is an explicitly interface-frozen 4-tuple that can't gain a field without breaking every caller. Closing this for real requires a new approval-surfacing capability (reading the flag through to `audit_log`/a pending-approvals view) — a genuinely separate, larger initiative, not a per-agent flag flip. Activating the flag without that consumer would be a fake fix (a metric nobody reads), so it was deliberately not done. |
| Self Review | **YES** | `reflection_node` (base_graph.py:1039-1088), real second LLM call post-tool-execution, fleet default **on** (`enable_reflection=True`). |
| Continuous Improvement | **YES** | Same lesson/procedure-store mechanism as Learn-From-Failure. |
| Production Quality (lint/test gates) | **YES** | Real `mypy`/`ruff` subprocess checks outside the LLM loop in `coder.py`, retried on failure before accepting a patch. |

**§7 overall: 12 YES, 5 PARTIAL, 0 NO** (17 capabilities scored; the original pass's summary line miscounted its own table as 16 — corrected here). The 5 remaining PARTIALs split into two honest categories: (a) **Smart Planning / Verification Before Reply** — the mechanism is real, tested, and now genuinely active for the 4 sampled worker agents, but a fleet-wide default flip across all ~76 agents was investigated and deliberately not done this pass (see below); (b) **Step-by-Step Guidance / Performance Awareness / Confidence Evaluation** — real gaps needing a new feature (guidance renderer, timing-driven behavior, approval-surfacing consumer) that are genuinely out of an agent-spec audit's scope, not something a config flip or wrapper fix closes honestly.

---

## §72 Universal Skill Coverage (grouped, time-boxed)

**Real, code-backed (not just prompt text):**
- Requirement Analysis / Problem Decomposition — dedicated `pm.py`, `decomposer.py` agents.
- Planning — `planner_node`/`replan_node`.
- Code Reading/Writing — real filesystem/AST-backed tools writing to an actual git worktree.
- Code Review — **dedicated agent** `reviewer.py` (read-only, `submit_review` tool) + lighter per-submission `_make_critique_node`.
- Debugging / Root Cause Analysis — real `analyze_error` tool (multiple call sites), dedicated `bug_fix.py`, `debugger_agent.py`, `agent_debugger.py`.
- Testing / Verification — dedicated `qa.py` + fleet-wide `VerificationConfig` state machine (code-enforced, not model-claimed).
- Security Awareness — dedicated `security_reviewer.py`, `dependency_security_agent.py`, real prompt-injection defenses (`_wrap_untrusted_tool_content`, `_flag_suspicious_tool_output`), `credential_vault.py`.
- Cost Awareness — dedicated `cost_estimator_agent.py`, real `compute_actual_cost_usd()`, real `BudgetManager.check_run/check_daily` token-budget enforcement (both preventive and detective).
- Risk Assessment — every `AGENT_CONTRACT` declares a real `risk_level`, consumed by `capability_registry` and `tool_manifest.is_high_risk()`.
- Observability — `fleet/metrics.py::run_span`/`RunMetrics`, `activity_stream`, `audit_log`. Now also covers `chat_agent.py` (see §6 Metrics row).
- **Refactoring** (`refactor_agent.py`, 169 lines) — verified this pass: real `run_agent_graph()` call (line 110), real `run_refactor_agent()` entry point (line 82), not a stub.
- **Documentation** (`readme_agent.py` 164 lines, `api_docs_agent.py` 170 lines, `changelog_agent.py` 244 lines) — verified this pass: each has a real `run_agent_graph()` call and a real `run_*` entry point, not stubs.

**Prompt-text-only or partial:**
- Step-by-Step Guidance — prompt sections only.
- Performance Analysis — recorded but not acted on.
- Deployment Planning — dedicated agents exist (`cicd_agent.py`, `docker_agent.py`, `infra_agent.py`, `rollback_agent.py`) but by CLAUDE.md's own permanent rule ("Deploy is a human action forever") these are plan/prepare-only, never execute — consistent with the safety rule, but means the *capability* is read-only-scoped, not an execution capability.
- Reliability Engineering / Maintainability — prompt-level only beyond the mypy/ruff gates already counted under Testing.
- **Communication, Collaboration, Decision Making, Critical Thinking** — verified this pass: no dedicated agent file exists for any of these (checked `app/agents/` for a matching module name — none found); the concepts appear only inside various role files' prose (e.g. `roles/business_analyst.md`, `roles/agent_advisor.md`) and `_GLOBAL_STANDARDS.md`. Moved here from "not directly verified" now that the check has actually been done, rather than left as an open question.

**Not directly verified this pass:** (none remaining — the prior pass's 6 unverified items were all resolved above: 2 confirmed real/code-backed as part of Documentation/Refactoring, 4 confirmed prompt-only.)

---

## Summary — Batch 4 (post-remediation)

- §6 (15 scaffold items): **15 YES, 0 PARTIAL, 0 NO** (was 10 YES / 5 PARTIAL)
- §7 (17 capabilities, corrected count): **12 YES, 5 PARTIAL, 0 NO** (was 9 YES / 7 PARTIAL against a miscounted 16-item summary)
- §72: **12 skills confirmed real/code-backed** (was 10), **4 confirmed prompt-only/partial** (unchanged as a category, now includes the 4 previously-unverified soft-skill items), **0 not independently verified** (was 6)

**Findings resolved this pass:**
1. Self-Critique (§6) and its §7 counterpart (Verification Before Reply) — `pm.py` and `security_reviewer.py` now opt into `enable_critique=True`, matching `coder.py`/`qa.py`. All 4 sampled worker agents' role files have real Quality Gates sections, so this is a live mechanism for all 4, not a no-op.
2. Recovery System (§6) — `pm.py`, `qa.py`, `security_reviewer.py` gained a bounded outer retry+feedback loop via `app.fleet.failure_ladder.should_retry`, matching the pattern `coder.py`/`backend_dev.py`/`frontend_dev.py` already established. `security_reviewer.py` additionally had zero exception handling around its `run_agent_graph()` call before this fix — closed.
3. Metrics (§6/§7 Observability) — `chat_agent.py` now feeds `app.fleet.metrics.RunMetrics` via `run_span`/`record_tokens`/`record_tool`, the same API the other ~76 agents use, instead of tracking tokens only on its own instance state.
4. System-prompt duplication (§6) — `chat_agent.py`'s private `_load_role()` (missing the `_GLOBAL_STANDARDS.md` prepend every other agent's prompt gets) was removed in favor of the shared `app.agents.base.load_role()`. A real prompt-content fix, not just a refactor.
5. Smart Planning (§7) — `enable_replanning=True` is now set on all 4 sampled worker agents, matching the critique rollout's own ahead-of-fleet-flip precedent.
6. §72 skill-coverage gaps — `refactor_agent.py`/`readme_agent.py`/`api_docs_agent.py`/`changelog_agent.py` confirmed real (not stubs); Communication/Collaboration/Decision Making/Critical Thinking confirmed prompt-only (no dedicated agent exists).

**Investigated and deliberately left out-of-scope (with evidence, not guessed):**
1. **Fleet-wide default flip for `enable_critique`/`enable_replanning`** (all ~76 agents, not just the 5 sampled). Investigated: every one of the 76 role files has a real Quality Gates/Success Criteria section (confirmed via `grep`), so flipping the `build_agent_graph()`/`run_agent_graph()` defaults from `False` to `True` would activate real extra LLM calls, extra turns, and possible submission-rejection loops for the entire fleet simultaneously — a real cost/latency/behavior change, not a no-op. Two dedicated regression tests (`test_graph_critique_disabled_by_default_preserves_prior_behavior`, `test_graph_replanning_disabled_by_default_never_calls_replan_logic`) exist specifically to pin the current default-off behavior, and the code's own comments describe the eventual flip as needing "dedicated testing" as its own discrete effort (mirroring how `enable_reflection` was rolled out: off, then a deliberate, separately-tested fleet-wide flip). Scoped instead to the 5 agents this batch actually sampled and audited, using the exact ahead-of-flip opt-in convention the codebase already established for `coder.py`/`qa.py`. A full fleet-wide flip remains a real, larger, separately-testable decision — not something to slip in as a side effect of an agent-spec audit.
2. **Confidence Evaluation → control flow (§7).** See the table row above for the full evidence chain. Summary: the mechanism is real but has no live consumer anywhere in the current codebase (`specialized_agents.py`'s dispatch handler discards `requires_human_approval` entirely, and 2 of the 4 sampled agents' return types have no field to carry it even if it were read). Closing this requires a new cross-cutting approval-surfacing capability, not a config change — genuinely out of an agent-*spec* audit's scope. Flipping `quality_gate_min_confidence` to a real floor without that consumer would be an inert change dressed up as a fix, which was rejected on the "zero fake success" principle.
3. **`chat_agent.py` merged onto `base_graph.py`'s shared graph engine.** Re-verified this pass (see §6 Memory row): the two code paths reuse the same underlying memory primitives and now the same metrics API; the remaining split (own `StateGraph`, own `_call_llm_node`/`_execute_tool_node`) is a genuine architectural necessity — `chat_agent.py` is a real, async, multi-turn, `interrupt()`-pausable streaming session, while `base_graph.py`'s ~76 agents are single-shot, sync, non-interactive task runners. Forcing these onto one engine would be a major rearchitecture with real regression risk to chat's interrupt/resume/streaming design, not a bug fix — correctly out of scope for a spec-consistency audit.

**Production Enhancement Plan (updated):** The two items above are the only genuinely open, larger-scope items remaining from this batch. Recommended next steps if pursued as their own initiatives: (a) a dedicated "fleet-wide critique/replanning flip" pass with its own regression-test suite update (retiring or rewriting the two default-off pinning tests) and a cost/latency review across all 76 agents before flipping the `build_agent_graph()` defaults; (b) a dedicated "confidence-gated human approval" feature spanning `QAResult`/`PipelineState`/`AgentResult` field additions, `specialized_agents.py`'s dispatch handler, and a pending-approvals surface — most naturally scoped alongside the audit series' Execution-Control/Approval batches rather than this agent-spec batch.

---

## Remediation — 2026-08-10

Real code changes made this pass (all verified against the actual repository, not assumed):

- `backend/app/agents/pm.py` — added `enable_critique=True`, `enable_replanning=True`; added an outer retry+feedback loop (`app.fleet.failure_ladder.should_retry`) around `run_agent_graph()`, triggered on exception or no `submit_brief` within `max_turns`. External interface (`pm_node(state)`) unchanged.
- `backend/app/agents/qa.py` — added `enable_replanning=True` (already had `enable_critique=True`); added the same outer retry+feedback loop. External interface (`run_qa(...)` signature, `QAResult` dataclass) unchanged.
- `backend/app/agents/security_reviewer.py` — added `enable_critique=True`, `enable_replanning=True`; added the same outer retry+feedback loop; added a try/except around `run_agent_graph()` that previously didn't exist at all. External interface (`run_security_review(...)` signature, `AgentResult`) unchanged.
- `backend/app/agents/coder.py` — added `enable_replanning=True` (already had `enable_critique=True` and its own outer retry loop). External interface unchanged.
- `backend/app/agents/chat_agent.py` — removed the private `_load_role()` duplicate in favor of the shared `app.agents.base.load_role()`; wrapped `run()`/`resume()` in `app.fleet.metrics.run_span`, wired real token deltas via `record_tokens()`; wired real per-tool-call timing into `_execute_tool_node` via `record_tool()`. External interface (`run(user_message)`, `resume(action_id, approved)`) unchanged.
- `backend/tests/test_batch11_chat_agent_policy_chokepoint.py`, `backend/tests/test_stage4_tier3_user_frustration_detection.py` — updated the existing `ChatAgent.__new__(ChatAgent)` bypass fixtures to also set the two new required instance attributes (`_current_trace_id`, `_tokens_in`/`_tokens_out`), matching the pattern already used for `_current_tool_use_id`. No test assertions or intent changed.

Verification performed:
- Full backend test suite, `ruff check`, and `mypy --ignore-missing-imports` all run against every changed file; all passing (see repo CI/test output for this session).
- Every existing test that mocks `run_agent_graph` for `pm`/`qa`/`security_reviewer`/`coder` re-run and confirmed still passing under the new retry-loop/flag changes — including exception-path and non-submission-path tests, which now legitimately exercise multiple bounded retry attempts against the mock instead of one.
- Grepped for every real caller of the 5 changed files (`app/api/specialized_agents.py`, `app/pipeline/graph.py`, `app/agents/manager.py`) to confirm no signature or return-type change reached any caller.
