# Batch 7 — Autonomous Ranger/Guardian Agents, Human Interaction, Human Approval, Human Override

Covers §12, §64, §13, §39, §103. Evidence-only, file:line cited.

**Remediation pass (2026-08-11):** every implementable checkpoint below was
converted to YES. Two whole-tier claims (§12/§64's "architecturally separate
5-agent tier"/"separate memory"/"automatic planning") and two whole-graph
claims (§13's worker-agent in-place pause/resume, §103's step-level plan
editing) remain genuinely out of scope for a remediation pass — reasoning
and evidence for each is given inline, not just asserted. See the Summary
for the full before/after.

---

## §12 / §64 — "5 Guardian/Ranger Agents"

**The literal claim (5 agents, architecturally separate from normal task agents, with separate memory/tools, monitoring Docker/logs/Git/architecture) does not exist as described.** No agent, class, or module named guardian/ranger/sentinel/watchdog/overseer exists anywhere in the codebase — the only hit for those words is a single hypothetical comment in `base_graph.py:2448` ("...like 'fleet-scan' from a guardian agent's periodic scan"), not real code.

**What does exist, and is real:** the "Day 9 Fleet Enhancement" system — originally 5 agents, then 7 (Days 48-50 gap-closure added `architecture_reviewer`/`dependency_security_agent`), now **8** as of this pass (`agent_performance_reviewer`, `agent_debugger`, `agent_advisor`, `knowledge_curator`, `quality_auditor`, `architecture_reviewer`, `dependency_security_agent`, `monitoring_agent`).

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Architecturally separate 5-agent tier | **NO — impossible without changing project scope** | See "Scope-limited findings" below. |
| Separate memory | **NO — impossible without changing project scope** | Same section. |
| Separate tools | **PARTIAL — unchanged, not a gap** | `SCAN_TOOLS`/`FLEET_APPLY_TOOLS` are a bespoke subset, but built from the same primitive tool specs (`write_file`, `edit_file`, `run_tests`, etc.) shared fleet-wide — an intentional architectural characteristic (reuse over duplication), not something to "fix". |
| Autonomous scheduling (no manual trigger) | **YES** | `main.py::_fleet_agents_scan_loop` (`app/main.py:136`) — real `while True: await asyncio.sleep(interval*3600)` loop, now runs all **8** scan functions on a config-driven interval (default 4h). |
| Codebase monitoring | **PARTIAL — unchanged, not a gap** | Covered by scan phases (architecture/dependency/quality checks), folded into the agents' individual scan logic rather than one distinct "codebase monitor" module — an architectural characteristic, not a defect. |
| Log monitoring | **YES** (was NO) | `monitoring_agent.py::run_monitoring_agent_scan` (`app/agents/monitoring_agent.py:216`), wired into `_fleet_agents_scan_loop` (`app/main.py:197`). Honest caveat: this deployment's own logging (`app/observability/logging_context.py`) writes structured JSON to stdout only, no file sink, so file-based `read_logs` is included for repos that configure one but the always-functional signal here is real Docker container log tailing (`docker_logs`, read-only). |
| Docker monitoring | **YES** (was NO) | Same scan function — read-only `docker_ps`/`docker_logs` tools (never `docker_agent.py`'s write-capable tools, which stay human-gated per its own contract) plus a deterministic, independently-re-run pre-check, `app/fleet/docker_health.py::check_docker_containers` (line 29), flagging unhealthy/restarting containers, logged non-fatally before the LLM scan runs. |
| Git monitoring | **YES** (was NO) | Same scan function — `git_status` tool plus a deterministic pre-check, `app/fleet/git_worktree_health.py::check_git_worktree` (line 29), flagging a diverged/behind-upstream branch or an unusually large number of uncommitted changes (possible crashed/unfinished agent run). |
| Architecture monitoring | **YES** | `architecture_reviewer` runs on the scheduled loop, unchanged. |
| Enhancement suggestions | **YES** | All 8 scan phases call `submit_enhancement_request`, creating real `EnhancementRequest` DB rows proactively, unchanged. |
| Bug detection | **YES** | `agent_debugger.py`, unchanged. |
| Automatic planning | **NO — impossible without changing project scope** | See "Scope-limited findings" below. |
| Approval workflow before code changes | **YES** | `POST /api/fleet/requests/{id}/approve` (RBAC-gated via `require_approver`), unchanged, still the only path to `_run_apply_phase`. |
| Never modifies code without approval | **YES** (was PARTIAL) | The real gap wasn't safety — it was UX: `architecture_reviewer`/`dependency_security_agent` (and by the same logic, `agent_advisor`/now `monitoring_agent`) have no `_apply` function, so an approval on their requests looked identical in the UI to a real code-changing approval. `_serialize()` (`app/api/fleet_dashboard.py:76`) now computes `autoApplicable` fresh from `_apply_dispatch()`'s own dict every time (never a stored/stale flag), and the dashboard (`apps/web/app/fleet/page.tsx`) shows a "Recommendation only" badge on the request *before* a human approves it, plus a neutral "no code was changed" note after, instead of looking like every other completed apply. |

**§12/§64 overall verdict: mostly YES, with two claims left as honest scope mismatches.** The real system (8 scheduled scan-and-suggest agents, approval-gated apply phase, now including genuine Docker/log/git self-monitoring) satisfies the *spirit* of "never modify code without approval" and "proactive monitoring" well. It is still not — and per the reasoning below, should not become — the architecturally-separate 5-agent supervisory tier with its own memory subsystem described in the original ask; that framing was a naming/scope mismatch from day one, not a bug to close.

---

## §13 Human Interaction

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Ask permission | **YES** | Real `interrupt()`-based `_confirm()` (`chat_agent.py:710-806`), backed by a `PendingApproval` DB row + SSE `confirmation_required` event. Unchanged. |
| Wait indefinitely | **YES** | No timeout on `interrupt()` — unchanged. |
| Present options (multi-choice) | **YES** (was NO) | New `ask_human_to_choose` tool (`app/agents/tools.py:7552`, dispatched at `chat_agent.py:2993`) and `ChatAgent._confirm_with_options()` (`chat_agent.py:816`) — a genuinely different decision shape from `_confirm()`'s Y/N pause (which is completely untouched; every existing dangerous-operation gate behaves exactly as before). Reuses the *same* real `interrupt()`/`Command(resume=...)` pause primitive and thread/checkpointer as `_confirm()` — `resume()` now accepts an optional `selected` id (`chat_agent.py:3566`). Proven end-to-end against the real compiled graph (pause → resume with a selection → tool result carries the chosen option), not just asserted. A malformed/stale `selected` not among the real options is rejected, not silently trusted. |
| Recommend choices | **YES** (was PARTIAL) | `ask_human_to_choose`'s `recommended_option` field and `request_clarification`'s new optional `options`/`recommended_option` fields (`app/agents/tools.py`, `REQUEST_CLARIFICATION_TOOL`) give both the chat path and the ~76-83 plain worker agents a structured recommendation field, not just prose buried in free text. |
| Pause/resume execution | **PARTIAL — unchanged, genuinely out of scope for worker agents** | See "Scope-limited findings" below. Chat's own pause/resume got *more* capable this pass (multi-choice + "don't ask again", both below), so the gap that remains is specifically the ~76-83 plain worker agents, not chat. |
| Understand follow-up replies / continue from previous context | **PARTIAL — unchanged, same split as above** | Real for pipeline and chat; `request_clarification`'s "ends the run, a future run receives the answer" remains the honest working substitute for plain worker agents (now carrying structured options/recommendation, per above). |

**§13 overall: mostly YES.** The chat confirmation mechanism gained a real, tested multi-choice capability and structured recommendations without touching any existing binary-gate call site's behavior. Coverage across agent execution paths is still uneven (pipeline and chat are the two paths with true pause/resume; plain worker agents are not) — that specific gap is architecturally out of scope for this pass, reasoned through below rather than left unexplained.

## §39 Human Approval System

Confirmed real, specific gates (not a blanket policy — each checked individually):

| Dangerous operation | Gated? | Evidence |
|---|---|---|
| Delete a file | **YES** | `chat_agent.py:1404-1419`. Unchanged. |
| Overwrite an existing file | **YES** | `chat_agent.py:1336-1338` (note: new-file writes are not gated, only overwrites). Unchanged. |
| `git push` (incl. force) | **YES** | Unchanged. |
| `git reset --hard` | **YES** | Unchanged (non-hard resets not gated). |
| Dangerous bash command | **YES** | Unchanged. |
| `undo_changes` (`git checkout --`) | **YES** | Unchanged. |
| DB migration | **YES, with defense-in-depth** | Unchanged — gated in interactive session, hard-blocked in production regardless of confirmation, blocked entirely outside an interactive session. |
| `seed_database` | **YES** | Unchanged. |
| **Dependency upgrades** | **YES** (was NO) | `npm_install_h`/`pip_install_h` (`app/agents/tools.py:11982`, `:12053`) now require a session with `request_confirmation` — `session is None` (true for every real ~32-worker-agent caller of `make_chat_handlers()`, confirmed by grep across all call sites) hard-blocks outright with `[BLOCKED]`, exactly mirroring `run_migration_h`/`seed_database_h`/`undo_changes_h`'s existing pattern immediately above them in the same file — not a new mechanism. `TOOL_MANIFEST["npm_install"/"pip_install"].notes` documents the gate. |
| **Deployment** | **N/A by design** | Unchanged — no deploy tool exists at all; deploy-related bash commands are hard denylisted outright. |
| "Don't ask again this session" | **YES** (was NO) | `ChatSession.remembered_confirmations: set[str]` (`app/models/chat.py:54`); `ConfirmActionRequest.remember: bool = False` (`app/api/chat.py`, defaults False — every existing client that doesn't send the field is unaffected); `_confirm()` (`chat_agent.py:710`) auto-approves (skipping the pause, but still writing an audit-trail decision and pushing a `confirmation_auto_approved` SSE event) when the current tool name is in the session's remembered set, and records it there only when the human approved *and* opted in via `remember=True` on that specific decision. Scoped to the in-memory `ChatSession`'s own lifetime (cleared on restart/session deletion) — genuinely "this session" only. Cannot weaken the hard, confirmation-independent blocks (e.g. production migrations) since those checks run in the caller *before* `_confirm()` is ever invoked. |

**§39 overall: fully YES.** Both confirmed gaps (unconfirmed dependency installs; no session-scoped "don't ask again") are closed using the codebase's own existing patterns — no new safety mechanism invented, no existing gate weakened. Verified: the two closed gaps + all 8 previously-YES gates still pass their tests.

## §103 Human Override

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Interrupt any agent mid-run | **YES** | `POST /api/tasks/{task_id}/stop`, unchanged. |
| Resume with injected input | **YES** | `POST /api/tasks/{task_id}/resume`, unchanged. |
| Take over a task / edit a plan / reject one step and resume from that exact point | **NO — impossible without changing project scope** | See "Scope-limited findings" below. |

**§103 overall: PARTIAL, unchanged from before — reasoned through, not just re-asserted.** Stop/resume at the task level is real and fine-grained. Step-level plan editing remains a graph-topology change, not a wiring fix — see below.

---

## Scope-limited findings (verified impossible without changing project scope)

These four claims were re-examined against the current code, not just carried forward. Each is a genuine architectural boundary, with the specific evidence for why closing it is a new-capability decision rather than a bug fix.

**1. §12/§64 — "Architecturally separate 5-agent tier" / "separate memory".** The 8 fleet self-improvement agents use the identical `AGENT_CONTRACT` + `_register()` registration mechanism, the same `memory_hook_node`, the same `memory_embeddings` table, and the same process-local `LessonStore` as all ~76+ other agent files. Building a literally separate memory subsystem and tool registry for this subset would mean maintaining a second, parallel version of infrastructure that already works fleet-wide — the kind of duplicated abstraction this codebase's own conventions (and CLAUDE.md-style guidance generally) argue against. This is a scope decision about whether a second architecture tier is wanted at all, not a defect in the existing one.

**2. §12/§64 — "Automatic planning".** Confirmed by tracing the only real planning system in the codebase: `run_planning_pipeline` (`app/pipeline/graph.py:144`) is called exclusively from `app/api/agents.py:140` — a human/API-triggered endpoint — never from `_fleet_agents_scan_loop` or any scheduled loop. No dedicated agent proposes multi-step plans unprompted. Building one (an autonomous "here's what I think we should do next" planning agent that runs on a schedule) is genuinely new capability — a new agent module, role file, verification contract, and tests — not a wiring fix like the Docker/log/git monitoring closed above.

**3. §13 — True in-place pause/resume for the ~76-83 plain worker agents.** `base_graph.py` does have a real Postgres checkpointer (`_agent_checkpointer`, `app/agents/base_graph.py:65`) — but it exists for crash/reboot recovery of an in-flight run (AUDIT_Q_BATCH08 §14), not human-approval pausing: grep confirms `interrupt()` and `Command(resume=...)` are never called anywhere in `base_graph.py`, unlike `pipeline/graph.py`'s `interrupt_before=["human_review"]` or `chat_agent.py`'s per-tool-call `interrupt()`. A genuine fix needs (a) a meaningful interrupt point in one shared graph topology used by ~76-83 structurally different agents, and (b) a resume dispatcher that can rebuild the correct tool_handlers/verification_cfg for whichever specific agent module a paused run belongs to — since each agent file builds its own handlers/tools inline rather than from a shared registry. This is the identical missing piece AUDIT_Q_BATCH08 already documented as a deliberately out-of-scope "per-agent-type graph-rebuild registry that doesn't exist yet" for the structurally identical auto-resume-on-reboot problem. `request_clarification`'s "ends the run, a future run receives the answer" remains the honest, working substitute — extended this pass with structured `options`/`recommended_option` fields (the maximum safely implementable improvement without that larger investment).

**4. §103 — Step-level plan editing.** `resume_pipeline(task_id, approved: bool)` (`app/pipeline/graph.py:207`) is binary at the whole-plan level — confirmed by its signature, there is no step-addressable parameter. A real "reject just this one step and resume from that exact point" needs: a plan data model with addressable steps, a new API surface for editing at that granularity, and resuming the graph from a specific mid-plan checkpoint rather than the single `human_review` interrupt point compiled into `build_graph()` (`app/pipeline/graph.py:134`) — a graph-topology change, not an endpoint or tool addition.

---

## Summary — Batch 7

**Before this pass:** re-tallied directly against the original table above (33 counted checkpoints, excluding the 1 explicit N/A "Deployment" row) — **17 YES / 6 PARTIAL / 10 NO**. Note: the original document's own summary line stated "YES: 13, PARTIAL: 10, NO: 6", which does not match a row-by-row count of its own table; that arithmetic error is corrected here rather than carried forward.

**After this pass:** same 33 checkpoints, re-tallied — **25 YES / 4 PARTIAL / 4 NO** (all 4 remaining NO rows now explicitly reasoned as out-of-scope in "Scope-limited findings" above, not left as unexplained gaps; both remaining PARTIAL rows in §12/§64 are honest architectural characteristics, not defects — "separate tools", "codebase monitoring" — and the two remaining PARTIAL rows in §13 are the one genuinely uneven-coverage item, pause/resume and follow-up understanding for plain worker agents, reasoned through in finding #3 above).

**Real changes made:**
- `npm_install_h`/`pip_install_h` gated behind the same session-confirmation pattern as `run_migration_h`/`seed_database_h`/`undo_changes_h` (`app/agents/tools.py`).
- `monitoring_agent.py` gained a SCAN phase (`run_monitoring_agent_scan`) wired into `_fleet_agents_scan_loop`, using read-only `docker_ps`/`docker_logs` plus two new deterministic pre-check modules, `app/fleet/docker_health.py` and `app/fleet/git_worktree_health.py` — the fleet is now 8 agents, not 7.
- Fleet dashboard (`app/api/fleet_dashboard.py`, `apps/web/app/fleet/page.tsx`) surfaces `autoApplicable` per request, computed live from `_apply_dispatch()`, closing the "approval that silently does nothing" UX gap.
- New `ask_human_to_choose` tool + `ChatAgent._confirm_with_options()` give the chat path real structured multi-choice with a recommended option, reusing the existing `interrupt()`/checkpointer pause primitive — `_confirm()`'s existing binary gates are untouched.
- `request_clarification` gained optional structured `options`/`recommended_option` fields for the ~76-83 plain worker agents.
- `ChatSession.remembered_confirmations` + `ConfirmActionRequest.remember` implement session-scoped "don't ask again", explicitly unable to weaken the hard confirmation-independent blocks.
- All above: ruff clean, mypy clean, full backend pytest suite green, frontend vitest/tsc/eslint green. New/changed tests: `tests/test_audit_q_batch07_guardian_human_interaction.py` (27 tests), plus additions to `tests/test_fleet_dashboard_api.py` and `apps/web/app/fleet/page.test.tsx`.

**Findings worth flagging (unchanged from before, still true):**
1. The "5 guardian agents" as literally described (separate memory, separate tools, architecturally distinct tier) is not what exists, and per the reasoning above, deliberately shouldn't be built that way — the real system reuses shared infrastructure by design.
2. Pause/resume and human-interrupt coverage is genuinely strong for 2 of 3 execution paths (pipeline, chat — chat gained real capability this pass) but remains architecturally absent for plain worker agents, the majority of the fleet by file count — a larger, explicitly-scoped-out decision, not an oversight.
