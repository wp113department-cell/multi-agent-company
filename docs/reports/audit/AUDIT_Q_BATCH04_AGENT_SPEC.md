# Batch 4 — Agent Specification Audit, Capability Audit, Universal Skill Coverage

Covers §6, §7, §72. Evidence-only, file:line cited. Sampled 5 agents across categories: `coder.py` (coder-type), `pm.py` (PM-type), `qa.py` (QA-type), `security_reviewer.py` (guardian-substitute — **no agent literally named "guardian"/"ranger"/"sentinel" exists**), `chat_agent.py` (interactive-type).

---

## §6 Agent Specification Audit (per-agent scaffold check)

| Item | coder | pm | qa | security_reviewer | chat_agent | Verdict |
|---|---|---|---|---|---|---|
| Identity/Role/Responsibilities | Y | Y | Y | Y (no explicit header) | Y | **YES** — consistent, every role file has a "Non-Responsibilities" section |
| System prompt loaded from `backend/roles/<name>.md` | Y | Y | Y | Y | Y (separate local loader `_load_role`, not `base.py`'s) | **YES**, code-verified for all 5 — but chat_agent uses a duplicated second implementation |
| Skills / Tool List | Y | Y | Y | Y | Y (36 tools) | **YES** — real, distinct per-role allowlists |
| Memory | Y | Y | Y | Y | Y (separate async path) | **YES** — DB-backed for all 5, two different code paths |
| Knowledge Base (repo context) | Y | Y | Y | Y | Partial (live tools instead of context snapshot) | **YES/PARTIAL** |
| Planning Engine | Y | Y | Y | Y | **N** | **PARTIAL** — 4/5 real; chat_agent has none by design (interactive, not task-oriented) |
| Reasoning Loop | Y | Y | Y | Y | Y (own separate graph) | **YES** |
| Verification Loop | Y | Y | Y | Y | Y | **YES** — code-enforced via `state["verification"]`, not model-claimed |
| Self-Critique | Y (opted in) | **N** | Y (opted in) | **N** | N/A | **PARTIAL** — real mechanism exists but only 2/4 eligible agents opted in; not a fleet default |
| Recovery System | Y (outer retry+feedback) | graph-level only | graph-level only | graph-level only | tool-level try/except | **PARTIAL** — coder has real outer retry loop, others rely only on inner turn loop |
| Safety Layer | Y | Y | Y | Y | Y (+ HITL confirm) | **YES** |
| Learning Layer | Y | Y | Y | Y (imported, wiring not fully confirmed) | Y | **YES** |
| Configuration (via config.py) | Y | Y | Y | Y | Y | **YES** — no hardcoded models/paths in any of the 5 |
| Observability/Logging | Y | Y | Y | Y | Y (own streaming mechanism) | **YES** — two mechanisms, not unified |
| Metrics | Y | Y | Y | Y | Y (NOT fed into shared `fleet/metrics.RunMetrics`) | **PARTIAL** — chat_agent's metrics are tracked separately and don't feed the shared metrics span the other 4 use |

**§6 overall: PARTIAL.** The scaffold is real and consistently applied across the 4 `run_agent_graph`-based agents sampled. The two real gaps: (1) `enable_critique`/outer-retry adoption is inconsistent and explicitly incomplete per code comments ("ahead of a fleet-wide default flip"); (2) `chat_agent.py` is architecturally a second, independent implementation (own graph, own memory calls, own metrics, own role loader) that won't automatically inherit future upgrades made to the shared 76-agent path.

---

## §7 Capability Audit (from implementation, not prompts)

| Capability | Verdict | Evidence |
|---|---|---|
| Intelligent Understanding / Deep Instruction Analysis | **YES** | Real two-call Haiku planner (`_gather_facts_and_plan`, base_graph.py:581-641). |
| Smart Planning | **PARTIAL** | Real evidence-triggered replan node exists, but `enable_replanning` defaults False fleet-wide. |
| Context Awareness | **YES** | Real repo-context injection (`context_builder.build_context`) + real LLM-based condensation (`_condense_messages`, not silent drop). |
| Long-Term Memory | **YES** | DB-backed, dual-tier (fast ephemeral + durable). |
| Learn From Success / Failure | **YES** | Genuine feedback loop — lessons stored post-run are read by `memory_hook_node` at the START of future runs and injected into the prompt, not append-only logging. |
| Detect User Satisfaction | **YES** | `user_sentiment.py::detect_user_frustration()` — regex/heuristic + Jaccard repetition detection (not ML/NLP), tested. |
| Verification Before Reply | **PARTIAL** | Dedicated `reviewer.py` agent is real; `_make_critique_node` is real but gated behind `enable_critique`, not fleet default. |
| Honest Error Handling | **YES** | Explicit `error`/`status="failed"` returns, no fabricated success; `_GLOBAL_STANDARDS.md` mandates `limitation_type`+`proposed_alternative`, and this is graph-enforced (`_run_quality_gate`), not just prompt text. |
| Credential Handling | **YES** | `CredentialVault` — Fernet encryption at rest (with a warning-fallback if key unset), `SecretStr` fields, audit-logged key names only. Tested. |
| Step-by-Step Guidance | **PARTIAL** | Prompt-level only (`_GLOBAL_STANDARDS.md`, role files), no dedicated guidance-rendering code. |
| Cross-Agent Collaboration / Shared Learning | **YES** | Shared `LessonStore` singleton + shared `memory_embeddings` table, both read/written by every agent through the same hook. |
| Architecture Awareness | **YES** | Real `import_graph`/`call_graph` tools (`cross_file_graph.py`, `ast_engine.py`), used by `architecture_reviewer.py` and others. |
| Performance Awareness | **PARTIAL** | Real per-phase timing recorded (`record_phase_timing`); no evidence any agent reads its own timing data to change behavior — observational only. |
| Confidence Evaluation | **PARTIAL** | Real numeric confidence is set and a miscalibration flag is computed (`check_confidence_calibration`) — but it's recorded as a metric only; no code path changes control flow based on it. |
| Self Review | **YES** | `reflection_node` (base_graph.py:1039-1088), real second LLM call post-tool-execution, fleet default **on** (`enable_reflection=True`). |
| Continuous Improvement | **YES** | Same lesson/procedure-store mechanism as Learn-From-Failure. |
| Production Quality (lint/test gates) | **YES** | Real `mypy`/`ruff` subprocess checks outside the LLM loop in `coder.py`, retried on failure before accepting a patch. |

**§7 overall: mostly YES with real caveats** — the pattern across this whole batch is: the mechanism is genuinely implemented in code, but several of the more advanced behaviors (replanning, critique, confidence-driven routing) are wired as **opt-in flags that default off**, so "does the capability exist" (yes) and "is it active fleet-wide today" (often no) are different, both-true answers.

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
- Observability — `fleet/metrics.py::run_span`/`RunMetrics`, `activity_stream`, `audit_log`.

**Prompt-text-only or partial:**
- Step-by-Step Guidance — prompt sections only.
- Performance Analysis — recorded but not acted on.
- Deployment Planning — dedicated agents exist (`cicd_agent.py`, `docker_agent.py`, `infra_agent.py`, `rollback_agent.py`) but by CLAUDE.md's own permanent rule ("Deploy is a human action forever") these are plan/prepare-only, never execute — consistent with the safety rule, but means the *capability* is read-only-scoped, not an execution capability.
- Reliability Engineering / Maintainability — prompt-level only beyond the mypy/ruff gates already counted under Testing.

**Not directly verified this pass (agent files exist in inventory, not opened to confirm real vs. stub):** Refactoring (`refactor_agent.py`), Documentation (`readme_agent.py`, `api_docs_agent.py`, `changelog_agent.py`), Communication, Collaboration, Decision Making, Critical Thinking.

---

## Summary — Batch 4

- §6 (15 scaffold items): 10 YES, 5 PARTIAL, 0 NO
- §7 (16 capabilities): 9 YES, 7 PARTIAL, 0 NO
- §72: 10 skills confirmed real/code-backed, 3 confirmed prompt-only/partial, 6 not independently verified this pass (flagged, not scored)

**Findings worth flagging:**
1. **Advanced behaviors are real but opt-in-and-mostly-off**: replanning, self-critique, and confidence-driven routing are all genuinely implemented, tested mechanisms — but each is gated behind a flag that defaults to `False` or isn't consumed downstream. A reader of the code alone would reasonably conclude these are active; they aren't, fleet-wide, today.
2. **`chat_agent.py` is a structurally separate implementation** from the other ~76 agents (own graph builder, own role loader, own memory calls, own metrics). Any future fix or feature added to `base_graph.py`'s shared engine will not reach the interactive chat surface without a matching, manual change in `chat_agent.py` — this is the same architectural split flagged in Batch 1's sandboxing finding, now confirmed as a general pattern rather than an isolated bug.

**Production Enhancement Plan:** Before claiming "smart planning"/"self-critique"/"confidence evaluation" as fleet capabilities in any external-facing readiness score, either (a) flip `enable_replanning`/`enable_critique` to fleet defaults now that the mechanisms are tested, with per-agent opt-out for the few that shouldn't have them, or (b) explicitly scope readiness claims to "implemented, opt-in per agent" rather than "implemented." Given `chat_agent.py`'s divergence, prioritize either merging it onto `base_graph.py`'s shared engine or documenting the split as intentional so future changes don't silently miss the interactive path (as already happened with sandboxing in Batch 1).
