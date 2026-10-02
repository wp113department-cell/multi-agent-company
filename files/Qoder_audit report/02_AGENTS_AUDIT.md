# AUDIT 02 — MASTER AGENT AUDIT
## Gridiron AI Developer Department — every agent vs. the project's own contract

**Audit ID:** AGENT-02 | **Report file:** `files/Qoder_audit report/02_AGENTS_AUDIT.md`
**JSON sidecar:** `files/Qoder_audit report/json/AUDIT_02_AGENTS.json`
**Run date:** 2026-10-02
**Auditor:** Qoder (read-only audit — no code was modified)
**Baseline:** started from audit-01 baseline `846021aa` (2026-09-30); HEAD advanced to `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02) before evidence collection. All audit-02 evidence was gathered and re-verified against the current checkout at `c927c44b` (tracked worktree clean; only the untracked audit-report folders differ).
**Standards followed:** `files/Audit/00b_AUDIT_STANDARDS.md` (evidence schema + JSON sidecar + no-padding rule)
**Method:** AST scans over all 104 agent modules + runtime imports (capability registry, model router) + targeted file reads. Every finding cites file:line. Claims marked "runtime-verified" were executed against the real code in this checkout.

---

## 0. GROUND TRUTH — counts reconciled with evidence

`PROJECT.md` still does not exist (see Audit 01 §0); all "per PROJECT.md" counts below were re-derived from code.

| Metric | Claimed (audit brief / docs) | Actual (verified) | Evidence |
|---|---|---|---|
| Agent .py files | "~72 agents" | **105 files** (104 excl. `__init__.py`) | `ls app/agents/*.py` |
| Registered agents (capability registry) | ~72 | **85** | runtime: `_entries` after `ensure_all_agents_registered()` (capability_registry.py:158-181; main.py:1489-1491) |
| Capability tags | — | **170, zero duplicates** | runtime Counter over `_entries[*].capabilities` |
| Static API registry (`/api/specialized-agents`) | — | **65 entries** | specialized_agents.py:45-174 |
| Dynamic-discoverable beyond registry | — | **7 agents** | specialized_agents.py:199-244 `_discover_agent_fn` (AGENT_CONTRACT + exactly one non `_scan`/`_apply` run fn) |
| Role files (`backend/roles/`) | "67 role files" | **86 = 85 roles + `_GLOBAL_STANDARDS.md`** | `ls roles/*.md` |
| Role files with all 7 role-specific sections | — | **85/85** | section scan (Non-Responsibilities, Success Criteria, Failure Conditions, Output Contract, Quality Gates, Edge Cases, Escalation) |
| Role files with a Karpathy variant | Day 6A | **55/85** (15 Engineering, 18 Review, 9 Design, 13 Analysis) | `grep "Karpathy .* Principles" roles/*.md` (see AGENT-02-003) |
| `VerificationConfig` instances | — | **93** | AST scan; only `executive` (0,0) and `manager` (none) opt out — both legitimate |
| `run_agent_graph` call sites in `app/agents/` | 131 (audit 01) | **90** in agent files (131 repo-wide incl. api/pipeline) | AST scan |
| `submit_*` tools | — | **27 files** in `app/tools/agents/` | `ls` |
| agent_models.json entries | "72" | **86** (85 registered agents all covered + 1 `groq_adapter` row) | runtime route() cross-check |
| Model route mismatches (json vs router) | — | **0** | runtime `get_model_router().route(name)` for all 85 |

**Reachability buckets (no module-level orphans among real agents):**
- pipeline-graph nodes: `pm`, `architect`, `decomposer` (pipeline/graph.py:12-14)
- static callers: coder, planner, qa, reviewer, backend_dev, frontend_dev, bug_fix, manager, executive, research — the appendix table states each module's exact path (note: `docs` is registry-API-only despite the static-sounding name)
- registry-API only: 51 of the 65 static entries (zero static callers; dispatched via POST /api/specialized-agents/{name}/run — verified in Audit 01 that the frontend never calls it)
- dynamic-API only: `agentic_ai_architect`, `mcp_developer_agent`, `mobile_dev`, `prompt_engineer_agent`, `roadmap_agent`, `tech_advisor_agent`, `ux_design_agent`
- autonomous scan-loop: 8 agents (main.py:143-221, `_fleet_agents_scan_loop`; interval `fleet_scan_interval_hours`, disabled when 0) — `agent_performance_reviewer`, `agent_debugger`, `agent_advisor`, `knowledge_curator`, `quality_auditor`, `architecture_reviewer`, `dependency_security_agent`, `monitoring_agent`
- human-approved APPLY phase: 4 agents (`agent_debugger`, `agent_performance_reviewer`, `knowledge_curator`, `quality_auditor`) via fleet_dashboard.py:331-342
- runtime-created: `temporary_agent` (TemporaryAgentPool, dynamic_agent_runtime.py:13); meta: `barot_agent` (gap-fill planner, no capability of its own — capabilities=[] by design)
- infra (not agents): 17 modules (base, base_graph, tools, guardrails, guidance, delegation, conflict_resolution, agent_result, monitoring_handlers, output_parsers, role_detection, static_checks, tool_security, user_sentiment, gemini_adapter, groq_adapter, bhaskar_sandbox)

**No dead agents were found** — every non-infra module has at least one real (non-test) reachability path. Two agents (`prompt_engineer_agent`, `ux_design_agent`) remain reachable only by the raw API with an exact capability string no product surface sends (cross-ref ARCH-01-003).

---

## 1. Executive summary

The agent layer is structurally the strongest part of the system so far audited: 85 registered agents, 170 globally-unique capability tags (runtime-proved, zero duplicates), 93 verification configs with zero dead enforcement keys, 85/85 role files carrying all seven required sections, zero hardcoded model strings (all routing flows through `model_router.py`, zero json-vs-router mismatches), explicit SDK timeout/retry configuration, bounded retry loops that re-feed the actual error text, fail-closed QA consumption defaults, a real policy chokepoint for write/bash tools, and a genuinely wired image pipeline (four named agents receive real Anthropic content blocks). Two real problems: (1) **`bhaskar_agent` — the tool-synthesis sub-agent wired into 8+ agents' tool lists and the chat dispatcher — fails 100% of the time in production** because it passes `role_name="bhaskar_agent"` but `roles/bhaskar_agent.md` does not exist; the failure is caught and returned as `ok=false`, and every test mocks `run_agent_graph`, so CI stays green (runtime-proved). (2) Submission payloads are JSON-schema-validated at the shared chokepoint but violations are recorded as a warning and **not rejected** (no pydantic anywhere in the 27 submit tools). Both are small fixes.

---

## 2. Layer score

**Score: 80 / 100**

Deductions: one High (a fully broken, default-enabled feature, AGENT-02-001), one Medium (trust-boundary validation is warn-only, AGENT-02-002), two Lows (Karpathy coverage inconsistency, un-locked module-level chat dict). Everything else on the brief's Phase 1/2/3B checklists verified clean with evidence (see §4-§6).

---

## 3. Findings (evidence schema)

### AGENT-02-001 — [HIGH] `bhaskar_agent` is 100% broken in production: `role_name="bhaskar_agent"` has no role file; every invocation returns `ok=false`

- id: AGENT-02-001
- severity: High
- file: `backend/app/agents/bhaskar_agent.py` (+ missing `backend/roles/bhaskar_agent.md`)
- location: `run_bhaskar_agent` → `run_agent_graph(role_name="bhaskar_agent", ...)`
- line: bhaskar_agent.py:186-187; base_graph.py:3449 → 1737 (load_role); base.py:39-41 (raise); caught at bhaskar_agent.py:205-215
- finding: `load_role()` raises `FileNotFoundError` for a missing `roles/<name>.md` (base.py:39-41). `build_agent_graph` calls `_make_call_llm_node` unconditionally (base_graph.py:3449), which calls `load_role(role_name)` at node-construction time (base_graph.py:1737). There is no `roles/bhaskar_agent.md` (`ls roles/ | grep -i bhaskar` → empty). The exception propagates out of `run_agent_graph` and is caught by `run_bhaskar_agent`'s own `except Exception` (bhaskar_agent.py:205-215), which returns `{"ok": False, "error": "bhaskar_agent run failed: Role file not found: .../roles/bhaskar_agent.md"}`. Result: **every** bhaskar_tool call fails, with zero tokens spent, on every path.
- evidence: **Runtime-proved in this checkout** (no LLM call needed — it fails before any API call): `.venv/bin/python -c "from app.agents.bhaskar_agent import run_bhaskar_agent; print(run_bhaskar_agent('Write a script that prints hello','','/tmp'))"` → `{'ok': False, 'code': '', 'result_summary': '', 'tested_output': '', 'error': 'bhaskar_agent run failed: Role file not found: /home/pc-117/Documents/CRR2906/backend/roles/bhaskar_agent.md', 'tokens_in': 0, 'tokens_out': 0}` (verbatim re-capture at HEAD `c927c44b`). `load_role('bhaskar_agent')` independently raises the same. The feature is default-enabled (`bhaskar_tool_enabled: default=True`, config.py:1802-1805) and wired into `chat_agent.py:115,4302-4312`, `tools.py:78-80,1348,1668-1674,1693`, and ≥8 agents' tool lists (`bug_fix.py:55`, `mcp_developer_agent.py:69`, `migration_agent.py:51`, `user_story_generator.py:39`, `evaluation_agent.py:39`, `devex_agent.py:43`, `ux_design_agent.py:55`, `test_coverage_agent.py:46`). Tests never exercise the real path — `tests/test_bhaskar_tool.py:983-1026` monkeypatches `run_agent_graph`, so CI stays green. The Groq bypass's `except FileNotFoundError` (base_graph.py:3990-3995) does not help: production runs `USE_GROQ=false` (conftest.py:66 forces it in tests; default in config), so the normal graph path raises.
- production_impact: The advertised "on-demand tool synthesis" capability silently never works: agents and chat users asking for a missing tool always get the structured failure instead of a generated script. Any feature work, docs, or demos relying on bhaskar_tool are non-functional while appearing wired, tested, and enabled.
- confidence: High (runtime proof + static chain)
- recommendation: Add `backend/roles/bhaskar_agent.md` (with the standard 7 sections + Karpathy variant) — or, if a role file is intentionally unwanted, extend the graph to accept an inline system prompt and pass one here. Add a regression test that asserts `load_role()` succeeds for every `role_name=` literal passed to `run_agent_graph` anywhere in `app/` (a 10-line AST/grep test would have caught this class).
- effort: Small

### AGENT-02-002 — [MEDIUM] `submit_*` payloads are schema-validated but violations never reject; no pydantic in any of the 27 submit tools

- id: AGENT-02-002
- severity: Medium
- file: `backend/app/agents/base_graph.py` (chokepoint) + `backend/app/tools/agents/submit_*.py` (27 handlers)
- location: `_make_execute_tools_node` submit handling
- line: base_graph.py:2879-2893 (validate), 2894-2906 (enforce_in_result override), 2920-2950 (citation check)
- finding: The brief asks whether submit payloads are validated against a Pydantic model or trusted via `dict.get(...)`. Ground truth: **0 of 27** submit-tool files use pydantic/BaseModel (`grep -l "BaseModel\|pydantic"` → 0). The handlers themselves mostly do `dict.update(inp)` / read via `.get()` (e.g. submit_qa_result.py:114-116 `qa_result.update(inp); return "QA result submitted"`). Framework-level mitigation exists: the execute_tools chokepoint runs `jsonschema.validate(instance=raw_result, schema=<tool input_schema>)` — but on `ValidationError` it only logs a warning and attaches `_validation_warning` to the result (base_graph.py:2883-2893); the submission is still accepted and trusted downstream. Stronger mitigations exist alongside: `enforce_in_result` overwrites model-claimed result fields with harness-computed truth (base_graph.py:2894-2906), file:line citations are verified against the real repo (2920-2950), and a quality gate runs (2952-2974). Sampled consumer `qa.py:257-272` uses fail-closed defaults (missing → "failed"/0/False), which is the safe direction.
- evidence: `ls app/tools/agents/submit_*.py | wc -l` → 27; `grep -l "pydantic\|BaseModel" app/tools/agents/submit_*.py | wc -l` → 0; base_graph.py:2885-2893 shows warning-only handling; qa.py:260-272 shows fail-closed `raw.get(...)` defaults.
- production_impact: A malformed-but-accepted submission (wrong types, missing required-by-schema keys) flows into result dicts; consumers that were not individually audited may default differently than qa.py's fail-closed pattern. Since `_validation_warning` is recorded but nothing downstream is known to read it (no consumer found in the sampled paths), a schema-invalid submission is materially indistinguishable from a valid one at most call sites.
- confidence: High (behavior), Medium (downstream blast radius — one consumer sampled)
- recommendation: Decide explicitly: either (a) reject submissions that fail their declared input_schema (at least for high-risk/coder-class agents), or (b) document the deliberate warn-only choice next to the jsonschema call and make at least the quality gate read `_validation_warning`. Optionally adopt pydantic models per submit tool for typed consumption.
- effort: Small–Medium

### AGENT-02-003 — [LOW] Karpathy principles coverage is inconsistent: 55/85 role files, missing on several review/analysis-class agents

- id: AGENT-02-003
- severity: Low
- file: `backend/roles/*.md`
- location: role files of `monitoring_agent`, `security_architect`, `business_analyst`, `research`, `evaluation_agent`, `quality_auditor`, `knowledge_curator`, `agent_debugger`, `agent_advisor`, `pm`, `sprint_planner`, `manager` + 17 more
- line: n/a (per-file)
- finding: Day 6A's four Karpathy variants exist and are correctly category-mapped where present — "Karpathy Review Principles" (18 files: reviewer, security_reviewer, style_reviewer, performance_reviewer, architecture_reviewer, qa, devops, infra_agent…), "Engineering" (15: coder, backend_dev, frontend_dev, bug_fix, refactor_agent, sql_agent, migration_agent, cleanup_agent, docker_agent, cicd_agent…), "Design" (9: architect, decomposer, planner, api_designer_agent, database_architect, schema_agent…), "Analysis" (13: debugger_agent, incident_responder_agent, rollback_agent, cost_estimator_agent…). But 30 role files have **no** Karpathy section at all, including agents whose direct category peers have one: `monitoring_agent` (peer infra_agent → Review), `security_architect` (peer security_reviewer → Review), `business_analyst`, `evaluation_agent`, `quality_auditor`, `knowledge_curator`, `agent_debugger` (whose own docstring says it follows quality_auditor's pattern).
- evidence: `grep -l "Karpathy .* Principles" roles/*.md | wc -l` → 55; full variant membership lists in scan output; `monitoring_agent.md` contains none (`grep -ri karpathy roles/monitoring_agent.md` → empty).
- production_impact: Prompt-level behavioral variance between same-category agents; a reviewer reading role files cannot rely on a uniform quality baseline. No runtime breakage.
- confidence: High
- recommendation: Add the matching variant section to the 30 files (or document deliberately that advisory/doc/coordination roles are exempt).
- effort: Small (docs only)

### AGENT-02-004 — [LOW] `_chat_agents` module-level dict is mutated without a lock (no real race today; risk on any future thread caller)

- id: AGENT-02-004
- severity: Low
- file: `backend/app/agents/chat_agent.py`
- location: module-level session map
- line: 412-420 (`_chat_agents: dict[str, "ChatAgent"] = {}`, `get_or_create_chat_agent`), 437 (`delete_chat_agent`)
- finding: The brief's known-fixed instance (`_background_processes` moved per-instance) is confirmed still per-instance (chat_agent.py:882 `self._background_processes: dict[int, subprocess.Popen[str]] = {}`; also `self._stop_requested`, `self._current_tool_use_id`, `self._tokens_in/out` — all instance state). However the session→agent map itself is a module-level dict with a check-then-set (`if agent is None: … _chat_agents[session.session_id] = agent`) and a pop, **with no lock** (no `_chat_agents_lock`, no `threading.Lock`). Today all four call sites are async route handlers in the single process/event loop (chat.py:200, 343, 380, 426), and there is no `await` between check and set, so it is serialized in practice.
- evidence: chat_agent.py:412-420, 437; callers: `grep -rn "get_or_create_chat_agent\|delete_chat_agent" app/` → only `app/api/chat.py` routes.
- production_impact: None today. If any caller later invokes these from a worker thread (e.g. `asyncio.to_thread`, sync context), concurrent get/create can leak two ChatAgents for one session, orphaning background processes the second instance can't stop.
- confidence: High (pattern), Medium (impact scenario)
- recommendation: Add a small lock around get/create/pop, or add a comment documenting the event-loop-only invariant.
- effort: Small

---

## 4. Phase 1 checklist results (aggregate; full table in appendix)

| Check | Result | Evidence |
|---|---|---|
| AGENT_CONTRACT with real input_types/output_types | 86/87 real agents have contracts; exceptions deliberate: `bhaskar_agent` (docstring: intentionally no contract, not selectable), `temporary_agent` (runtime-created; docstring), + 17 infra modules | scan `/tmp/qoder_agent_scan.txt`; bhaskar_agent.py:1-28; temporary_agent dispatch via dynamic_agent_runtime |
| VerificationConfig with non-empty enforce_in_result | 93 configs; only `executive` (0,0 — no tools, pure LLM, per brief's own exception) and `manager` (none — pure orchestrator, per brief's own exception) lack one. No other agent silently lacks a config | AST scan of all 104 files |
| enforce_in_result keys reachable (dead-key check) | **0 dead keys** after correcting the check to the right-hand side (verif key must be settable via set_by/initial/command_patterns; left-hand fields are *overwritten* at submission per base_graph.py:2894-2906). An initial version of this scan flagged 4 (cicd/docker/refactor/sql agents) — disproven: e.g. cicd_agent.py:70 `enforce_in_result={"lint_passed": "lint_ran"}` and `lint_ran` is set by bash (line 66) | AST scan (corrected) + base_graph.py:2894-2906 semantics read |
| Capability tags globally unique | **Runtime-verified zero duplicates** (170 tags over 85 entries). The two historical collisions (business_analyst/user_story_generator, changelog_agent/release_notes_agent) show no regression and no new collision exists | runtime `Counter(_entries[*].capabilities)` |
| `_register()` called at import time | Present in every real agent module except `bhaskar_agent` (deliberate) | scan; e.g. coder.py:290-312, qa.py:356-388, chat_agent.py:572-594 |
| Role file exists at the loaded path | 85/85 real agents that load role files have one; `chat_agent`→`roles/chat.md`; exceptions: `bhaskar_agent` (none — but this is finding AGENT-02-001, because it *does* load one), `barot_agent`/`temporary_agent` exceptions checked: barot never calls `load_role` (own inline API call, no `load_role` reference in file), temporary_agent has `roles/temporary_agent.md` | scan + `load_role` traces |
| Role files non-trivial + 7 role-specific sections | 85/85 contain all 7 sections; sizes 100-200 lines | section scan |
| Read-only tool scope (reviewer, security_reviewer, architecture_reviewer, monitoring_agent + auditor class) | The four named agents have **no** write_file/edit_file/bash (scan `write=[]`). Scan/apply pairs separate scopes by tool-list constant: e.g. quality_auditor.py — `SCAN_TOOLS` (line 166, read-only; scoped bash handler constructed with `read_only=True` at line 137) vs `APPLY_TOOLS` (line 102); scan called with SCAN_TOOLS (line 188). Doc-writer agents (readme, api_docs, changelog…) hold write_file by design (their output *is* .md artifacts) | scan + quality_auditor.py read |
| Coder-class self-correction wired | coder.py: bounded attempt loop; on check failure `check_error` is appended to the next attempt's message (`[RETRY n] Previous attempt failed checks:\n{check_error}`, coder.py:172-176) — a real change per attempt, not a blind re-run; final attempt returns the error (274-280). Static check = mypy+ruff via `run_python_checks` (coder.py:112-115, call at 257; backend_dev.py:131 with black=True). Retry counter is a local loop variable inside `run_coder` — no cross-run leakage | coder.py read + AST |
| Model routing (json tier vs runtime route) | **0 mismatches** across all 85 registered agents (runtime `route()` vs agent_models.json). Router wins over passed-in model at run time (base_graph.py:3743-3760). **Zero hardcoded model strings**: `grep -rn '"claude-' app/agents/*.py` → 0 hits | runtime script + grep |
| Fleet OS flags set deliberately | Coder-class call sites pass them explicitly (coder.py:191-213: planning/memory/reflection/lesson/critique on, replanning resolved by fleet default); read-only scan agents pass `enable_lesson=False`-equivalent contexts where they never mutate code (e.g. bhaskar_agent.py:194-199 sets planning/memory/reflection/lesson all False deliberately) | sampled call sites |
| task_id threaded (Day-18 regression check) | 76/90 agent-file call sites pass `task_id=`. The 14 without: 13 are the autonomous scan/APPLY agents (no dev_task exists — base_graph handles synthetic ids, base_graph.py:3868-3874) and `bhaskar_agent` (runs from chat context). No call site passes a trace id as task_id (the Day-18 bug shape is absent) | AST scan of all 90 sites |
| Dispatched from a real path | 100% of real agents reachable (buckets in §0); no dead agents. API-only agents are a product-surface gap (ARCH-01-003), not an orphaned-code gap | classification script over call sites + main.py:165-208 + fleet_dashboard.py:331-342 |

---

## 5. Phase 2 — cross-agent consistency

- **Read-only auditor uniformity:** the review-class agents (`reviewer`, `security_reviewer`, `architecture_reviewer`, `performance_reviewer`, `style_reviewer`, `tech_debt_agent`, `security_architect`, `database_architect`, `evaluation_agent`, `sprint_planner`, `business_analyst`) uniformly have `write=[]` and `enforce_in_result` with a single verification key set by the tool their role requires (e.g. reviewer.py `set_by={"git_diff": "diff_reviewed"}`; qa.py `set_by={"bash": "tests_run"}` + `command_patterns` gate so only a test-runner-looking command counts). VERIFIED uniform in the sampled set.
- **Karpathy variants:** correctly categorized where present — see AGENT-02-003 for the 30-file gap.
- **Policy engine routing:** both execution paths enforce policy — (a) legacy/hybrid path `run_agent()` calls `_enforce_policy` before every tool execution in all three backends (base.py:61-73 def; calls at 207, 314, 408); (b) primary LangGraph path: `_policy_check` (base_graph.py:1042-1096) wraps `check_path`/`check_command` (imported from `app.agents.guardrails`, line 41) and additionally `check_backend_framework_governance` (line 1096). No agent holds deploy/kubectl/raw-prod-credential tools in its declared list (tool lists cross-checked in the scan; `delete_file` appears only in `cleanup_agent` — consistent with its role). VERIFIED CLEAN.

---

## 6. Phase 3 / 3B — prompt quality and deep reliability (all cited)

**Prompt quality (spot-audit of structure across all 85 + reads of chat/reviewer/research/docs):**
- Injection-resistance scan: `grep -rniE "obey|follow (any|all|the) instruction|instructions? (found|contained) in|treat .* as instruction|ignore (previous|above)" roles/` → **zero hits**. No role file instructs the model to trust file/issue contents as instructions.
- `_GLOBAL_STANDARDS.md` (133 lines) carries the 11-section constitution (Operating Loop, Anti-Hallucination, Context Management, Engineering Principles, Security Guidelines, Reasoning, Error Handling, Escalation, Communication, Output Contract Discipline, Production Quality Bar) and is prepended to every role by `load_role()` (base.py:43-45). All 85 role files add all 7 role-specific sections (version scan above).
- Web-access scoping: `web_search` appears in 7 role files; `roles/research.md:17,40` explicitly scopes it ("Use web_search if available — fall back to codebase reading if not").

**Model selection & fallback (per brief, answered from this codebase):**
- Model comes from the router, not hardcoded (see Phase 1 table; base_graph.py:3748-3751 even applies `cost_mode.cap_model`).
- Fallback story, stated precisely: **same-provider retry only.** The Anthropic SDK client is constructed with `timeout=settings.llm_call_timeout_seconds` (default 300.0, config.py:139-144) and `max_retries=settings.llm_call_max_retries` (default 3, config.py:145-147) at base.py:54-58 (the same constructor is used by the graph path via `_make_client`, base_graph.py:1847). Groq/Gemini are **static selection switches** (`USE_GROQ`/`USE_GEMINI`, base.py:102-123; base_graph.py:3928 bypass), not failover targets — there is no Anthropic→Groq provider-level fallback anywhere in the agent run path. This is a design fact, not a defect, but ops should know a prolonged Anthropic outage stops all runs (after 3 SDK retries × timeout).
- Timeout: explicit and enforced on the SDK call itself (not just `budget_manager`) — VERIFIED.

**Retry & self-correction:** see coder row in §4 (error text re-fed; bounded; local counter — no leakage across runs; `retry_count` lives in per-thread LangGraph state, base_graph.py:3982).

**Structured output & validation:** AGENT-02-002 (warn-only jsonschema at base_graph.py:2883-2893; truth-override 2894-2906; citations 2920-2950; quality gate 2952-2974). `executive.py`'s plain-JSON contract has a real error path: `_parse_json` raises ValueError (executive.py:96), caught at 156-157 → returns `("", [], "JSON parse error: ... — raw: ...")`; the LLM call itself is also wrapped (146-147). VERIFIED CLEAN.

**Tool permission matrix:** derived from the scan (`write` column in appendix). Matrix summary: read-only (no write/bash): reviewer, security_reviewer, architecture_reviewer, performance_reviewer, style_reviewer, tech_debt_agent, security_architect, database_architect, business_analyst, evaluation_agent, sprint_planner, planner, architect, pm, decomposer, agent_advisor, monitoring_agent. bash-only: qa, devops. delete-capable: cleanup_agent only (role-consistent). write doc-artifact agents: the doc-writer family (expected). No violations found against the brief's named set.

**Race conditions:** AGENT-02-004 (chat map); the two known-fixed patterns are confirmed fixed: per-instance `_background_processes` (chat_agent.py:882) and per-run graph state. `base_graph` module globals are init-once resources (`_agent_checkpointer` base_graph.py:65-96; `_lesson_store` 683) — not per-request mutable state.

**Inter-agent handoffs (traced one real failure path end-to-end):** manager.py:755-799 — QA failure: `qa_errors = qa_result.errors or [qa_result.summary]` (778-779); published to events (781-794, payload truncates to `errors[:3]` for the dashboard **only**); the full `qa_errors`/`retry_context` is fed back into the next dev attempt per the loop's own contract (comments 890-947 document the identical mechanism for reviewer findings and security/architecture gate findings, T2-B5). Reviewer blocking → same retry mechanism; verdict non-blocking → `subtask_status="completed"` (936-937). The actual error text is **not** dropped between handoffs.

**Memory synchronization:** lessons are persisted best-effort via `_persist_lesson_async` (non-blocking DB write, base_graph.py:310-322); `memory_hook_node` queries memory at run **start** — so lesson visibility across agents is next-run by construction, and in-run coordination happens through explicit manager-passed context. This is the design; no in-same-run cross-agent memory read was found (report accurately: next-run-only, by design).

**Multimodal (4 named agents):** the full chain is real — `run_agent_graph(images=…)` builds genuine Anthropic content blocks: `initial_content = [{"type": "text", "text": initial_message}] + [{"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}} for img in images]` (base_graph.py:3726-3741), threaded from `task_images` at the entry points (api/agents.py:550, 719, 957) into pm.py:187, architect.py:181, frontend_dev.py:286, reviewer.py:179 (plus coder.py:181, planner.py:181, manager.py:610/844/1653). VERIFIED END-TO-END.

**read_pdf bounding:** bounded — `max_pages` input (default 20) with `pdf.pages[:max_pages]` slicing (read_pdf.py:71-74, 92, 99); path validated against the worktree (`check_path_in_worktree`, line 88). No per-page character cap, but page count is bounded — VERIFIED bounded.

**Emotion/intent:** no agent claims an emotion model; handling is (a) prompt-level de-escalation guidance in `roles/chat.md:135-150`, and (b) a real, deliberately-bounded heuristic detector `app/agents/user_sentiment.py` (regex patterns; module docstring explicitly disclaims NLP accuracy), **actually wired** into the chat loop — `detect_user_frustration` called at chat_agent.py:4813, emits an SSE `user_sentiment` event (4817) and a `frustration_directive` (4825-4827). Reported exactly as designed: bounded heuristic + prompt guidance, not fabricated sentiment analysis.

---

## 7. Verdict and fix order

**Verdict: READY** — the agent layer is fundamentally sound; fix AGENT-02-001 before relying on bhaskar_tool / chat tool-synthesis (it is enabled by default and currently fails 100%), and make an explicit decision on AGENT-02-002.

Fix order: (1) AGENT-02-001 add `roles/bhaskar_agent.md` + regression test for all `role_name` literals [Small]; (2) AGENT-02-002 decide warn-vs-reject for schema-invalid submissions [Small–Medium]; (3) AGENT-02-003 Karpathy sections for the 30 files [Small]; (4) AGENT-02-004 lock or document `_chat_agents` [Small].

## Appendix — full agent scorecard (104 modules)

Columns: contract = AGENT_CONTRACT present (values: YES / NO / none(deliberate)); vcfg = VerificationConfig present at module level; reg = present in the static `/api/specialized-agents` `_REGISTRY` at runtime (65 entries = 59 direct module-name matches + 6 alias keys — `arch_reviewer`→architecture_reviewer, `docs_agent`→docs, `executive_agent`→executive, `qa_agent`→qa, `research_agent`→research, `reviewer_agent`→reviewer; a "-" module can still be in the fleet capability registry and/or reachable another way); role.md = role file at the loaded path; karp = Karpathy section present; write = W write_file/edit_file (some also hold bash), B bash-only, "-" none; reachability = every real non-test path found (buckets: pipeline-graph, static caller, registry-API = POST /{name}/run, dynamic-API, scan-loop, apply-API, chat-routes, temp-pool, gap-fill; infra = support module, not an agent).

| agent module | contract | vcfg | reg | role.md | karp | write | reachability |
|---|---|---|---|---|---|---|---|
| accessibility_agent | YES | Y | Y | Y | Y | W | registry-API |
| agent_advisor | YES | Y | - | Y | - | - | static, scan-loop |
| agent_debugger | YES | Y | - | Y | - | W | scan-loop, apply-API |
| agent_performance_reviewer | YES | Y | - | Y | - | W | scan-loop, apply-API |
| agent_result | NO | - | - | - | - | - | infra |
| agent_roster_doc_agent | YES | Y | Y | Y | - | W | registry-API |
| agentic_ai_architect | YES | Y | - | Y | Y | W | dynamic-API |
| ai_engineer | YES | Y | Y | Y | Y | W | registry-API |
| api_designer_agent | YES | Y | Y | Y | Y | W | registry-API |
| api_docs_agent | YES | Y | Y | Y | - | W | registry-API |
| architect | YES | Y | - | Y | Y | - | pipeline-graph |
| architecture_doc_agent | YES | Y | Y | Y | - | W | registry-API |
| architecture_reviewer | YES | Y | Y | Y | Y | - | static, registry-API, scan-loop |
| backend_dev | YES | Y | Y | Y | Y | W | static, registry-API |
| barot_agent | YES | Y | - | - | - | - | gap-fill (fleet-reg, 0 caps) |
| base | NO | - | - | - | - | - | static |
| base_graph | NO | - | - | - | - | - | static |
| bhaskar_agent | none(deliberate) | Y | - | - | - | - | static, bhaskar_tool (broken; AGENT-02-001) |
| bhaskar_sandbox | NO | - | - | - | - | - | static |
| bug_fix | YES | Y | Y | Y | Y | W | static, registry-API |
| business_analyst | YES | Y | Y | Y | - | - | registry-API |
| changelog_agent | YES | Y | Y | Y | - | W | registry-API |
| chat_agent | YES | Y | - | chat.md | - | - | chat-routes |
| cicd_agent | YES | Y | Y | Y | Y | W | registry-API |
| cleanup_agent | YES | Y | Y | Y | Y | W | registry-API |
| code_explainer_agent | YES | Y | Y | Y | Y | W | static, registry-API |
| code_quality_agent | YES | Y | Y | Y | Y | W | registry-API |
| coder | YES | Y | - | Y | Y | W | static |
| compliance_agent | YES | Y | Y | Y | Y | W | registry-API |
| conflict_resolution | NO | - | - | - | - | - | infra |
| cost_estimator_agent | YES | Y | Y | Y | Y | W | registry-API |
| data_pipeline_agent | YES | Y | Y | Y | Y | W | registry-API |
| database_architect | YES | Y | Y | Y | Y | - | registry-API |
| debugger_agent | YES | Y | Y | Y | Y | W | registry-API |
| decomposer | YES | Y | - | Y | Y | - | pipeline-graph |
| delegation | NO | - | - | - | - | - | infra |
| dependency_agent | YES | Y | Y | Y | - | W | static, registry-API |
| dependency_security_agent | YES | Y | Y | Y | Y | W | static, registry-API, scan-loop |
| deployment_guide_doc_agent | YES | Y | Y | Y | - | W | registry-API |
| devex_agent | YES | Y | Y | Y | Y | W | registry-API |
| devops | YES | Y | Y | Y | Y | B | static, registry-API |
| docker_agent | YES | Y | Y | Y | Y | W | registry-API |
| docs | YES | Y | Y | Y | - | W | registry-API |
| env_checker_agent | YES | Y | Y | Y | Y | W | registry-API |
| evaluation_agent | YES | Y | Y | Y | - | - | registry-API |
| executive | YES | Y | Y | Y | - | - | static, registry-API |
| feature_flag_agent | YES | Y | Y | Y | Y | W | registry-API |
| frontend_dev | YES | Y | Y | Y | Y | W | static, registry-API |
| gemini_adapter | NO | - | - | - | - | - | static (USE_GEMINI) |
| groq_adapter | NO | - | - | - | - | - | static (USE_GROQ) |
| guardrails | NO | - | - | - | - | - | infra |
| guidance | NO | - | - | - | - | - | infra |
| incident_responder_agent | YES | Y | Y | Y | Y | W | registry-API |
| infra_agent | YES | Y | Y | Y | Y | W | registry-API |
| knowledge_curator | YES | Y | - | Y | - | W | scan-loop, apply-API |
| load_test_agent | YES | Y | Y | Y | Y | W | registry-API |
| localization_agent | YES | Y | Y | Y | Y | W | registry-API |
| manager | YES | - | - | Y | - | - | static |
| mcp_developer_agent | YES | Y | - | Y | Y | W | dynamic-API |
| migration_agent | YES | Y | Y | Y | Y | W | registry-API |
| migration_guide_doc_agent | YES | Y | Y | Y | - | W | registry-API |
| mobile_dev | YES | Y | - | Y | - | W | dynamic-API |
| monitoring_agent | YES | Y | Y | Y | - | - | static, registry-API, scan-loop |
| monitoring_handlers | NO | - | - | - | - | - | infra |
| onboarding_agent | YES | Y | Y | Y | Y | W | registry-API |
| output_parsers | NO | - | - | - | - | - | infra |
| pair_programmer_agent | YES | Y | Y | Y | Y | W | registry-API |
| performance_reviewer | YES | Y | Y | Y | Y | - | registry-API |
| planner | YES | Y | - | Y | Y | - | static |
| pm | YES | Y | - | Y | - | - | pipeline-graph |
| prompt_engineer_agent | YES | Y | - | Y | Y | W | dynamic-API |
| qa | YES | Y | Y | Y | Y | B | static, registry-API |
| quality_auditor | YES | Y | - | Y | - | W | scan-loop, apply-API |
| rag_engineer_agent | YES | Y | Y | Y | - | W | registry-API |
| readme_agent | YES | Y | Y | Y | - | W | registry-API |
| refactor_agent | YES | Y | Y | Y | Y | W | registry-API |
| release_notes_agent | YES | Y | Y | Y | - | W | registry-API |
| research | YES | Y | Y | Y | - | - | static, registry-API |
| reviewer | YES | Y | Y | Y | Y | - | static, registry-API |
| roadmap_agent | YES | Y | - | Y | Y | W | dynamic-API |
| role_detection | NO | - | - | - | - | - | infra |
| rollback_agent | YES | Y | Y | Y | Y | W | registry-API |
| runbook_generator_agent | YES | Y | Y | Y | Y | W | registry-API |
| schema_agent | YES | Y | Y | Y | Y | W | registry-API |
| security_architect | YES | Y | Y | Y | - | - | registry-API |
| security_reviewer | YES | Y | Y | Y | Y | - | static, registry-API |
| slo_agent | YES | Y | Y | Y | Y | W | registry-API |
| spike_agent | YES | Y | Y | Y | Y | W | static, registry-API |
| sprint_planner | YES | Y | Y | Y | - | - | registry-API |
| sql_agent | YES | Y | Y | Y | Y | W | registry-API |
| static_checks | NO | - | - | - | - | - | static |
| style_reviewer | YES | Y | Y | Y | Y | - | registry-API |
| tech_advisor_agent | YES | Y | - | Y | Y | W | dynamic-API |
| tech_debt_agent | YES | Y | Y | Y | Y | - | registry-API |
| temporary_agent | none(deliberate) | Y | - | Y | - | - | temp-pool |
| test_coverage_agent | YES | Y | Y | Y | Y | W | static, registry-API |
| test_writer_agent | YES | Y | Y | Y | Y | W | registry-API |
| tool_catalog_doc_agent | YES | Y | Y | Y | - | W | registry-API |
| tool_security | NO | - | - | - | - | - | infra |
| tools | NO | - | - | - | - | - | static |
| user_sentiment | NO | - | - | - | - | - | infra |
| user_story_generator | YES | Y | Y | Y | - | W | registry-API |
| ux_design_agent | YES | Y | - | Y | Y | W | dynamic-API |
| version_manager_agent | YES | Y | Y | Y | Y | W | registry-API |

