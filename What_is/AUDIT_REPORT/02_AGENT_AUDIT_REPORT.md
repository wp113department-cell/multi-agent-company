# Audit 02: Master Agent Audit (all 85 agents)

**Spec:** `files/Audit/02_MASTER_AGENT_AUDIT.md` + `00b_AUDIT_STANDARDS.md`
**Date:** 2026-09-29 · **JSON sidecar:** `json/AUDIT_02_AGENT.json`

## Result

🟢 **GREEN: every agent verified at runtime; all defects fixed. Two agents are documented as not wired, by owner decision.**

**Agent layer score: 90 / 100.** Contracts, verification, tool scoping and registration are consistent across all 85 agents. Points lost for three real defects found and fixed (a broken run endpoint, unscoped writes, a missing task id), and for two agents that exist but aren't wired into the pipeline (`docs`, `mobile_dev`), kept that way by owner decision.

## How this was checked

The audit did not read agent files one by one and guess. `evidence/agent_scorecard.py` imports every agent module, calls its real `run_*` function with the LLM call intercepted (no API spend), and records exactly what the agent hands to the graph: tools, verification rules, model, flags, `task_id`. Three further executed probes:

| Probe | What it proves |
|---|---|
| `evidence/agent_scorecard.py` | the per-agent scorecard (runtime capture) |
| `evidence/agent_api_bind_check.py` | whether each agent the API advertises can really be called |
| `evidence/docs_agent_write_probe.py` | whether "docs-only" agents can really write code |

## Scorecard summary (85 agents)

| Check | Result |
|---|---|
| `AGENT_CONTRACT` with real input/output types | ✅ 85 / 85 |
| `VerificationConfig` present | ✅ 84 / 85 (`manager`: pure orchestrator, legitimate exception) |
| Non-empty `enforce_in_result` | ✅ 82 / 84 (`executive`: plain-JSON contract; `barot_agent`: meta-agent; both legitimate) |
| Dead enforcement keys (enforced but no tool can set) | ✅ **0** |
| Capability-tag collisions (fleet-wide) | ✅ **0** (historical collisions stay fixed) |
| Registered at import | ✅ 85 / 85 |
| Role file with all 7 role sections | ✅ 83 / 83 that load a role file (`barot_agent` and `chat_agent` build their prompt in code; N/A) |
| High-risk tool used but not declared in contract | ✅ **0** |
| Tool the model wasn't offered, but handler exists | ✅ refused by the graph (`base_graph.py:2643`) |
| `role_name` passed = agent name | ✅ 85 / 85 |
| `task_id` threaded into the graph | ✅ after fix (AGENT-02-003). The 5 fleet self-improvement agents run background scans with no task (by design). |
| Explicit model route in `agent_models.json` | ✅ 85 / 85 after fix (was 72) |
| Real (non-test) caller exists | ✅ 84 / 85. `mobile_dev` is not wired (owner decision). |

**Dead or unreachable agents:** only `mobile_dev`. The docs agent (`run_docs`) is reachable only as a pipeline helper that nothing currently calls. Both are documented in the guide by owner decision.

## Phase 3B: runtime reliability (verified in code)

| Question | Answer, with evidence |
|---|---|
| Model from router or hardcoded? | Router wins: `run_agent_graph()` overrides the caller's model with `ModelRouter.route(role_name)` (`base_graph.py:3608-3617`). |
| Provider fallback? | **Same-provider only**: the SDK retries (`llm_call_max_retries`) plus a shared circuit breaker. There is no automatic Anthropic → Groq/Gemini failover; the provider is chosen by config. This goes to audit 13 as a human decision. |
| LLM call timeout? | ✅ Enforced: `anthropic.Anthropic(timeout=llm_call_timeout_seconds)` (`base.py:54-58`, `base_graph.py:123`). |
| Structured output validated? | ✅ Every `submit_*` call is JSON-schema-validated at one chokepoint (`base_graph.py:2762-2776`). **Known limitation:** validation is soft. A mismatch is logged and surfaced as a result warning (`base_graph.py:2203`) but not rejected. Making it strict would change behaviour for all agents and can't be tested without live LLM credit (listed in `PENDING_TESTS_API_KEYS.md` §L). |
| Tool scope enforced at runtime? | ✅ `filter_runtime_tools` drops undeclared high-risk tools; the graph refuses unadvertised tools. |
| Multimodal | ✅ `run_agent_graph(images=…)` builds Anthropic image content blocks (`base_graph.py:3590-3605`); the manager forwards task images (`manager.py:609, 844, 1645`). |
| Emotion / intent | Real code, not just a prompt: `app/agents/user_sentiment.py` is wired into the chat agent (`chat_agent.py:4789`) as telemetry. |

## Findings

- **id:** AGENT-02-001 · **severity:** High · **status: FIXED**
  **file:** `backend/app/api/specialized_agents.py` · **location:** `_agent_call_kwargs`, `/run`, `/run-sync`, `/dispatch`, `GET /agents`
  **finding:** 16 of the 80 agent names the API advertised could never run. `_agent_call_kwargs` always sent `task_id` + the description as "the second parameter", so `run_devops(repo_path, task_description)` got an unexpected `task_id`, and pipeline-only agents (qa, reviewer, backend_dev, docs, …) were missing required context. The endpoint answered `{"status":"queued"}`, then the background task raised `TypeError`. Capability dispatch for `backend_development` always picked `backend_dev`, so it always failed.
  **evidence:** `evidence/agent_api_bind_check.out.txt`: "signature bind failures: 16" (before the fix).
  **fix:** arguments are matched by parameter name. Agents that need pipeline context are refused up front with a clear 422 and are no longer advertised.
  **verification:** `tests/test_audit02_specialized_agent_call_contract.py` (10 tests; real app, prod-like auth); 781 related existing tests pass.
  **confidence:** High · **effort:** Small

- **id:** AGENT-02-002 · **severity:** High · **status: FIXED**
  **file:** `backend/app/agents/api_designer_agent.py`, `data_pipeline_agent.py`, `load_test_agent.py`
  **finding:** These three declare `permissions=["read_repo", "write_docs", …]` but inherited the chat agent's **unscoped** `write_file`, which could create or overwrite any file (including `app/main.py` or `docker-compose.yml`). This is the same class as the earlier fix for `accessibility_agent` (tool #231); these three were missed.
  **evidence:** `evidence/docs_agent_write_probe.py` created `evil.py` through all three (before the fix).
  **fix:** shared helper `tool_security.docs_or_new_file_write_denial()`. It allows `.md` / `docs/**` and **new** files of each agent's own deliverable type (OpenAPI spec; pipeline design/stub; load-test script), and it refuses overwriting any existing non-doc file.
  **verification:** probe across all 36 `write_docs` agents → **0 can overwrite existing code**; `tests/test_audit02_docs_agent_write_scope.py` (10 tests); an existing test that protects `data_pipeline_agent`'s intended `.py` stubs still passes.
  **confidence:** High · **effort:** Small

- **id:** AGENT-02-003 · **severity:** Medium · **status: FIXED**
  **file:** `backend/app/agents/devops.py`, `research.py`
  **finding:** No `task_id` parameter, so their runs never reached the task's live activity stream (the Day-18 bug class).
  **fix:** optional `task_id`, threaded into `run_agent_graph`; covered by a test.
  **confidence:** High · **effort:** Small

- **id:** AGENT-02-004 · **severity:** Low · **status: FIXED**
  **file:** `backend/app/fleet/agent_models.json`
  **finding:** 13 registered agents had no routing row and silently used DEFAULT.
  **fix:** explicit rows at the same model (no behaviour change), plus a test that every future agent needs one.

- **id:** AGENT-02-005 · **severity:** Low · **status: ACCEPTED (owner decision)**
  `docs` (README/changelog writer) and `mobile_dev` are not wired into the pipeline. The owner chose to document this rather than add new LLM-spending behaviour now; the guide is corrected.

- **id:** AGENT-02-006 · **severity:** Low · **status: OPEN (tracked)**
  **file:** `backend/app/fleet/tool_manifest.py`
  **finding:** About 45 agent-specific tools (mostly `submit_*` result sinks and read-only listers) have no `TOOL_MANIFEST` entry, so they default to "not high-risk". None of them writes files or runs commands (checked), so there is no current exposure; it's a catalogue-completeness gap only.

## Verdict

**READY:** no open Critical or High issues in the agent layer.
