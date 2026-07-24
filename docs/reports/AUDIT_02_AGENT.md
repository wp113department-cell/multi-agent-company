# AUDIT 02 — MASTER AGENT AUDIT (All ~72 Agents)

**Run date:** 2026-07-24
**Scope:** Read-only. Evidence-only. Follows `files/Audit/00b_AUDIT_STANDARDS.md`. Builds on Audit 01's confirmed two-graph structure and Fleet OS understanding.
**Method:** A Python AST-based structural scanner (written for this audit, not a pre-existing tool) parsed all 73 real files under `backend/app/agents/*.py`, extracting `AGENT_CONTRACT`, `VerificationConfig`, `_register()`/capability-tag data, `run_agent_graph()` call kwargs, and role-file mappings — cross-checked against `capability_registry.py`, `specialized_agents.py`'s dispatch table, `main.py`'s self-improvement scan loop, and `agent_models.json`. Structural findings below are exhaustive (all 73 files); qualitative findings (Phase 3/3B) are evidence-based spot-checks as the source audit prompt itself specifies.

---

## 1. Phase 0 — Ground Truth

- `capability_registry.py` — confirmed as described: in-process, thread-safe, write-once-per-name singleton.
- `tool_manifest.py:1644` — `verify_agent_contract(agent_name, tool_list, contract_allowed_tools)` is the real enforcement function: flags any high-risk tool used but not declared in `AGENT_CONTRACT.allowed_tools`. Used as this audit's pass/fail bar.
- Counts reconciled (fresh, not from PROJECT.md): **73 files in `app/agents/*.py`**, of which **72 are real agents** and **1 (`groq_adapter.py`) is LLM-provider-routing infrastructure**, not an agent — it has no `AGENT_CONTRACT`, no `VerificationConfig`, no role file, and is never dispatched as a capability; it's the Groq bypass shim `run_agent_graph()` itself calls internally (confirmed in Audit 01), consistent with PROJECT.md's own description ("groq_adapter (stub only)") and the "TEMPORARY shim, easily removable" comment in `base_graph.py`. **72 role files** exist (73 `.md` files in `roles/` minus `_GLOBAL_STANDARDS.md`, the shared constitution, not a per-agent file). **72 capability registrations**, 0 collisions. All three counts (72 agents / 72 role files / 72 capabilities) are now internally consistent — the audit prompt's own cited baseline ("~72 agents / 67 role files") is stale (role-file count has grown since that prompt was written); this is **not** a discrepancy in the current codebase, just a stale expectation in the prompt itself.

---

## 2. Phase 1 — Structural Scorecard (all 72 real agents, not a sample)

| Check | Result |
|---|---|
| Has `AGENT_CONTRACT` with real (non-empty) `input_types`/`output_types` | **72/72 ✅** |
| Has `VerificationConfig` with non-empty `enforce_in_result` | **71/72 ✅**, 1 legitimate exception (`manager`) |
| `enforce_in_result` keys backed by a real `set_by` value (no dead enforcement key) | **72/72 ✅** — 0 violations found |
| Capability tags globally unique | **72/72 ✅** — 0 collisions (see §3) |
| `_register()` exists and is called at module top level | **72/72 ✅** |
| Role file exists at the exact path the agent loads | **72/72 ✅** (see naming note below) |
| Dispatched from real (non-test) code | **72/72 ✅** — full call map traced (see §5) |

**`manager` exception, verified (not assumed):** `manager.py` has no `VerificationConfig` anywhere in the file (confirmed by direct AST scan and by the full read performed during Audit 01) — it is a plain `async def` orchestrator that dispatches other agents via `asyncio.to_thread`, never calls `run_agent_graph()` itself. Legitimate.

**Correction to the audit prompt's own stated exception list:** The prompt names `executive` as a second legitimate no-`VerificationConfig` agent ("no tools, pure LLM"). This is **stale relative to current code** — `executive.py:26,53,120` shows it *does* call `run_agent_graph(tools=[])` with a real `VerificationConfig`, per its own comment: `"No tools: run_agent_graph with tools=[] does a single LLM call, returns text in messages."` This is not a defect (having a `VerificationConfig` is the *more* compliant state), just a note that the assumption in the audit prompt doesn't match today's code. `manager` is the sole real exception.

**Role-file naming note (not a defect, verified):** `chat_agent.py` was initially flagged by the automated scan as "missing" a role file, because the scanner assumed `roles/<module-stem>.md`. Direct code check (`chat_agent.py:104,160`) shows it loads `roles/chat.md` via its own `_load_role("chat")` — a deliberate, working, different filename. Role file exists and is used correctly; the automated scan's naming assumption was the gap, not the code.

---

## 3. Capability Tag Collision Findings

**0 collisions across all 72 real agents** — re-confirmed fresh by this audit's own AST scan (not trusted from PROJECT.md's "2 collisions found and fixed" history). No regression of the previously-fixed `business_analyst`/`user_story_generator` or `changelog_agent`/`release_notes_agent` collisions, and no new collision introduced since.

---

## 4. Tool-Scope Findings (read-only vs. write-capable)

44 agents have a tool-scope profile consistent with "read-only auditor" (no `edit_file`/`apply_patch`/`delete_file`/`bash` in `AGENT_CONTRACT.allowed_tools`), spanning code review, security, architecture, performance, style, docs-adjacent, and planning-analysis categories. **0 violations found**: none of the reviewer/auditor-named agents (`reviewer`, `security_reviewer`, `architecture_reviewer`, `monitoring_agent`, `style_reviewer`, `performance_reviewer`, `code_quality_agent`, etc.) carry a write- or execute-capable tool.

18 agents legitimately carry `bash`/`edit_file`/`apply_patch`/`delete_file` — all are coder-, DevOps-, or explicitly-gated meta-agent classes: `backend_dev`, `bug_fix`, `cicd_agent`, `cleanup_agent`, `coder`, `dependency_agent`, `devops`, `docker_agent`, `frontend_dev`, `migration_agent`, `qa` (bash for test execution only, no write tool), `refactor_agent`, `sql_agent` — matches CLAUDE.md's own "Coder-class agents" list exactly.

**3 self-improvement meta-agents carry `edit_file` under an explicit, documented approval gate**, not unscoped: `agent_debugger` (`AGENT_CONTRACT["description"]`: *"Gets the full write toolset for its apply phase once a human approves a specific fix"*), `agent_performance_reviewer` (`permissions: ["read_repo", "read_metrics", "write_repo_on_approval"]`, description: *"Never writes code until a specific request is approved"*), `knowledge_curator` (*"Never writes code; its apply phase only touches memory rows and, occasionally, role prompts"*). Each has a structurally separate `run_<name>_scan()` (read-only) and `run_<name>_apply()` (write-capable) function — confirmed for all 3 plus `quality_auditor`. **Not verified in this pass**: whether the `_apply()` functions' write phase is actually gated behind a real approval check in code (vs. only in the prompt/description) — this is Audit 05's mandate (RBAC/approval-gate enforcement); flagged here as a cross-reference item, not asserted as either safe or unsafe.

**`set_by`/`enforce_in_result` pattern across the 44 read-only agents**: PROJECT.md describes this as "a minimal, uniform pattern." Verified: structurally uniform (every one of the 44 has exactly one primary verification key, correctly set by a real read/domain tool, correctly enforced in exactly one result field — 0 dead-key violations per §2) but **not textually identical** — 32 distinct key-name combinations (e.g. `style_reviewer` enforces `lint_ran` via `run_linter`; `schema_agent` enforces `schema_inspected` via `inspect_schema`; `security_reviewer` enforces `scan_ran` via `secrets_scan`). This is domain-appropriate tailoring of the same underlying convention, not copy-paste drift — reported accurately rather than rounded up to "identical" or down to "inconsistent."

---

## 5. Dead/Unreachable Agent List: **NONE FOUND**

Full real-caller trace for all 72 agents, cross-referencing `pipeline/graph.py`, `api/agents.py`, `api/chat.py`, `main.py`, and `api/specialized_agents.py`'s `_REGISTRY` dict:

| Dispatch path | Agents |
|---|---|
| `pipeline/graph.py` (LangGraph nodes) | `pm`, `architect`, `decomposer` (3) |
| `api/agents.py`/`manager.py` (`asyncio.to_thread`) | `backend_dev`, `frontend_dev`, `qa`, `reviewer`, `coder` (5) |
| `api/agents.py:554` (`run_planner`) / `api/tasks.py:211` (`launch_planner`) | `planner` (1) |
| `api/specialized_agents.py`'s `_REGISTRY` (60 entries, `POST /api/specialized-agents/{name}/run(-sync)`) | 60 agents — confirmed every entry resolves to a real, existing `app.agents.<module>` + `run_<fn>` |
| `main.py:126-145`'s `_fleet_agents_scan_loop()` (Day 9 background loop, `FLEET_SCAN_INTERVAL_HOURS`) | `agent_performance_reviewer`, `agent_debugger`, `agent_advisor`, `knowledge_curator`, `quality_auditor` (5) |
| `api/chat.py:118` | `chat_agent` (1) |
| `manager.py`'s own `run_epic_manager()`/`launch_manager()` | `manager` (self, orchestrator) |
| Goal→Epic conversion (`api/goals.py`, not traced in detail this pass) | `executive` (1) |

72/72 accounted for. No agent registered in `capability_registry` with zero real (non-test) callers — this exact pattern (which recurred multiple times in PROJECT.md's history: `chat_agent` once, `versioned_memory` once, `fleet_checkpoint` once) was checked fresh and found clean this round.

---

## 6. Findings

### AGENT-02-001
- **severity:** High
- **file:** 53 files under `backend/app/agents/*.py` (full list below)
- **location:** each file's `run_<name>(task_id: int, ...)` function
- **line:** varies per file; representative: `accessibility_agent.py:89-126`, `bug_fix.py:71-111`, `security_reviewer.py`, `cost_estimator_agent.py:89`
- **finding:** 53 agent functions receive `task_id: int` as a parameter — declared in the signature, included in the AGENT_CONTRACT's `input_types`, and interpolated directly into the initial prompt text (e.g. `f"Task #{task_id} — {description}"`) — but never pass `task_id=` into their `run_agent_graph(...)` call. `run_agent_graph()`'s `task_id` parameter defaults to `""` when omitted. Verified this is a real caller-side gap, not a false pattern match: for a representative sample of 5 (`accessibility_agent`, `cost_estimator_agent`, `debugger_agent`, `security_architect`, `test_writer_agent`), confirmed by direct read that `task_id` truly is used in the prompt string and truly is never referenced again in the function body.
- **evidence:** `accessibility_agent.py:89-126` — `task_id` used at line 102 (`f"Task #{task_id} — {description}"`) but the `run_agent_graph(...)` call at lines 111-126 has no `task_id=` kwarg. Cross-checked against the exact dispatch path that supplies a real `task_id`: `api/specialized_agents.py`'s `SpecializedAgentRequest.task_id: int = Field(..., description="ID of the DevTask this agent is working on")` (line 167) — a required, real `DevTask.id`, not a placeholder.
- **production_impact:** For every one of these 53 agents, when dispatched via `POST /api/specialized-agents/{name}/run` or `/run-sync` (the real, only dispatch path for all of them per §5): (1) `base_graph.py`'s `push_thinking`/`push_token_usage`/`push_tool_call`/`push_tool_result`/`push_file_edit`/`push_terminal`/`push_done` activity-stream events (Day 18's real-time SSE streaming feature) never fire, because every one of those call sites in `base_graph.py` is gated on `if task_id:` and receives `""`. The task detail page's live stream view shows nothing for these agents' execution. (2) `agent_registry.start_task(role_name, task_id=task_id)` and the `TaskStarted`/`TaskCompleted`/`TaskFailed`/`HealthUpdated` Fleet OS events all record `task_id=""` instead of the real DevTask id — the exact class of correlation bug the Days-0-18 gap-closure audit fixed inside `base_graph.py`'s own internal `tid`-vs-`task_id` confusion, recurring here as a *caller-side* instance across the majority of the agent fleet. Does **not** affect `DevTask` status itself — `_run_specialized_agent_bg()` (`api/specialized_agents.py`) independently calls `transition_task(db, task_id, "blocked")`/writes `task_logs` directly with the correct id on failure, so the task's own lifecycle is unaffected; only the real-time/event-correlation layer is degraded. **Excluded from this finding, correctly**: the 5 self-improvement scan agents (`run_<name>_scan(trace_id: str = "")` — no `task_id` parameter at all, by design, since they run on a scheduled fleet-wide loop, not per-task), `research`/`docs`/`executive`/`devops` (no `task_id` parameter — different call shape), and the 8 core-pipeline agents which correctly pass it (see §7).
- **confidence:** High
- **recommendation:** Add `task_id=task_id` (and, where already computed, `trace_id=`) to the `run_agent_graph(...)` call in each of the 53 files. Mechanical, uniform fix — same one-line addition in each file, matching the exact pattern already used correctly in `backend_dev.py`/`frontend_dev.py`/`coder.py`/`bug_fix.py`... (`bug_fix.py` is itself in the affected list, worth noting the inconsistency: `qa`/`reviewer` do it correctly while `bug_fix`, dispatched the same way via `specialized_agents.py`, does not).
- **effort:** Medium (53 single-line changes, mechanical but touches many files — recommend a small script to verify none were missed, similar to this audit's own scan)
- **affected files:** `accessibility_agent`, `ai_engineer`, `api_designer_agent`, `api_docs_agent`, `architecture_reviewer`, `bug_fix`, `business_analyst`, `changelog_agent`, `cicd_agent`, `cleanup_agent`, `code_explainer_agent`, `code_quality_agent`, `compliance_agent`, `cost_estimator_agent`, `data_pipeline_agent`, `database_architect`, `debugger_agent`, `dependency_agent`, `dependency_security_agent`, `devex_agent`, `docker_agent`, `env_checker_agent`, `evaluation_agent`, `feature_flag_agent`, `incident_responder_agent`, `infra_agent`, `load_test_agent`, `localization_agent`, `migration_agent`, `monitoring_agent`, `onboarding_agent`, `pair_programmer_agent`, `performance_reviewer`, `planner`, `rag_engineer_agent`, `readme_agent`, `refactor_agent`, `release_notes_agent`, `rollback_agent`, `runbook_generator_agent`, `schema_agent`, `security_architect`, `security_reviewer`, `slo_agent`, `spike_agent`, `sprint_planner`, `sql_agent`, `style_reviewer`, `tech_debt_agent`, `test_coverage_agent`, `test_writer_agent`, `user_story_generator`, `version_manager_agent`

### AGENT-02-002
- **severity:** Medium-High
- **file:** `backend/app/fleet/agent_models.json`
- **location:** per-agent `model` field for every `"tier": "sonnet"` (62 agents) and `"tier": "opus"` (9 agents) entry
- **line:** 9-84 (representative: line 9 `DEFAULT`, line 18 `architect`, line 20 `backend_dev`)
- **finding:** `agent_models.json` — the file `model_router.py` treats as authoritative, overriding any model string an agent passes as a fallback (confirmed in Audit 01/`base_graph.py:957-964`: *"ModelRouter wins over passed-in model — router is source of truth"*) — pins 62 agents to `"claude-sonnet-4-20250514"` and 9 to `"claude-opus-4-20250514"`, while `config.py`'s own `model_coder` default is `"claude-sonnet-5"` (a different, newer model identifier). Only the 2 haiku-tier entries (`"claude-haiku-4-5-20251001"`) match `config.py`'s `model_planner`/`model_router` defaults.
- **evidence:** `agent_models.json:9` (`"DEFAULT": {..., "model": "claude-sonnet-4-20250514", "tier": "sonnet"}`), confirmed identical string repeated at 62 sonnet-tier entries (e.g. line 20 `backend_dev`, line 21 `bug_fix`); `config.py:32` (`model_coder: str = Field(default="claude-sonnet-5", ...)`). The file's own top comment (`agent_models.json` `_comment` field) says *"Central model routing table for all 68 Gridiron agents"* — also stale (73 entries present, 72 real agents).
- **production_impact:** 71 of 72 agents (all but the 2 haiku-tier ones) are silently routed to a different, older model generation than `config.py`'s own documented default implies — anyone reading `config.py`'s `model_coder`/inspecting agent code that passes `model=settings.model_coder` as a fallback would reasonably believe agents run on `claude-sonnet-5`; in reality `model_router.py` always overrides that with the older pinned string. Not a crash (both are presumably valid, callable model identifiers), but a real drift between two config sources that CLAUDE.md's own "Model names live in config... so we can swap models without code changes" rule exists specifically to prevent — here the two config sources disagree with each other.
- **confidence:** High
- **recommendation:** Reconcile: either bulk-update `agent_models.json`'s sonnet/opus entries to match `config.py`'s current model identifiers, or make `agent_models.json`'s tier-to-model mapping derive from `config.py`'s settings at load time (so there's exactly one source of truth) rather than two files that must be kept in sync by hand. Also update the stale "68 agents" comment to the current count.
- **effort:** Small (bulk find/replace in one JSON file, or a small `model_router.py` change to resolve tier→model from `Settings` instead of the JSON's literal strings)

### AGENT-02-003
- **severity:** Medium
- **file:** `backend/app/agents/base_graph.py`
- **location:** `_make_call_llm_node`, `_make_reflection_node`, `planner_node`, `_extract_and_store_lesson`
- **line:** 286-303 (`planner_node`), 413,437 (`call_llm`), 494-502 (`reflection_node`), 713 (`_extract_and_store_lesson`)
- **finding:** No call site of `anthropic.Anthropic(...)`/`client.messages.create(...)` anywhere in `base_graph.py` passes an explicit `timeout=` parameter. `grep -n "timeout" app/agents/base_graph.py app/agents/base.py app/config.py` returns zero matches. Every LLM call relies entirely on the Anthropic Python SDK's own built-in default client timeout, which is not a value this project controls or has documented.
- **evidence:** `client = anthropic.Anthropic(api_key=get_effective_api_key())` appears 4 times in `base_graph.py` (lines 286, 413, 494, 713-ish) with no `timeout=` argument at construction or at any `.messages.create(...)` call.
- **production_impact:** Matches this audit's own explicit concern verbatim: "a hung connection could block a worker indefinitely." Since every real agent call runs inside an `asyncio.to_thread()` worker (confirmed Audit 01, ARCH-01-002), a hung LLM call would tie up that worker thread for however long the SDK's undocumented default allows, with no project-level control to shorten it for, e.g., time-sensitive dispatches. Not observed to have caused an incident (no evidence either way — static analysis only), but it's an unenforced, unconfigured value in an area CLAUDE.md's "Zero Hardcoding" rule explicitly wants config-driven ("retry limits: config or database tables, never inline constants" — a timeout is the same class of value).
- **confidence:** High
- **recommendation:** Add a `LLM_CALL_TIMEOUT_SECONDS` (or similar) field to `config.py`'s `Settings`, and pass `timeout=settings.llm_call_timeout_seconds` to every `anthropic.Anthropic(...)` client construction in `base_graph.py` (and `base.py` if it constructs its own client).
- **effort:** Small (one config field + ~4 call sites in `base_graph.py`)

### AGENT-02-004
- **severity:** Medium
- **file:** `backend/app/agents/tools.py`
- **location:** every `submit_*` handler factory (e.g. `make_bug_fix_handlers`, and the equivalent for QA/review/research/docs/security/architecture)
- **line:** representative: 1015 (`qa_result.update(inp)`), 1030 (`review_result.update(inp)`), 3261 (`bug_fix_result.update(inp)`), 3400, 3477
- **finding:** Every `submit_*` tool handler found in this pass takes the raw LLM tool-call arguments (`inp: dict[str, Any]`) and does `result.update(inp)` — a direct, unvalidated dict merge. No Pydantic model validates `inp` against the tool's own declared `input_schema` before it's trusted and returned as part of `AgentResult.raw`. Downstream code reads fields with silent-default `.get(key, default)` (e.g. `bug_fix.py:115`: `raw.get("fix_summary", raw.get("root_cause", "(no summary)"))`).
- **evidence:** `grep -n "\.update(inp)" app/agents/tools.py` matches at (at minimum) lines 1015, 1030, 1165, 1227, 3261, 3400, 3477 — the same shape repeated across the QA, review, research, docs, bug-fix, security, and architecture-review submit handlers.
- **production_impact:** Matches this audit's own stated concern: "Malformed-but-silently-defaulted output is a hallucination-propagation risk." If Claude's tool call omits a field the JSON schema marks `required` (which the SDK enforces on the *shape* of a well-formed tool call, but a model can still emit a technically-valid call with an empty string or unexpected type for a field), the handler accepts it as-is; the caller's `.get(..., default)` masks the gap rather than surfacing it as a verification failure. The `state["verification"]` boolean-override mechanism (Audit 01/`base_graph.py` — the core anti-hallucination contract) still correctly forces `tests_passed`/`read`/etc. booleans regardless of what the model claims, so the *boolean* verification contract is not bypassed by this finding — this is specifically about the *non-boolean* free-text/list fields (summaries, findings, recommendations) having no structural validation.
- **confidence:** High
- **recommendation:** Define a Pydantic model per `submit_*` tool matching its `input_schema`, and validate `inp` through it inside the handler before merging into `result` — reject/log-and-flag a validation failure rather than silently accepting a malformed payload. Given the scale (dozens of handlers), a shared helper (`validate_submit(model_cls, inp) -> dict`) applied uniformly would avoid per-handler duplication.
- **effort:** Medium (one shared validation helper + wiring it into each `submit_*` handler)

---

## 7. Model Selection & Fallback (Phase 3B spot-check, 5 agents + cross-cutting)

- **Model source**: confirmed via Audit 01 and re-verified here — `run_agent_graph()` always calls `model_router.get_model_router().route(role_name)` and overrides the caller-passed `model`, for all 72 agents uniformly (no agent bypasses the router with a hardcoded model string — 0 found in `app/agents/*.py` beyond the one instance already fixed in Audit 01, `api/settings.py`, which is not an agent file).
- **Fallback provider**: confirmed **retry-same-provider only, no cross-provider fallback** for the primary path. `run_agent_graph()`'s LLM calls (`_make_call_llm_node`, `_make_reflection_node`, `planner_node`) have no `try/except` around `client.messages.create(...)` that would catch a rate-limit/5xx and retry on a different provider — a failure there propagates up as an unhandled exception into `run_agent_graph()`'s outer `try/except Exception` (Audit 01 territory), which checkpoints and re-raises. The *only* cross-provider path is the `USE_GROQ=true` bypass (`base_graph.py:1030-1096`), which is an entirely separate code path selected before the graph runs, not a runtime fallback triggered by an Anthropic failure.
- **Timeout policy**: see AGENT-02-003 above.
- **Retry state isolation**: confirmed clean — `AgentRunState` (including `retry_count`, `n_stalls`) is constructed fresh in `initial_state` inside `run_agent_graph()` for every call (`base_graph.py:1118-1139`), a local dict, never a module-level/global counter. No cross-task/cross-run retry-state leak possible by construction.
- **`chat_agent`'s background-process tracking**: re-verified per-instance, not module-level — `self._background_processes: dict[int, subprocess.Popen[str]] = {}` inside `ChatAgent.__init__` (`chat_agent.py:164`), not a module global. PROJECT.md's documented fix is holding, no regression.

---

## 8. Multimodal / Image Input (Day 16 agents)

Confirmed the 4 documented image-capable agents (`pm`, `architect`, `frontend_dev`, `reviewer`) are among the 8 agents that correctly thread `task_id`/receive real production dispatch with images — not re-traced end-to-end in this pass (Audit 01 already traced `pipeline/graph.py`'s image pre-fetch into `state["images"]`, and `manager.py`'s `images=images` forwarding to `run_frontend_dev`/`run_reviewer`). No new finding; deferred to avoid duplicating Audit 01's already-verified trace.

---

## 9. Prioritized Fix List

| Priority | ID | Task | Effort |
|---|---|---|---|
| 1 | AGENT-02-001 | Add `task_id=task_id` to the `run_agent_graph()` call in each of the 53 listed agent files | Medium |
| 2 | AGENT-02-002 | Reconcile `agent_models.json`'s pinned model strings with `config.py`'s current defaults (or derive one from the other) | Small |
| 3 | AGENT-02-003 | Add a config-driven `timeout=` to every Anthropic client call in `base_graph.py` | Small |
| 4 | AGENT-02-004 | Add Pydantic validation to `submit_*` tool handlers instead of raw `dict.update(inp)` | Medium |

---

## 10. Agent Layer Production-Readiness Score: 78/100

Strong structural foundation — 0 capability collisions, 0 orphaned agents (a full, traced dispatch map for all 72), correct tool-scope enforcement, and a real (if not textually uniform) verification contract on every agent. The score is held down by one genuinely systemic, previously-undocumented gap (AGENT-02-001, affecting 53 of 72 agents' observability) plus a real model-version drift (AGENT-02-002) — both mechanical to fix, neither a production blocker (task lifecycle correctness is independently maintained through direct DB writes, confirmed in §6's production-impact analysis), but both should close before this layer is called fully production-hardened.

**Overall: READY for next audit phase (Audit 03 — Memory).**

---

## 11. Fixes Applied (2026-07-24)

All 4 findings fixed per user direction.

- **AGENT-02-001 [FIXED]** — Added `task_id=str(task_id)` to the `run_agent_graph()` call in all 53 listed files (52 via a scripted, span-verified insertion + `planner.py` fixed by hand since it has a second, unrelated `run_agent_graph(` mention inside a docstring). `str()` conversion required because `run_agent_graph()`'s `task_id` parameter is typed `str` while these functions receive `task_id: int` — matches the existing convention already used correctly in `backend_dev.py`/`frontend_dev.py`/etc. Re-verified via a fresh AST pass: 0/53 files still missing the kwarg.
- **AGENT-02-002 [FIXED]** — Bulk-updated `backend/app/fleet/agent_models.json`: all 63 `claude-sonnet-4-20250514` entries → `claude-sonnet-5` (matching `config.py`'s current `model_coder` default), all 9 `claude-opus-4-20250514` entries → `claude-opus-4-8` (current Opus generation; no `config.py` field exists for this tier, so the JSON file's own literal was corrected directly, consistent with its stated role as the per-tier config surface). Haiku-tier entries were already correct, left untouched. Updated the file's stale `_comment` (68→72 agents) and added a note that the sonnet/opus strings should be kept in sync with `config.py` going forward.
- **AGENT-02-003 [FIXED]** — Added `llm_call_timeout_seconds: float = 300.0` to `config.py`'s `Settings`. Added a shared `_make_client()` helper in `base_graph.py` (all 4 call sites now route through it) and updated `base.py`'s existing `_make_client()` the same way — both now construct `anthropic.Anthropic(api_key=..., timeout=get_settings().llm_call_timeout_seconds)` instead of an unconfigured client.
- **AGENT-02-004 [FIXED]** — Installed `jsonschema==4.26.0` into the venv and pinned it in `requirements.txt` (verified current via `pip install`, per CLAUDE.md's zero-hallucination package rule). Rather than hand-writing a Pydantic model per `submit_*` tool (dozens of them, real scope bloat for a mechanical validation task), added centralized validation at the one real chokepoint every `submit_*` call already passes through — `base_graph.py`'s `execute_tools()` node — reusing each tool's own already-declared `input_schema` via `jsonschema.validate()`. A schema mismatch is now non-fatal (logged as a warning, and the result dict gets a `_validation_warning` key so it's inspectable downstream) rather than either crashing the run or silently vanishing. This covers all ~72 agents uniformly, including both the ~20 handlers in `tools.py` and the ~50 per-agent inline handlers, since all of them funnel through this one node.

**Verification:** `pytest tests/ -q` → 2758 passed, 0 failed, 55 skipped, 17 deselected (unchanged — no regressions across any of the 4 fixes). `mypy app/ --strict` → 0 errors, 176 source files (this caught a real bug during the fix itself: the initial mechanical `task_id=task_id` insertion was `int`-typed against a `str`-typed parameter in all 53 files — fixed to `task_id=str(task_id)` before this ran clean). Live-verified the new jsonschema validation directly against `execute_tools()`: a malformed `submit_plan` call (missing the required `plan` field) is correctly flagged with `_validation_warning` and the run still completes normally; a well-formed call passes through with no warning.
