# Batch 7 — Autonomous Ranger/Guardian Agents, Human Interaction, Human Approval, Human Override

Covers §12, §64, §13, §39, §103. Evidence-only, file:line cited.

---

## §12 / §64 — "5 Guardian/Ranger Agents"

**The literal claim (5 agents, architecturally separate from normal task agents, with separate memory/tools, monitoring Docker/logs/Git/architecture) does not exist as described.** No agent, class, or module named guardian/ranger/sentinel/watchdog/overseer exists anywhere in the codebase — the only hit for those words is a single hypothetical comment in `base_graph.py:2448` ("...like 'fleet-scan' from a guardian agent's periodic scan"), not real code.

**What does exist, and is real:** the "Day 9 Fleet Enhancement" system — originally 5 agents, now 7 (`agent_performance_reviewer`, `agent_debugger`, `agent_advisor`, `knowledge_curator`, `quality_auditor`, `architecture_reviewer`, `dependency_security_agent`).

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Architecturally separate 5-agent tier | **NO** | These 7 use the identical registration mechanism (`AGENT_CONTRACT` + `_register()` into `capability_registry`/`agent_registry`) as all ~83 other agent files — not a distinct tier. |
| Separate memory | **NO** | Same `memory_hook_node`, same `memory_embeddings` table, same process-local `LessonStore` as every other agent. |
| Separate tools | **PARTIAL** | `SCAN_TOOLS`/`FLEET_APPLY_TOOLS` are a bespoke subset, but built from the same primitive tool specs (`write_file`, `edit_file`, `run_tests`, etc.) shared fleet-wide — not a genuinely distinct toolset. |
| Autonomous scheduling (no manual trigger) | **YES** | `main.py::_fleet_agents_scan_loop` — real `while True: await asyncio.sleep(interval*3600)` loop, runs all 7 scan functions on a config-driven interval (default 4h), wired into FastAPI lifespan under leader election, clean shutdown. |
| Codebase monitoring | **PARTIAL** | Covered by scan phases (architecture/dependency/quality checks), but not a distinct "codebase monitor" — folded into the 7 agents' individual scan logic. |
| Log monitoring | **NO — not autonomous** | A separate `monitoring_agent.py` exists (cpu/memory/disk/health_check/read_logs) but is confirmed **task-triggered only**, not present in `_fleet_agents_scan_loop`'s scan function list. |
| Docker monitoring | **NO — not autonomous** | `docker_agent.py` is a normal, human-triggered, single-purpose worker agent (its own contract states it "always requires human approval") — not scheduled. |
| Git monitoring | **NO — not found** as an autonomous function of the 7-agent scan tier. |
| Architecture monitoring | **YES** | `architecture_reviewer` is one of the 7, runs on the scheduled loop. |
| Enhancement suggestions | **YES** | All 7 scan phases call `submit_enhancement_request`, creating real `EnhancementRequest` DB rows proactively, with no user prompt. |
| Bug detection | **YES** | `agent_debugger.py`, docstring: "Detects failing agents and platform bugs from real audit-trail evidence." |
| Automatic planning | **NO — not found** beyond the scan→suggestion pattern; no dedicated autonomous planning agent in this tier. |
| Approval workflow before code changes | **YES — real and tested** | `POST /api/fleet/requests/{id}/approve` (RBAC-gated via `require_approver`) is the only path to `_run_apply_phase`. `reject_request` is terminal. Tested: `test_fleet_dashboard_api.py` (366 lines). |
| Never modifies code without approval | **PARTIAL — with a real gap** | Enforced correctly for the 4 apply-capable agents (`agent_performance_reviewer`, `agent_debugger`, `knowledge_curator`, `quality_auditor`) — code changes only happen via the approval gate. **But `architecture_reviewer` and `dependency_security_agent` have no `_apply` function at all** — their enhancement requests can be approved in the UI, but nothing happens beyond the row being marked completed. This isn't a safety violation (they simply can't write code), but it is a UX/functionality gap: an approval that silently does nothing. |

**§12/§64 overall verdict: PARTIAL, with a significant naming/scope mismatch from the original ask.** The real system (7 scheduled scan-and-suggest agents, approval-gated apply phase) satisfies the *spirit* of "never modify code without approval" and "proactive monitoring" reasonably well, but it is not the architecturally-separate 5-agent supervisory tier described in the question, doesn't cover Docker/log/Git monitoring autonomously, and has a dead-end for 2 of its 7 agents' approved requests.

**Production Enhancement Plan:** Either wire `architecture_reviewer`/`dependency_security_agent` into `_apply_dispatch()` with real apply functions (if there's meaningful auto-fixable output from their scans) or make the UI clearly mark their enhancement requests as "recommendation only, no auto-apply" so an approval doesn't silently no-op. Add `monitoring_agent`'s log/Docker checks and a Git-status check as additional scan functions in `_fleet_agents_scan_loop` if autonomous infra monitoring is actually wanted — the scheduling infrastructure to do this already exists and works.

---

## §13 Human Interaction

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Ask permission | **YES** | Real `interrupt()`-based `_confirm()` (`chat_agent.py:564-624`), backed by a `PendingApproval` DB row + SSE `confirmation_required` event. |
| Wait indefinitely | **YES** | No timeout on `interrupt()` — nothing auto-proceeds or auto-cancels a pending confirmation. |
| Present options (multi-choice) | **NO — not found** | Confirmation payload is binary approve/deny only; no structured multi-choice mechanism anywhere. |
| Recommend choices | **PARTIAL** | `request_clarification` allows free-text context/question that can embed a recommendation in prose, but there's no structured recommendation field. |
| Pause/resume execution | **PARTIAL — real but inconsistent across agent types** | Real, persistent LangGraph checkpoint-based resume for the PM/Architect/Decomposer pipeline (`AsyncPostgresSaver`, `interrupt_before=["human_review"]`) and for chat_agent (same-thread resume). **Plain worker (base_graph) agents have no true pause/resume** — `request_clarification` there just ends the run; "resume" means an external caller re-dispatches a fresh run with the answer folded in, not true in-place state retention. |
| Understand follow-up replies / continue from previous context | **PARTIAL** | Same split as above — real for pipeline and chat, not real for plain worker agents. |

**§13 overall: PARTIAL.** The mechanism is real and well-built where it exists (genuine LangGraph `interrupt()`/`Command(resume=...)`, DB-backed pending-approval tracking), but coverage is uneven: only 2 of the 3 agent execution paths (pipeline, chat) have true pause/resume; the ~76-83 plain worker agents that make up the bulk of the fleet do not.

## §39 Human Approval System

Confirmed real, specific gates (not a blanket policy — each checked individually):

| Dangerous operation | Gated? | Evidence |
|---|---|---|
| Delete a file | **YES** | `chat_agent.py:1122` |
| Overwrite an existing file | **YES** | `chat_agent.py:1039-1046` (note: new-file writes are not gated, only overwrites) |
| `git push` (incl. force) | **YES** | `chat_agent.py:1243-1250` |
| `git reset --hard` | **YES** | `chat_agent.py:1676-1683` (non-hard resets not gated) |
| Dangerous bash command | **YES** | `chat_agent.py:1261-1267` via `_is_dangerous_command`/`check_command` |
| `undo_changes` (`git checkout --`) | **YES** | `chat_agent.py:2536-2541` |
| DB migration | **YES, with defense-in-depth** | Gated in interactive session (`chat_agent.py:2578-2583`); additionally hard-blocked outright in production regardless of confirmation, and blocked entirely outside an interactive session. |
| `seed_database` | **YES** | `chat_agent.py:2600-2605` |
| **Dependency upgrades** | **NO — confirmed gap** | `npm_install_h`/`pip_install_h` (`tools.py:12022-12062`) run `subprocess.run` directly with **zero confirmation and zero policy check**. Only publish-type commands (`npm publish`, `docker push`) are denylisted; plain `install` is not. |
| **Deployment** | **N/A by design** | No deploy tool exists at all; deploy-related bash commands are hard denylisted outright (not ask-then-proceed) — consistent with CLAUDE.md's "Deploy is a human action forever" rule. |
| "Don't ask again this session" | **NO — not found** | No mechanism exists; every gated action re-prompts every time, confirmed by grep across the relevant files. |

**§39 overall: PARTIAL.** 8 of 9 specifically-named dangerous-operation categories are genuinely, individually gated — a real and fairly thorough safety net. The one confirmed gap (unconfirmed `pip install`/`npm install` via worker-agent tool handlers) is meaningful: a compromised or misbehaving dependency name could be installed without any human in the loop, unlike every other write/destructive action in the same tool surface.

**Production Enhancement Plan:** Add the same `session`-based confirmation check that `run_migration_h` already uses (`if session is None: return "[BLOCKED]..."`) to `npm_install_h`/`pip_install_h`, and route them through `chat_agent.py`'s `_confirm()` when called interactively — this mirrors an existing, working pattern rather than inventing a new one.

## §103 Human Override

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Interrupt any agent mid-run | **YES** | `POST /api/tasks/{task_id}/stop` — checked inside the LLM-call loop itself (`registry.set_abort`), not only at pre-defined interrupt points. Caveat: takes effect after the in-flight tool call completes, not instantaneously. |
| Resume with injected input | **YES** | `POST /api/tasks/{task_id}/resume` — clears abort flag, injects message/files. |
| Take over a task / edit a plan / reject one step and resume from that exact point | **NO — not found** | No plan-editing API endpoint exists anywhere. The only plan-level control is binary approve/reject of the *entire* PM/Architect/Decomposer output via `resume_pipeline(approved: bool)` — not per-step editing. |

**§103 overall: PARTIAL.** Stop/resume at the task level is real and reasonably fine-grained (checked continuously, not just at fixed gates). Step-level plan editing — the more granular "reject just this one step" capability the question asks about — does not exist.

---

## Summary — Batch 7

- **YES:** 13
- **PARTIAL:** 10
- **NO:** 6

**Findings worth flagging:**
1. The "5 guardian agents" as literally described (separate memory, separate tools, architecturally distinct tier) is not what exists — what exists (7 scheduled scan-and-suggest agents sharing the standard agent infrastructure) is real and reasonably well-built, but auditing it as if it were the described separate tier would overstate the architecture's actual separation.
2. Pause/resume and human-interrupt coverage is genuinely strong for 2 of 3 execution paths (pipeline, chat) but absent for plain worker agents — the majority of the fleet by file count.
3. Dependency-install commands are a real, specific hole in an otherwise fairly thorough approval-gating system.
