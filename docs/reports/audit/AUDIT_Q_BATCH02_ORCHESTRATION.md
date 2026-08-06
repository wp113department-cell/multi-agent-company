# Batch 2 — Complete Orchestration, Agent Selection, Tool Selection, Runtime Decisions

Covers §2, §3, §4, §62. Evidence-only, file:line cited.

**Agent count reality check:** claim is "72 agents." Real count: 84 `.py` files in `backend/app/agents/`, 73 role `.md` files in `backend/roles/` (72 roles + `_GLOBAL_STANDARDS.md`). Of the 84 `.py` files, 8 are shared infrastructure, not agents (`base.py`, `base_graph.py`, `tools.py`, `guardrails.py`, `agent_result.py`, `groq_adapter.py`, `chat_agent.py`, `__init__.py`) — leaves ~76 candidates, close to the 72 claimed. **Gap found:** 4 agent modules (`agent_roster_doc_agent.py`, `architecture_doc_agent.py`, `migration_guide_doc_agent.py`, `tool_catalog_doc_agent.py`) call `run_agent_graph(role_name=...)` with a role name that has **no matching file** in `backend/roles/` — `load_role()` will raise `FileNotFoundError` if these run as written. `user_sentiment.py` isn't wired through `run_agent_graph`/`load_role` at all.

---

## §2 Complete Orchestration

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Who receives the request first | **YES** | `POST /api/tasks/{id}/run` → `launch_planning_pipeline` → `run_planning_pipeline()` (`pipeline/graph.py:144`) → LangGraph starts at node `"pm"` (`agents/pm.py:104`). |
| Who decides which agents work | **PARTIAL** | Two layers: hardcoded type check (`manager.py:301-303`, `frontend_dev` if type=="frontend" else `backend_dev`) then `FleetManager.select()` (`fleet_manager.py:65-165`) which can only return one of those same two names — the code's own comment admits it "produces the same routing the old check did in the common case." |
| Automatic / rule-based / AI-based routing | **PARTIAL — rule-based, not AI-based** | Deterministic scoring formula (`fleet_manager.py:140-142`), no LLM call anywhere in the dispatch decision. |
| Multiple agents work simultaneously (fan-out) | **NO** | Zero `Send()`/LangGraph fan-out usage anywhere in `app/`. `run_manager()`'s subtask loop is a strict sequential `for` loop. |
| Agents create subtasks dynamically | **NO — not found** | Subtasks created once by `decomposer_node`. Zero hits for `create_subtask`/`add_subtask`/`spawn_subtask`. |
| Agents request help from other agents | **NO — not found** | Zero hits for `delegate_to`/`request_agent`/`call_agent`/`invoke_agent`. `request_clarification` exists but routes to a human, and is wired only into `planner.py`, not general worker agents. |
| Agents reject tasks they're not suited for | **PARTIAL** | `FleetManager.select()` returns `None` on no-healthy-match (real refusal at fleet level) — but the real call site in `manager.py:313-320` swallows this in `try/except: pass` and silently falls back to the hardcoded default, so the refusal never actually blocks or reroutes dispatch today. |
| Orchestration changes dynamically mid-execution | **PARTIAL** | Real replanning exists (`_should_replan`/`_make_replan_node`, base_graph.py:693-760) triggered on evidence (2+ unsatisfied reflections or critique retries) — but gated behind `enable_replanning`, which **defaults False** fleet-wide; opt-in per agent. |
| Dependencies managed | **YES** | `_topological_subtask_order()` (`manager.py:21-85`), real Kahn's-algorithm sort over `depends_on` indices from the decomposer's schema. |
| Priorities managed | **NO** | `DevTask.priority`/`EnhancementRequest.priority` fields exist in the DB and are stored/read back into API responses, but no queue or dispatch code sorts or weights by priority. Field is decorative today. |
| Conflicts resolved | **YES** | `check_file_conflicts()` (`pipeline/conflict_guard.py:21-54`) compares impacted-files sets across concurrently-running epics, halts on overlap before coding starts. Tested (3 files). |
| Duplicate work prevented | **PARTIAL** | Only mechanism is the conflict guard above — a point-in-time check before dispatch, not a held lock during coding. A second epic starting after the check runs could still race in. |

## §3 Agent Selection

Real function: `FleetManager.select()` (`fleet_manager.py:65-165`).

| Factor | Verdict | Evidence |
|---|---|---|
| Skills/capability | **YES** | Filters by `find_by_capability(required_capability)`. |
| Tools | **YES** | `verify_tool_availability` checks each declared tool resolves. |
| Current workload | **YES** | `instance.is_available` check skips non-idle agents. |
| Health / previous success / previous failures | **YES** | Score formula `health_weight * success_rate * (1/(1+error_count))` (`fleet_manager.py:140-142`). |
| Experience (tenure) | **NO — not found** | Only proxied through success_rate/error_count, no distinct tenure factor. |
| Confidence | **NO** | `confidence` exists in per-run state and gates a post-hoc quality check, but `select()` never reads it. |
| Memory (past outcomes) | **NO** | Memory informs the chosen agent's prompt, not which agent gets chosen. |

**Overall §3 verdict: PARTIAL.** A real scoring function exists with 4 of 8 asked-about factors genuinely wired in, but its practical impact is limited — it can currently only choose between 2 literal agent names per manager.py's call site, so the scoring rarely changes the outcome versus the simple type check it sits behind.

## §4 Tool Selection

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Automatic tool selection | **YES** | Native Anthropic `tool_use` — the model picks from the passed `tools` list; no custom picker on top. |
| Call multiple tools per turn | **YES** | `pending_tool_uses` processes all `tool_use` blocks in one model response (base_graph.py:1552-1560), executed sequentially within that turn. |
| Retry failed tools | **YES** | `_run_tool_with_retry()` (base_graph.py:1446-1484), policy-driven (`none/once/backoff`) per `TOOL_MANIFEST`, exponential backoff, explicitly excludes `write_remote`/`execute`/`write_repo` tools from auto-retry to avoid duplicate side effects. Tested (`test_stage4_tier3_tool_level_retry.py`). Separate higher-level retry for whole agent-runs via `failure_ladder.py::should_retry()`. |
| Verify tool outputs | **YES** | `[ERROR]`/`[POLICY]` prefix checks + `jsonschema.validate()` on submit tools + `_run_quality_gate()` cross-checking model claims against real `state["verification"]` flags — "the model cannot lie about tests passed" per the module's own docstring. |
| Recover from failures | **YES** | Exhausted tool retries return `[ERROR]` to the model for its next turn; at agent-run level, `should_retry()` retries the whole cycle, then `blocked`→`abort()`/`escalate()`+human review once `max_epic_failures` hit. |
| Intelligent vs hardcoded tool list | **PARTIAL** | Static per-agent-role list (each agent declares a fixed set at call time) — varies by role, but not dynamic within a run based on context/history. |

**Overall §4 verdict: YES — mostly production ready**, with the one caveat that tool lists don't adapt within a run.

## §62 Runtime Decision Making

| Capability | Verdict | Mechanism |
|---|---|---|
| Switch strategies | **PARTIAL** | Replanning exists but defaults off (see §2). |
| Switch tools | **NO — not found** | No mid-run tool-list swap. |
| Call additional agents | **NO — not found** | No agent-initiated cross-agent invocation; only orchestrator-sequenced (backend_dev→qa→reviewer). |
| Request human approval (HITL) | **YES** | Two real, separate LangGraph `interrupt()` paths: pipeline human-review gate (`pipeline/graph.py:87-134`) and chat_agent's `self._confirm()` (`chat_agent.py:503,561`). Plus non-interrupt cost-approval halt (`manager.py:983-1017`). |
| Stop execution | **YES** | `_make_router` (base_graph.py:2061-2092) — stops on submit, `max_turns`, or stall detection (`n_stalls`). |
| Retry | **YES** | See §4. |
| Rollback | **PARTIAL** | `rollback_to`/`failure_ladder.rollback` exist as real functions but are **explicitly, deliberately not auto-wired** per the module's own docstring — manual/operator-invoked only, no automatic trigger. |
| Skip unnecessary work | **YES** | `_route_after_resource_check`/`_route_after_cost_estimate`/`_route_after_conflict_check` (manager.py:1386-1401) skip coding entirely on halt conditions. |

---

## Summary — Batch 2 (36 checkpoints across 4 sections)

- **YES:** 15
- **PARTIAL:** 15
- **NO / NOT FOUND:** 6

**Findings worth flagging:**
1. **No fan-out / parallel agent execution anywhere** — despite being built on LangGraph (which supports `Send()` natively), the orchestrator runs every subtask sequentially. At fleet scale this is a real throughput ceiling, not a stylistic choice.
2. **Agent selection scoring exists but is mostly decorative** — `FleetManager.select()` implements a real, tested scoring formula, but the only real call site can only return one of 2 hardcoded names, so the sophistication doesn't currently affect outcomes.
3. **Priority field is stored but never consulted** — `DevTask.priority` looks load-bearing from the schema but has zero effect on dispatch order.
4. **4 agent modules reference nonexistent role files** — a real runtime crash risk if those agents are ever invoked (`agent_roster_doc_agent.py`, `architecture_doc_agent.py`, `migration_guide_doc_agent.py`, `tool_catalog_doc_agent.py`).

**Production Enhancement Plan (for the PARTIAL/NO items above):**
- Add `langgraph.types.Send()` fan-out in `run_manager()`'s subtask loop for independent (no `depends_on` edge) subtasks, bounded by the existing `concurrency.py` semaphores — turns the topological order into parallel waves instead of one long sequential chain.
- Either wire `DevTask.priority` into `_topological_subtask_order()` as a tie-breaker, or remove the field/document it as informational-only to stop it misleading future audits.
- Fix `manager.py:313-320`'s silent `except: pass` to actually surface/act on a `FleetManager.select()` refusal instead of masking it.
- Create the 4 missing `backend/roles/*.md` files or remove the 4 orphaned agent modules — this is a one-file check away from a production crash.
