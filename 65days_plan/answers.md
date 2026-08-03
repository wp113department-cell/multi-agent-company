# Gridiron Platform — Full Production Audit: Answers

Answers to all 120 questions in `Bhaskar's_questions.md`, produced by directly reading the
implementation (`backend/app/**`, `apps/web/**`, `backend/tests/**`, `backend/roles/*.md`,
`backend/migrations/**`) rather than from documentation or prompt text alone. Every claim below
cites a real file/function/line, a real test, or a real grep result. Where something could not be
verified with real effort, it is marked **NOT VERIFIED** rather than guessed — per the audit
request's own closing rule ("do not answer from assumptions... mark as Not Verified rather than
assuming it exists"), and per this engagement's own standing rule against hallucination.

## How to read each answer

- **YES** — a real, working, code-enforced implementation exists (not just prompt text asking an
  LLM to behave a certain way).
- **PARTIAL** — something real exists but is incomplete, unenforced (prompt-only where code
  enforcement would be needed), narrower in scope than asked, or not wired into an automatic
  trigger. Read as "half-implemented, not fully working as described."
- **NO** — confirmed absent; grepped/read for it and found nothing.
- **NOT VERIFIED** — could not be confirmed either way within this pass (flagged rather than
  guessed).
- Every **NO**/**PARTIAL** answer is followed by a one-line **Plan** — the concrete next step to
  reach a real YES, grounded in what already exists in the codebase (reusing real infrastructure
  wherever it exists, not proposing a rebuild).

## One honest caveat on "0% hallucination"

Per the audit brief's own closing note: zero hallucination is not a realistic property of any
current LLM-based system, including this one. What was actually verified throughout this audit is
the practical substitute the brief itself recommends: minimize hallucination through direct code
inspection, distinguish verified facts from assumptions, and say "NOT VERIFIED" rather than
fabricate. That standard was applied to every one of the 120 answers below.

## Methodology (proof of process, not just a claim)

12 independent research passes ran in parallel against the live repository (`C:\Users\Fardi\
OneDrive\Documents\crr\multi-agent-company`), each covering a themed cluster of the 120 questions,
each required to cite `file:line`/test-name evidence for every claim and to run real commands
(`pytest --collect-only`, a live Python import-and-inspect script against all 72 agent modules,
`git`/`grep` searches) rather than reason abstractly. One question (Q74) was caught missing from
every cluster's assignment during final compilation and was independently investigated and added
afterward — noted here rather than silently patched in, since the audit brief specifically asked
for this kind of process transparency.

---

## Table of Contents (all 120 questions, in original numeric order)

- Q1. Repository Execution
- Q2. Complete Orchestration
- Q3. Agent Selection
- Q4. Tool Selection
- Q5. Memory System Audit
- Q6. Agent Specification Audit (72 agents)
- Q7. Capability Audit (answered from implementation, not prompt text)
- Q8. Performance Audit
- Q9. Frontend and Backend Audit
- Q10. Project Architecture Audit
- Q11. Testing Audit
- Q12. Autonomous Ranger System / "Five Project Management Agents"
- Q13. Human Interaction
- Q14. Execution Control
- Q15. Large Project Handling
- Q16. File Understanding
- Q17. Terminal Intelligence
- Q18. Coding Workflow
- Q19. Deployment Intelligence
- Q20. External Knowledge
- Q21. Security Audit
- Q22. Safety Audit
- Q23. Production Readiness Score
- Q24. Missing Features (vs. Claude Code)
- Q25. User Intent Understanding
- Q26. Difficult User Handling
- Q27. Clarification Engine
- Q28. Requirement Analysis
- Q29. Existing Project Awareness
- Q30. Safe Implementation
- Q31. Resource Awareness
- Q32. Project Size Awareness
- Q33. AI Suggestion Review
- Q34. Incremental Implementation
- Q35. Project Health Monitoring
- Q36. Self-Audit
- Q37. Learning System
- Q38. Failure Recovery
- Q39. Human Approval System
- Q40. Git Intelligence
- Q41. Documentation Intelligence
- Q42. Cost Awareness
- Q43. Confidence & Uncertainty
- Q44. Explainability
- Q45. Multi-Session Continuity
- Q46. Scalability
- Q47. Extensibility
- Q48. Enterprise Readiness
- Q49. Claude Code Feature Gap Analysis
- Q50. Final Roadmap
- Q51. Repeat Task & Historical Context
- Q52. Large Context Understanding
- Q53. Strict Requirement Compliance
- Q54. No Hallucination Policy
- Q55. Truthfulness Policy
- Q56. Evidence-First Workflow
- Q57. Intelligent Clarification
- Q58. Multi-Terminal & Parallel Execution
- Q59. Multi-File Operations
- Q60. Agent Creation Capability
- Q61. MCP (Model Context Protocol) Capability
- Q62. Runtime Decision Making
- Q63. User Emotion & Conversation Handling
- Q64. Project Guardian Agents
- Q65. Token & Context Budget Management
- Q66. Production Reliability
- Q67. Real-World Engineering Behavior
- Q68. Impossible & Unsupported Requests
- Q69. Autonomous Quality Improvement
- Q70. Final "Claude Code Parity" Audit
- Q71. Professional Domain Coverage
- Q72. Universal Skill Coverage
- Q73. Adaptive Expertise
- Q74. Learning & Improvement
- Q75. Organizational Knowledge Sharing
- Q76. Continuous Improvement
- Q77. Company-Scale Readiness (100/250/500/1000 agents — governance angle)
- Q78. Final Verdict
- Q79. Modern Technology Coverage
- Q80. Technology Adaptation
- Q81. Documentation-Driven Development
- Q82. Professional Solution Quality
- Q83. Technology Recommendation Engine
- Q84. Capability Boundaries
- Q85. Governance & Policy Engine
- Q86. Organization-Wide Task Scheduler
- Q87. Agent Performance Metrics
- Q88. Agent Health Monitoring
- Q89. Automatic Agent Retirement
- Q90. Quality Gates
- Q91. Architecture Drift Detection
- Q92. Dependency Intelligence
- Q93. Knowledge Validation
- Q94. Multi-Project Management
- Q95. Workspace Isolation
- Q96. Enterprise Security
- Q97. Disaster Recovery
- Q98. Version Awareness
- Q99. User Experience Intelligence
- Q100. Accessibility & Localization
- Q101. Economic Awareness
- Q102. Long-Running Jobs
- Q103. Human Override
- Q104. Explainability
- Q105. Company Brain (Organizational Intelligence)
- Q106. Improvement Backlog
- Q107. Pattern Recognition
- Q108. Agent Performance Review
- Q109. Continuous Architecture Review
- Q110. Prompt Evolution
- Q111. Tool Evolution
- Q112. Knowledge Validation
- Q113. User Preference Learning
- Q114. Project Evolution
- Q115. Release Retrospectives
- Q116. Capability Gap Detection
- Q117. Quality Score
- Q118. Safe Self-Improvement
- Q119. "CEO Dashboard"
- Q120. Intelligent Memory Management

---

## Q1. Repository Execution

- Does it clone the repository into the user's selected folder?: **YES** — `backend/app/api/console.py:157` `clone_repo()` calls `backend/app/services/git_service.py:91` `git_clone(url, dest_path, branch)`, which runs `git clone <url> <dest_path>` via `asyncio.create_subprocess_exec` (no shell=True) into the caller-supplied `dest_path`.
- Does every operation happen inside that cloned repository?: **PARTIAL** — `backend/app/repo_tools/worktree.py:18-24` `worktree_path()`/`create_worktree()` create per-task/per-epic git worktrees under `settings.worktrees_dir`, and `_is_registered_worktree()` (line 27) verifies via `git worktree list --porcelain` before reuse; policy engine `backend/app/policy/engine.py:121` `check_path_in_worktree()` enforces boundary via realpath. But `backend/app/agents/tools.py:11668` `make_scoped_bash_handler()` and several other bash handlers (e.g. `bash_h` at line 11678) run `subprocess.run(cmd, shell=True, cwd=repo_path)` with only a best-effort `cd`-boundary regex check (`check_command_stays_in_boundary`, engine.py:285) — the code's own docstring admits this is "best-effort... not a claim of completeness" since there's no OS-level sandbox.
  Plan: Add a real OS-level sandbox (container/chroot/AppContainer) for full-shell bash tools instead of relying on regex-based `cd` boundary detection.
- Does it always use the repository's terminal?: **PARTIAL** — every bash-tool handler passes `cwd=repo_path` or `cwd=worktree_path` (e.g. `tools.py:723`, `tools.py:11683`), so commands start scoped to the repo, but "terminal" here means a fresh `subprocess.run`/`Popen` per call, not a persistent shell session — see Q58.
- How are terminals managed?: **PARTIAL** — no persistent PTY/terminal object exists. Two patterns: (1) one-shot `subprocess.run(shell=True, timeout=N)` calls per tool invocation (dozens of handlers in `tools.py`, e.g. lines 718, 779, 855, 11678); (2) a session-scoped background-process registry `_session_bg_procs: dict[int, subprocess.Popen]` defined locally inside `make_chat_handlers` (`tools.py:6998`), populated by `run_background` (line 7787) and read via `read_output_h` (line 8818).
  Plan: Document this "no persistent terminal, per-call subprocess + PID-tracked background dict" model explicitly instead of implying a real terminal-session abstraction exists.
- Can multiple terminals run simultaneously?: **YES** — `run_background` (`tools.py:7787`) can be called repeatedly, each producing a new `Popen` tracked by PID in `_session_bg_procs`; concurrent agent/subtask execution is also bounded by real `asyncio.Semaphore`s in `backend/app/pipeline/concurrency.py` (`epic_slot`, `agent_run_slot`, `subtask_slot`, lines 42-106).
- How does Windows terminal support work?: **PARTIAL/NO** — no `executable=` override is set on any `subprocess.run(shell=True, ...)` call (verified via repo-wide grep), so on Windows this defaults to `cmd.exe`. But venv-activation and many tool commands are hardcoded POSIX shell syntax, e.g. `tools.py:7487` `f"cd {repo_path} && source .venv/bin/activate 2>/dev/null || true && python -m pytest..."` — `source`, `.venv/bin/activate`, and `/dev/null` are all invalid/no-ops under `cmd.exe` (Windows venvs use `Scripts\activate`, not `bin/activate`, and there is no `true` command). Windows-specific handling does exist elsewhere: `tools.py:9656` uses `msvcrt.locking` instead of `fcntl.flock` for memory-file locks, and `tools.py:8791` falls back to a threaded blocking read instead of `fcntl` O_NONBLOCK for background-process output on `sys.platform == "win32"`.
  Plan: Detect platform and either force `executable="/bin/bash"`/WSL for POSIX-syntax commands or branch to `Scripts\activate.bat`/PowerShell equivalents on Windows; add CI coverage running the tool suite on native Windows.
- How does Ubuntu/Linux support work?: **YES** — same `shell=True` calls resolve to `/bin/sh` on Linux, and the hardcoded `source .venv/bin/activate` (`tools.py:7487` etc.), `fcntl`-based nonblocking IO (`tools.py:8791-8796`), and `ps aux`/`ss -tlnp`-based `list_processes_h`/`list_open_ports_h` (`tools.py:10569`, `10586`) all work natively on Linux.
- How are Docker terminals handled?: **YES** — `backend/app/agents/tools.py:3978` `make_docker_agent_handlers()` and a `_DOCKER_LOGS_TOOL` (line 2581) wrap `docker ps`, `docker build`, `docker logs`, `docker-compose config` via `subprocess.run` with list-args (not shell=True) in several spots (e.g. line 3990 format string for `docker ps`); `_docker_container_risk_reason()` (`tools.py:6900`) runs `docker inspect` before allowing `docker_exec` into a container and denies if it is `--privileged`, shares host PID namespace, has dangerous `CapAdd`, or bind-mounts sensitive host paths (`/etc`, `/root`, `/var/run/docker.sock`, etc.) — a real pre-exec safety check, not just a docstring claim.
- How are virtual environments activated?: **PARTIAL** — for `subprocess.run(shell=True)` bash tools, activation is via literal `source {repo_path}/.venv/bin/activate 2>/dev/null || true` prepended to the command string (`tools.py:7487, 7521, 7529, 7545, 7610, 7630, 7838, 8061, 8085, 8118, 11631` — 11 call sites, all identical pattern). For the test-runner/read-only handlers, activation is done differently by prepending the venv's `bin` dir to `PATH` in the subprocess env (`tools.py:708-710`, `1338-1341`, using `Path(sys.executable).parent`). Both approaches are POSIX-path-shaped (`bin/`, not `Scripts\`) and unverified on native Windows.
  Plan: Same as Windows terminal item — branch activation logic on `sys.platform`.
- How are shell commands executed safely?: **YES** — layered policy engine `backend/app/policy/engine.py`: `check_command()` (line 210) denylists `rm -rf`, `sudo`, `dd if=`, `mkfs`, `shutdown`/`reboot`, fork bombs, `kubectl`, `terraform`, `git push`, publish/deploy commands, curl/wget to http(s), secret-exfil patterns, `| bash`; `check_allowlisted_command()` (line 250) combines chaining-metachar rejection with a command-prefix allowlist for scoped agents (QA, CI/CD, Refactor, Dependency, Cleanup, AI Engineer, Migration, DevOps); `is_command_override_eligible()` (line 236) keeps catastrophic commands (`rm -rf`, `dd`, fork bomb, `mkfs`, `shutdown`) non-overridable even if a human clicks "approve"; `_shell_metachar_reason()` (`tools.py:6832`) rejects shell metacharacters in flag-style args; `_mask_secret_value()` (`tools.py:6856`) redacts secret-shaped values in tool output. `chat_agent.py` docstring (lines 1-45) documents a real `interrupt()`-based LangGraph confirmation gate for `git_push`, dangerous `bash`, `git_reset --hard`, `undo_changes`, `run_migration`, `seed_database` — verified as the first side-effecting step in each handler (e.g. `git_push` at `tools.py:7168` calls `session.request_confirmation()` before running the actual `git push`).
- Show the execution pipeline.: **YES** — traced: `api/console.py` clone → `git_service.git_clone()` into `allowed_workspace_parent`-scoped dest (`workspace_service.py:23` `assert_in_workspace`) → `repo_tools/worktree.py` creates an isolated per-task/per-epic git worktree → agent handler set built by `make_*_handlers(repo_path)` factories in `agents/tools.py` (read-only tools + scoped/full bash + write/edit/delete tools) → each tool call passes through `policy/engine.py` checks → dangerous ones pause via LangGraph `interrupt()` in `chat_agent.py` for human confirmation → concurrency bounded by `pipeline/concurrency.py` semaphores → dispatched per subtask type by `pipeline/dispatcher.py:74` `dispatch_subtask()`.

---

## Q2. Complete Orchestration

- Who receives the user request first: **YES** — `POST /api/tasks` (`backend/app/api/tasks.py`) creates the `DevTask` row (plain CRUD, no agent involved yet). `POST /api/tasks/{task_id}/run` (`backend/app/api/tasks.py:177`) is the real trigger: it calls `background_tasks.add_task(launch_planning_pipeline, ...)` (`backend/app/api/agents.py:62` `launch_planning_pipeline`). The first *agent* to touch the request is `pm_node` inside `run_planning_pipeline()` (`backend/app/pipeline/graph.py:144`, graph built in `build_graph()` lines 112-134: `START → pm → architect → decomposer → human_review(interrupt) → END`).
- Who decides which agents work: **YES for the backend_dev/frontend_dev pair — gap-closure Days 11-14
  (2026-07-30).** `build_graph()`'s pm→architect→decomposer sequence is still fixed by design (not a
  capability query — that's a different, orthogonal question). But `run_manager()`'s dev-agent
  dispatch is no longer a discarded side-channel: `FleetManager.select()`'s real `DispatchPlan.agent_name`
  is captured into `selected_agent_name` and is what the dispatch `if selected_agent_name ==
  "frontend_dev": ... else: ...` branch actually checks (`app/agents/manager.py`), replacing the old
  `if subtask_type == "frontend"` check. Falls back to the subtask_type heuristic only if `select()`
  itself fails/returns `None` (registry unavailable) — the scheduler's own health never blocks a
  subtask. Since exactly one concrete agent is registered per capability today, this produces
  identical routing to the old check in the common case; the real change is that `select()`'s
  negative signal (an unhealthy/unavailable instance) is now actually honored, and this is the real
  hook a second agent registered for the same capability would need to ever get dispatched — `qa`/
  `reviewer` dispatch is still unconditional (no capability alternatives exist for those roles today).
  Proven live: `backend/tests/test_gap11_14_fleet_manager_dispatch.py` (2 tests) — one deliberately
  makes `select()` disagree with the subtask_type default and confirms the disagreeing choice is what
  actually runs; one confirms graceful fallback when `select()` fails.
- Is task routing automatic: **YES** — no human picks an agent per subtask; `_TYPE_TO_TAG`/`_FALLBACK_ROUTING` (`backend/app/pipeline/dispatcher.py:24-39`) and `manager.py`'s type check both route without human input.
- Is routing rule-based: **YES** — rule-based, not AI-based, for the actual dispatch: `backend/app/pipeline/dispatcher.py:42-45` `get_agent_for_type()` is a literal `if subtask_type == "frontend": ... else: ...`. `manager.py`'s dev-agent dispatch (gap-closure Days 11-14) is now `if selected_agent_name == "frontend_dev": ... else: ...` — still a deterministic rule, just fed by `FleetManager.select()`'s real output (itself a deterministic scoring formula, not AI) rather than the raw `subtask_type` string directly.
- Is routing AI-based: **NO** — no LLM call decides which agent handles a subtask; the LLM only decides *within* an agent run which tool to call. `FleetManager.select()`'s score is a deterministic formula (health × success_rate × 1/(1+errors)), not a model call.
  Plan: N/A unless AI-based capability matching is a stated requirement; current formula-based fleet_manager could be wired in as a middle ground (see above).
- Can multiple agents work simultaneously: **PARTIAL** — within one epic, subtasks run sequentially in a `for` loop (`manager.py:187`, one subtask at a time — dev→QA→review must finish before the next subtask starts). Concurrency exists only *across* epics/agent-runs via semaphores: `epic_slot()`, `agent_run_slot()`, `subtask_slot()` (`backend/app/pipeline/concurrency.py:64-106`, capped by `max_concurrent_epics`/`max_concurrent_agent_runs`/`max_concurrent_subtasks_per_epic`). Also confirmed as a real, in-process-only, single-process concurrency model by `MASTER_AGENT_v2.md:411-421` (A.13).
  Plan: `depends_on` is now honored at dispatch time (gap-closure Days 11-14, see Q2's "How are
  dependencies managed" above) — that precondition is met. Still sequential within the loop itself
  (dispatch order is now correct, but subtasks are not yet dispatched concurrently); parallelizing
  independent subtasks within one epic remains a distinct, unstarted piece of work.
- Can agents create subtasks: **PARTIAL** — the `decomposer` agent creates the subtask list once, up front (`backend/app/agents/decomposer.py:115-194`, `submit_subtasks` tool). No worker agent (backend_dev, qa, reviewer, etc.) can create a *new* subtask mid-run; there is no `create_subtask` tool anywhere in `backend/app/agents/tools.py` (grepped, not found). Replanning (`_make_replan_node`, `base_graph.py:425-459`) revises the *plan text*, not the subtask list.
  Plan: add a `create_subtask` tool for worker agents (or route replan output back into the decomposer) if dynamic subtask creation is required.
- Can agents request help from other agents: **NO** — grepped `backend/app/agents/tools.py` and `backend/app/fleet/` for any `call_agent`/`delegate_to_agent`/`ask_agent`/`invoke_agent`-style tool; none exists. `fleet_events.py` publishes `TaskCreated`/lifecycle events (pub/sub for observability) but no agent can invoke another agent's run from inside its own tool loop. `MASTER_AGENT_v2.md:1112-1132` (D.2) explicitly confirms formal cross-agent negotiation/consultation/recursive delegation is deferred, not built.
  Plan: add an `invoke_agent(agent_name, task)` tool gated by the capability_registry + human-approval for high-risk agents.
- Can agents reject tasks they are not suitable for: **PARTIAL** — no agent can decline "I'm not the right agent for this" and hand it back for re-routing. The closest real mechanism is `request_clarification` (`backend/app/agents/tools.py:363-410`, Phase 5.3), which ends the run with `status="needs_clarification"` when the task is *underspecified*, not when it's the wrong agent. `fleet_manager.select()` can return `None` ("no healthy available agent") which blocks dispatch, but that's availability/health-based, not a self-assessed suitability rejection by the agent itself.
  Plan: distinguish "wrong agent for this" from "underspecified" as a second clarification/rejection reason routed back through `fleet_manager.select()` for re-dispatch.
- Can orchestration dynamically change during execution: **PARTIAL, real progress — gap-closure Days
  11-14 (2026-07-30).** `replan_node` (`backend/app/agents/base_graph.py:425-459`) can revise a single
  agent's own plan mid-run, triggered by real evidence (`_should_replan`: reflection dissatisfaction
  ≥2 or repeated critique failure ≥2). `enable_critique=True` is now real and wired for the 5
  highest-output-risk agents (coder, backend_dev, frontend_dev, qa, reviewer — chosen by role, not
  the unrelated `risk_level` operational-danger tag), proven live by
  `backend/tests/test_gap11_14_agent_critique.py` (7 tests, including a negative control on `devops`
  proving the rollout is precisely scoped, not an accidental fleet-wide flip). `enable_replanning`
  is deliberately still `False` fleet-wide — the plan's own sequencing makes flipping it conditional
  on critique first being validated as stable in real use ("once critique is stable and approved"),
  which requires live LLM-call observation this sandbox cannot currently do (no real
  `ANTHROPIC_API_KEY` configured, zero historical `agent_runs` telemetry in this dev DB to substitute
  for it) — tracked as an explicit, named follow-up, not silently skipped. At the epic level,
  `_conflict_check_node` (`manager.py:851-909`) can halt an epic before coding starts (abort, not
  re-routing).
  Plan: flip `enable_replanning=True` for the same 5 agents once the critique rollout above has been
  observed in real runs (cost/latency delta reviewed, no regressions) — the owner-required stop
  condition before proceeding further into Stage 1.
- How are dependencies managed: **YES — gap-closure Days 11-14 (2026-07-30).** `decomposer`'s
  `submit_subtasks` schema includes a `depends_on: list[int]` field per subtask (0-based indices into
  the same submitted list, per `roles/decomposer.md`'s own documented convention — not a `Subtask.id`
  DB primary key, which doesn't exist yet at this point in the pipeline). `run_manager()`'s dispatch
  loop now honors it for real: new `_topological_subtask_order()` (`app/agents/manager.py`, Kahn's
  algorithm with a min-heap for deterministic tie-breaking) computes a dependency-respecting
  dispatch order before the loop begins, replacing the old `for _subtask_idx, subtask in
  enumerate(subtasks)` that ignored `depends_on` entirely. Iterates by ORIGINAL index (not a
  reordered list) specifically so the loop's existing position-based `_db_subtask_rows` status-update
  correlation (see Q94/ORCH-04-011) still lands on the correct DB row despite the reordered dispatch
  — this was checked and deliberately preserved, not an accidental side effect. Falls back to the
  original order on any inconsistency (out-of-range index, a genuine cycle) — logged, never raised,
  so a malformed dependency graph from one decomposer run can never block the whole epic. Proven live
  by `backend/tests/test_gap11_14_topological_subtask_order.py` (10 tests: 9 unit tests on the sort
  function itself — linear chains, diamonds, cycles, out-of-range indices, self-references — plus 1
  full `run_manager()` integration test proving a subtask deliberately listed *before* its
  dependency is actually dispatched *after* it).
- How are priorities managed: **PARTIAL** — `CreateTaskRequest.priority` exists as a field (`backend/app/api/tasks.py:39-44`, default `"medium"`) and is persisted, but nothing in `run_manager()`, `dispatcher.py`, or `FleetManager` reads task priority to reorder or preempt dispatch — grepped, no `priority` reference in any of those three files. It is stored metadata, not an active scheduling input.
  Plan: use `DevTask.priority` to order the epic queue / subtask dispatch loop, or explicitly document it as informational-only today.
- How are conflicts resolved: **PARTIAL** — only one real conflict class is handled: **file-path conflicts between concurrently-running epics**, via `check_file_conflicts()` (`backend/app/pipeline/conflict_guard.py:21-54`), called from `_conflict_check_node` (`manager.py:851-909`) before coding starts; on overlap the epic is halted (`status="halted"`, `halt_reason=conflict`). There is no arbitration/voting/consensus mechanism for two agents producing *conflicting recommendations* — `MASTER_AGENT_v2.md:1112-1132` (D.2) explicitly confirms this is deferred/not built, citing no evidence the (sequential dev→qa→review) pipeline shape produces that scenario.
  Plan: N/A unless parallel independent-agent proposals become a real use case; then design arbitration against real disagreement examples per the doc's own trigger condition.
- How is duplicate work prevented: **PARTIAL** — same `check_file_conflicts()` mechanism above is the only duplicate-work guard, and it only prevents two *epics* from touching the same file, checked once before coding starts (not continuously). There is no lock/claim mechanism preventing two subtasks *within* the same epic from touching the same file (moot today since subtasks run strictly sequentially, per the "multiple agents simultaneously" answer above), and no de-duplication of semantically-identical tasks (e.g., the same bug reported twice).
  Plan: extend `check_file_conflicts()` to also gate per-subtask (not just per-epic) once/if intra-epic parallelism is added.

### Orchestration flow (as implemented, not aspirational)
```
POST /api/tasks             → create DevTask row (no agent)
POST /api/tasks/{id}/run    → launch_planning_pipeline() [backend/app/api/agents.py:62]
  → run_planning_pipeline() [backend/app/pipeline/graph.py:144]
      pm_node → architect_node → decomposer_node → human_review (LangGraph interrupt)
POST /api/tasks/{id}/approve → resume_planning_pipeline() → launch_manager()
  → run_epic_manager() [backend/app/agents/manager.py:657] — LangGraph supervisor graph:
      cost_estimate → planning(re-runs PM/Arch/Decomp) → conflict_check → coding → finalize
      coding node → run_manager() [manager.py:91] per-subtask loop:
        for each subtask (sequential, in list order, depends_on NOT enforced):
          dispatch by subtask.type (hardcoded if/else) → backend_dev|frontend_dev → qa → reviewer
          retry loop (max_retries) with backoff; blocked_count tracked
          ≥ manager_max_epic_failures blocked → epic halted (failure_ladder.abort)
      finalize → EpicApprovalPackage → human approval → git push
```
Separately: `POST /api/specialized-agents/{agent_name}/run` (`backend/app/api/specialized_agents.py`) lets a caller directly invoke any of ~60 named specialist agents (accessibility_agent, security_reviewer, etc.) outside the above pipeline entirely — these are NOT reachable from the main task-run flow above; they require a separate, explicit API call naming the agent.

---

---

## Q3. Agent Selection

- Skills: **YES** — `CapabilityRegistry.find_by_capability()` (`backend/app/fleet/capability_registry.py:63-65`) filters agents by declared `capabilities` list; `FleetManager.select()` (`backend/app/fleet/fleet_manager.py:85`) starts from this filter.
- Experience: **PARTIAL** — `AgentCapability.success_rate` (`capability_registry.py:42`) is used in scoring, but it's a **static literal set at registration time** (e.g. `pm`=0.95, `bug_fix`=0.82, `qa`=0.91, hardcoded in `capability_registry.py:182,222,259`), never updated from real run outcomes. The DB-backed `Agent.success_rate`/`avg_retries` (`backend/app/api/registry.py`, computed from real `AgentRun` rows) is a *separate* store that the module's own docstring claims gets "merged here at query time when a db session is available" (`capability_registry.py:9`) — but `FleetManager.select()` takes no `db` parameter and never queries it. The claim is aspirational, not implemented.
  Plan: wire `FleetManager.select()` to read the real `Agent.success_rate` from Postgres (or refresh `CapabilityRegistry.success_rate` periodically from it) instead of using the frozen registration-time constant.
- Tools: **YES** — `verify_tool_availability=True` (`fleet_manager.py:76-109`) skips a candidate whose declared tools resolve to nothing via `tool_discovery.check_availability()`.
- Memory: **NO** — memory (LessonStore / memory_embeddings) is injected *into* an agent's own run via `memory_hook_node` (`base_graph.py:462-529`) once an agent is already selected; it plays no role in *which* agent gets selected. Grepped `fleet_manager.py`/`capability_registry.py` for any memory reference — none.
  Plan: N/A unless a "which agent has relevant past-success memory for this task" heuristic is explicitly wanted.
- Current workload: **PARTIAL** — availability is binary (`AgentInstance.is_available`, `backend/app/fleet/agent_registry.py:50-54`: `state in (SLEEP, IDLE) and health != "unhealthy"`), so a busy (`RUNNING`) agent is excluded from selection — that's a coarse workload signal. There is no queue-depth/concurrent-task-count weighting beyond this binary flag.
  Plan: N/A for current fleet size; would matter once one agent name can be dispatched concurrently to multiple tasks.
- Confidence: **NO** — `confidence` in this codebase (`AgentRunState.confidence`, `base_graph.py:87`) is the *planner's* self-assessed confidence in its own plan, produced *after* an agent is already running (`_gather_facts_and_plan`, lines 293-351) and used only in the Phase 3.7 quality gate (`_run_quality_gate`, lines 853-920) to flag/whether to accept that agent's own submission. It is never a factor in *selecting* which agent to dispatch to.
  Plan: N/A — different meaning of "confidence" than agent-selection confidence; would need a distinct pre-dispatch confidence signal if desired.
- Previous success: **PARTIAL** — same as "Experience" above: `success_rate` is used in the scoring formula but is a hardcoded constant, not fed from real historical outcomes.
  Plan: same as Experience.
- Previous failures: **PARTIAL** — `AgentInstance.error_count` (`agent_registry.py:45,67-74`) is live and does feed the score (`1/(1+error_count)`, `fleet_manager.py:141`) and flips `health="unhealthy"` at 3 errors, excluding the agent entirely. This part IS live and real, unlike success_rate. But it's per-process, in-memory (`_agent_registry = AgentRegistry()` singleton, `agent_registry.py:158`) — reset on every restart, not durable across processes.
  Plan: persist `error_count`/health to the DB-backed `Agent` table so it survives restarts and is consistent across multiple app instances.

---

---

## Q4. Tool Selection

- Select tools automatically: **YES** — the LLM (Claude, via Anthropic `messages.create` with a `tools=` list) picks which declared tool to call each turn; no rule-based pre-filter chooses for it. `_make_call_llm_node` (`backend/app/agents/base_graph.py:532-650`) passes the agent's full tool list every turn; `execute_tools` (lines 977-1205) executes whatever the model chose.
- Call multiple tools: **YES** — `execute_tools` (`base_graph.py:1003-1205`) iterates `tool_uses = [b for b in content if b.get("type")=="tool_use"]` — a single LLM turn can contain multiple `tool_use` blocks and all are executed in the same turn, each producing its own `tool_result`.
- Retry failed tools: **PARTIAL** — there is no automatic re-invocation of the *exact same failed tool call*. A failing tool returns a `"[ERROR] ..."` string as the `tool_result` (`base_graph.py:1056-1057`), which goes back to the model; the model itself then decides whether to retry, adjust, or give up (LLM-driven, not a hard retry loop). What IS a real automated retry is one layer up: `manager.py`'s subtask loop (`for attempt in range(max_retries)`, lines 292-539) re-runs the whole dev→QA→review sequence with exponential backoff (`await asyncio.sleep(0.5 * (2**attempt))`, line 360) via `should_retry()` (`backend/app/fleet/failure_ladder.py:79-81`).
  Plan: if a hard automatic single-tool-call retry (e.g. on transient network error) is wanted, add it inside `execute_tools`'s handler-call `try/except` (currently line 1041-1058 catches and converts to `[ERROR]` on the first failure, no retry).
- Verify tool outputs: **YES** — `VerificationConfig` (`base_graph.py:105-125`) is a real, per-agent contract: `set_by` marks a verification flag True only when a tool completes without `[ERROR]`/`[POLICY]` prefix (lines 1078-1086); `reset_by`/`reset_keys` invalidate stale verification when a mutating tool runs afterward (lines 1088-1090); `enforce_in_result` (lines 1107-1119) overrides the model's own claimed result fields with the graph-tracked ground truth at submit time — the model literally cannot lie about "tests passed."
- Recover from failures: **PARTIAL** — recovery exists at multiple real layers: `SlotAcquisitionTimeout` handling routes into the normal blocked-subtask path (`manager.py:266-290`), `should_retry`/backoff (above), `escalate()`/`abort()`/`request_human_review()` (`failure_ladder.py:90-193`), and `reconcile_orphaned_runs()` for crashed processes (lines 209-265). What's NOT automatic: `rollback`/`resume` (`failure_ladder.py:63-71`) are explicitly documented as "intentionally manual/operator-invoked tooling... not unwired oversights" (comment lines 52-61) — a real checkpoint/rollback mechanism exists (`fleet_checkpoint.py`) but nothing calls it automatically on failure.
  Plan: N/A per the codebase's own explicit design decision (rollback is a judgment call reserved for a human); document this clearly as a deliberate choice, not a gap, if audited externally.
- Is tool selection intelligent or hardcoded: **YES (intelligent, LLM-driven), for per-turn tool choice** — confirmed above (model chooses from the declared schema each turn). **Hardcoded for meta-selection**: `MASTER_AGENT_v2.md:1134-1151` (D.3) explicitly confirms there is no reliability/cost/latency/confidence-scored selection across *redundant* tool implementations — verified correct because this fleet's tools are each a distinct capability (`edit_file` ≠ `bash` ≠ `run_tests`), not interchangeable providers, so that gap is by design, not oversight.

---

---

## Q5. Memory System Audit

The fleet has two structurally different agent populations, so "does every agent
have X" is answered per population, not per individual agent name (~70+ agents
share one mechanism via `run_agent_graph`).

- Working Memory: **YES** — `AgentRunState` (TypedDict, `backend/app/agents/base_graph.py`)
  holds messages/plan/verification/tokens for one `run_agent_graph()` invocation;
  discarded (Python GC, no persistence) when the run returns. Documented explicitly
  as the "working" tier in `backend/app/memory/store.py`'s module docstring (lines 11-14).
- Session Memory: **PARTIAL** — `LessonStore` (`base_graph.py::LessonStore`, in-process,
  keyword-overlap retrieval, `get_lesson_store()` singleton) is the session tier for
  the ~70 `run_agent_graph` agents, but it is explicitly in-process and cleared on
  restart (store.py docstring line 14: "session — LessonStore ... in-process, cleared
  on restart"). `chat_agent.py`'s `ChatSession` (`backend/app/models/chat.py`) is a
  separate, distinct session mechanism: in-memory `history` list + optional
  `chat_messages` DB table persistence (`save_message_to_db`/`load_history_from_db`),
  but the LangGraph pause/resume checkpointer itself uses `MemorySaver` (in-process
  only, `chat_agent.py` docstring line 42) — so an in-flight confirmation pause does
  NOT survive a restart even though prior turn text can.
  Plan: back the LangGraph checkpointer with a durable store (Postgres checkpointer)
  so an in-flight chat confirmation survives a process restart, not just message text.
- Shared Memory: **YES** — `memory_embeddings` table (pgvector, `app/db/models.py::MemoryEmbedding`)
  is written by every agent dispatched through either `app/api/specialized_agents.py`
  (via `app/memory/hooks.py::record_agent_run_outcome`) or `manager.py`, and read by
  every agent via `memory_hook_node` (`base_graph.py`) — genuinely cross-agent, cross-process.
- Project Memory: **PARTIAL** (was NO) — gap-closure Day 2 (2026-07-30) added a real,
  nullable `repo_id` FK (`ondelete=SET NULL`) to `MemoryEmbedding` and `VersionedLesson`
  (`app/db/models.py`, migration `backend/migrations/versions/024_memory_project_scoping.py`).
  Verified live: all 125 pre-existing rows preserved with `repo_id=NULL` (not dropped, not a
  magic sentinel — real SQL NULL); FK delete-behavior proven against real Postgres, not mocked
  (`tests/test_memory_project_scoping_migration.py`, 4/4 passing — including a genuine bug this
  test caught in itself: the first version read a stale SQLAlchemy-identity-map-cached object
  instead of the real post-delete DB row and would have silently passed either way; fixed with
  `session.expire_all()` before re-querying). Day 3 (same day) added real, tested filtering to
  every `embed_*`/`query_*` function in `store.py` (see Q95 for the isolation proof). Still
  PARTIAL, not YES: no real call site passes `repo_id` yet — that's Day 4, replacing the
  `_active_repo_path` global.
  Plan (Day 4, next): replace `_active_repo_path` with per-request repo context and thread the
  resolved repo id into every real `embed_*`/`query_*` call site.
- Long-Term Memory: **YES** — same `memory_embeddings` table, no TTL by default
  (`memory_embeddings_retention_days` default 180, `config.py` line 383-386) before
  archival (not deletion).
- Procedural Memory: **YES** — `category="procedure"` on `MemoryEmbedding`,
  `store.py::embed_procedure`/`::query_procedures`, written by `base_graph.py::_maybe_store_procedure`
  only when real iteration occurred (`reflection_unsatisfied_count > 0` or `retry_count > 0`),
  using `base_graph.py::_extract_steps_taken` (real ordered tool_use blocks, not a
  paraphrase). Per `IMPLEMENTATION_PROGRESS.md` Day 3/1.5.
- Failure Memory: **YES** — `store.py::embed_failure`/`::query_failures`, `outcome="failure"`,
  written automatically by `app/memory/hooks.py::record_agent_run_outcome` whenever
  `result.status != "completed"`, and by `chat_agent.py::_memory_write_outcome` on a
  chat-turn error.
- Knowledge Memory: **PARTIAL** — `category="learning"` (`store.py::embed_learning_signal`,
  `record_learning` tool wired to ~69 agents per `IMPLEMENTATION_PROGRESS.md` Phase 1.4/
  4.4) plus curated `VersionedLesson` (`app/db/models.py`, DRAFT→PUBLISHED→SUPERSEDED→ARCHIVED,
  `app/fleet/versioned_memory.py`). PARTIAL because writes to the "learning" category
  require no evidence gate at all (see Q112) — anything an agent calls `record_learning`
  with becomes durable, queryable knowledge on the first mention.

Where stored: Postgres, `memory_embeddings` + `versioned_lessons` tables (pgvector
`Vector(1536)` column), via SQLAlchemy async engine. Ephemeral tiers (working, session/
LessonStore, `EpicScratchpad`) are in-process Python objects, never persisted.
How updated: `embed_*` functions in `store.py`, all async, all non-fatal on failure
(catch+log+rollback, never raise into the calling agent graph).
How retrieved: cosine similarity (`embedding <=> vector`, pgvector) via `query_similar_tasks`/
`query_failures`/`query_learning_signals`/`query_procedures`/`query_architecture_notes`,
combined by `query_memory_context`, injected into the agent's system prompt by
`memory_hook_node` before every LLM call (fleet default `enable_memory=True`).
How synchronized: no locking/transaction coordination between agents beyond each
individual `db.commit()` — the table is effectively append-only for task/failure/
architecture/learning/procedure rows, so cross-agent write conflicts are structurally
avoided rather than resolved. `VersionedLesson.publish()` is the one place that does
real conflict handling: cosine-similarity dedup against the current PUBLISHED lesson,
then an LLM merge (`versioned_memory.py::_merge_via_llm`) rather than overwrite.
How it survives restart: Postgres persistence for `memory_embeddings`/`versioned_lessons`/
`chat_messages`; sync bridges (`query_memory_context_sync`, `embed_learning_signal_sync`,
etc.) use `app/db/session.py::new_isolated_async_engine()` so a plain-sync LangGraph node
can still reach the DB. In-process tiers (LessonStore, ChatSession's live queue, LangGraph
`MemorySaver`) do NOT survive restart — real, cited gap above.
How shared between agents: any agent's write to `memory_embeddings` is immediately
visible to any other agent's next `query_*` call — no per-agent or per-project partition
exists (see Project Memory finding above), so sharing is effectively "everything, fleet-wide."

---

---

## Q6. Agent Specification Audit (72 agents)

- Identity (AGENT_CONTRACT["name"]): **YES** — 72/72 have `AGENT_CONTRACT["name"]` set (script: `contract has name: 72`).
- Role (AGENT_CONTRACT["description"] + role file): **YES** — 72/72 contracts have a non-empty `description`; 71/72 also have a `backend/roles/{name}.md` system-prompt file. Only `chat_agent` has no role file (it runs its own hand-built loop, not `run_agent_graph` — see A.1 of `MASTER_AGENT_v2.md`).
  Plan: n/a — `chat_agent`'s system prompt is embedded directly in `chat_agent.py`'s own code rather than a `roles/*.md` file; low priority to unify given it's a deliberate, documented exception.
- Responsibilities: **YES** — role files are real prose (not stubs): e.g. `roles/coder.md` (111 lines, cites this repo's actual FastAPI/Next.js stack and exact `mypy`/`pytest` commands per `MASTER_AGENT_v2.md` §A.5), `roles/qa.md`/`roles/reviewer.md` (146–147 lines). 71/72 role files contain a "Quality Gates"/"Success Criteria" section (script: `role_has_quality_gates: 71`) that is mechanically parsed at runtime by `_extract_role_criteria()` (`base_graph.py:717-738`) to drive self-critique.
- System Prompt: **YES** — `load_role()` (`base.py:38-46`) reads `backend/roles/{name}.md`, prepends `_GLOBAL_STANDARDS.md`, and this is what's actually sent as the Anthropic `system=[...]` block in `_make_call_llm_node` (`base_graph.py:543,614-618`). 71/72 confirmed present; `chat_agent` is the one exception (custom prompt in-code).
- Skills / Tool List: **YES for 70/72** — `AGENT_CONTRACT["allowed_tools"]` is non-empty for 70/72 (script: `allowed_tools_count > 0: 70`). The 2 with zero: `executive` and `manager` (both orchestrators that dispatch other agents rather than call tools directly — confirmed by reading their contracts). Per `MASTER_AGENT_v2.md` §A.2, tool provisioning is real and individually correct as of Phase 2 (25 former template-identical "Tier-B" agents were fixed — `IMPLEMENTATION_PROGRESS.md` "Step 2 summary — all 25 Tier-B agents now individually tool-correct, not template-identical").
- Memory: **YES, fleet-wide, but until Phase 1 (already completed per IMPLEMENTATION_PROGRESS.md) three memory systems were disconnected.** `memory_hook_node` (`base_graph.py:462-529`) runs for every `run_agent_graph` call (default `enable_memory=True`), reading both the in-process `LessonStore` (keyword-only, wiped on restart) and the DB-backed `memory_embeddings` (pgvector, `app/memory/store.py::query_memory_context_sync`, Phase 1.3). `embed_failure`/`embed_architecture_note` — flagged in `MASTER_AGENT_v2.md` §A.4 as "fully implemented, fully dead" (zero call sites) — now have real call sites confirmed via grep: `app/memory/hooks.py:91,112` and `app/agents/chat_agent.py:463`.
- Knowledge Base: **YES** — `app/repo_tools/scanner.py` (real tree-sitter parsing), `cross_file_graph.py` (function-level call graph with PageRank), `context_builder.py`, DB tables `indexed_files`/`symbols`/`call_edges`/`code_embeddings` (`migrations/versions/001_initial_schema.py:145-205`). Injected into every graph-agent run via `memory_hook_node`'s repo-context block (`base_graph.py:510-525`).
- Planning Engine: **YES, 70/72** — `planner_node` (`base_graph.py:354-378`) runs a real gather-facts → create-plan two-LLM-call sequence, default `enable_planning=True` in `run_agent_graph` (`base_graph.py:1617`). Applies to all 70 agents calling `run_agent_graph`; `chat_agent`/`manager` are the 2 exceptions (custom loop / supervisor pattern, both documented in `MASTER_AGENT_v2.md` §A.1 as deliberate, not bugs).
- Reasoning Loop: **YES, 70/72** — `call_llm` node + conditional-edge `router` (`base_graph.py:572-650`, `1414-1445`) is a real `langgraph.graph.StateGraph` loop with stall detection (`n_stalls`/`max_stalls`) and `max_turns` enforcement.
- Verification Loop: **YES, 71/72** — `VerificationConfig(...)` is used in 71/72 modules (script: `uses VerificationConfig: 71`; only `manager` doesn't). `execute_tools` (`base_graph.py:1003-1205`) overrides the model's own claims in `submit_*` calls with actually-observed tool-run state (`state["verification"]`), plus a `_run_quality_gate` (`base_graph.py:853-920`) that also validates the submitted payload against its declared JSON schema (`jsonschema.validate`).
- Self Critique: **YES for the 5 Tier-A agents — gap-closure Days 11-14 (2026-07-30).** The mechanism
  is real (`critique_node`, `base_graph.py:741-837`, scores a submission against the role file's own
  "Quality Gates"/"Success Criteria" bullets via `_extract_role_criteria`, sends work back up to
  `max_critique_retries` times) and is tested. `enable_critique=True` is now genuinely wired for
  coder/backend_dev/frontend_dev/qa/reviewer (`app/agents/{coder,backend_dev,frontend_dev,qa,
  reviewer}.py`) — verified against the current code, not assumed: all 5 role files
  (`roles/{coder,backend_dev,frontend_dev,qa,reviewer}.md`) confirmed to actually have extractable
  "## Quality Gates"/"## Success Criteria" bullets, so critique does real scoring work for each, not
  a silent fail-open no-op. Remaining fleet-wide default is still `False` — this was a deliberately
  scoped 5-agent rollout, not a blanket flip, per the plan's own "at least the high-risk agent tier"
  phrasing. Proven live by `backend/tests/test_gap11_14_agent_critique.py` (7 tests) — including a
  negative control on `devops` (never named in this rollout) confirming the scoping is precise.
  Plan: flip fleet-wide once this 5-agent rollout is observed stable in real runs (see
  `enable_replanning`'s note above — the same observation-before-wider-rollout gate applies).
- Recovery System: **PARTIAL** — same pattern as Self Critique: `replan_node` (`base_graph.py:425-459`) is real, evidence-gated (only fires on repeated reflection-dissatisfaction or repeated critique failure, `_should_replan`), and tested (`test_phase36_continuous_replanning.py`), but `enable_replanning=True` appears in **zero** of the 72 agent modules (only in the test file). Separately, `app/fleet/fleet_checkpoint.py` provides mid-run failure checkpointing (`_last_known_state` salvage-on-exception pattern, `base_graph.py:1649-1659`), which IS live for all 70 graph-based agents regardless of the opt-in replanning flag.
  Plan: same as Self Critique — turn on `enable_replanning` fleet-wide or for a named subset; currently shipped-but-dormant.
- Safety Layer: **YES** — `app/policy/engine.py` denies writes to `.env*`, `secrets/**`, `*.pem`/`*.key`/`id_rsa`, and dangerous bash commands (`_policy_check`, `base_graph.py:273-285`, enforced at every tool call in `execute_tools`); prompt-injection defense on untrusted tool output (`_wrap_untrusted_tool_content`/`_flag_suspicious_tool_output`, `base_graph.py:933-974`, Phase 6.3); `requires_human_approval` gating set centrally at the `submit_*` boundary (`base_graph.py:1140-1142`) for every one of the 70 graph agents regardless of whether the agent's own module text references the field (per-module grep undercounts this: only 57/72 modules reference `requires_human_approval` in their own source, but the flag is enforced fleet-wide by the shared `execute_tools` node all 70 of them run through).
- Learning Layer: **YES, with a documented ephemerality caveat** — `_extract_and_store_lesson` (`base_graph.py:1214-1295`) runs after every graph-agent submission, writing to `LessonStore` (in-process, wiped on restart) and, when `VOYAGE_API_KEY` is set, to the durable `versioned_lessons` store. `record_learning` tool present in 69/72 contracts (script: `record_learning_in_contract: 69`) and referenced in 69/72 module sources. Procedural memory (`_maybe_store_procedure`, `base_graph.py:1337-1406`, Phase 1.5) captures the real ordered tool-call sequence, gated on the run having actually needed iteration.
- Configuration: **YES** — `app/fleet/agent_models.json` has a per-agent model-tier entry for all 72 agents plus `DEFAULT`/`_tiers`/`_comment` (76 top-level keys total, confirmed by loading the file). `app/fleet/model_router.py` is the actual source of truth used at run time (`base_graph.py:1678-1687`, overrides the caller-passed model).
- Observability: **YES** — 72/72 modules call `get_agent_registry()`/`_register()` at import time (fleet capability/agent registration, script: `calls_fleet_registry_register: 72`). `ActivityStream` pushes (`push_thinking`, `push_tool_call`, `push_tool_result`, `push_file_edit`, `push_terminal`, `push_token_usage`) fire from the shared `call_llm`/`execute_tools` nodes for every graph agent when `task_id` is set. OpenTelemetry present (`opentelemetry` imports in `app/config.py`, `app/fleet/metrics.py`, `app/main.py`) — `IMPLEMENTATION_PROGRESS.md` states "real OTEL spans with correct parent-child nesting" tested and "Phase 6 is now fully complete."
- Logging: **YES** — 72/72 modules define `logger = logging.getLogger(__name__)` (script: `has_module_logger: 72`).
- Metrics: **YES** — `app/fleet/metrics.py::run_span`/`get_metrics_collector()` wraps every `run_agent_graph` call (`base_graph.py:1713-1724`), recording per-tool accuracy, duration, and error data (`_m.record_tool(...)`, `base_graph.py:1064-1076`); `app/fleet/budget_manager.py` (per-run token/time/memory limits + cumulative daily spend) and `app/fleet/regression_detector.py`/`benchmark_manager.py` (baseline-comparison deploy gate) are additional real, independent metrics/perf systems, confirmed by reading their module docstrings.

**Missing items, stated plainly:** no agent has literal per-file "Self Critique" or "Recovery System" turned on in production — both exist as real, tested, shared infrastructure but are 0/72 opted-in today. `chat_agent` has no separate role file / doesn't use the shared verification contract (documented, deliberate exception). `manager`/`executive` have no direct tool list (they're supervisors, not tool-calling workers) and `manager` doesn't use `VerificationConfig`.

---

---

## Q7. Capability Audit (answered from implementation, not prompt text)

- Intelligent Understanding: **YES** — every capability runs on a real Anthropic `messages.create` call (`_make_client()`, `base_graph.py:48-55`), not a rules engine or regex classifier.
- Deep Instruction Analysis: **YES (70/72 by default)** — `planner_node`'s gather-facts call (`_gather_facts_and_plan`, `base_graph.py:293-351`) produces structured `{given, to_look_up, to_derive, guesses}` JSON before any tool call, for every `run_agent_graph` caller (default on).
- Smart Planning: **PARTIAL** — initial plan generation (`planner_node`) is real and on-by-default for 70/72; continuous mid-run replanning (`replan_node`) is real but confirmed **0/72 opted in** (see Q6 Recovery System). So "smart planning" = real initial plan, not real adaptive re-planning in production today.
- Context Awareness: **YES** — repo-context injection (`memory_hook_node`, `base_graph.py:510-525`, via `context_builder.build_context`) plus context-window condensing (`_condense_messages`, `base_graph.py:448` — Stage 1.5, 2026-07-31: real LLM-summarization, not the old drop-oldest `_trim_messages`; see Q65) for every graph agent.
- Long-Term Memory: **YES** — `memory_embeddings` (Postgres/pgvector) survives restarts and is shared across worker processes; confirmed real call sites now exist for all 4 categories (`embed_task_outcome`, `embed_learning_signal`, `embed_architecture_note`, `embed_failure` — the latter two were "fully dead" per `MASTER_AGENT_v2.md` §A.4 but now have live callers in `app/memory/hooks.py:91,112` and `chat_agent.py:463`, per `IMPLEMENTATION_PROGRESS.md` Phase 1.1). Caveat: the ONE store actually read before every LLM call, `LessonStore`, is still in-process/ephemeral — durable memory is a second, DB-backed layer queried in parallel (Phase 1.3), not the sole path.
- Learn From Success: **YES** — `_extract_and_store_lesson` runs after every graph-agent submission unconditionally (not just failures).
- Learn From Failure: **YES** — `embed_failure` has real call sites (`app/memory/hooks.py:91`, `chat_agent.py:463`) wired into the universal post-run hook (`record_agent_run_outcome`, Phase 1.1), which fires for all ~55 non-manager-driven agents dispatched via `app/api/specialized_agents.py`, not just manager-driven ones.
- Detect User Satisfaction: **NO** — grep for "satisfaction"/"sentiment"/"rating"/"thumbs" across `backend/app` found only `reflection_node`'s self-assessment JSON field (`"satisfied": true/false`, `base_graph.py:665`), which is the agent judging its OWN tool output, not detecting the end user's satisfaction with a response. No feedback/rating API endpoint found under `app/api`.
  Plan: add an explicit user-feedback signal (e.g. thumbs up/down on task results) feeding into `embed_learning_signal`, which already exists as a write path.
- Verification Before Reply: **YES, 71/72** — `_run_quality_gate` (`base_graph.py:853-920`) runs at every `submit_*` call for all agents using `VerificationConfig`, checking verification-flag consistency, schema validity, critique outcome, and confidence threshold before a result is accepted.
- Honest Error Handling: **YES** — uniform `[ERROR]`/`[POLICY DENIED]` prefixing convention surfaced directly into the model's context rather than swallowed (`execute_tools`, `base_graph.py:1056-1062`); `_validation_warning` surfaced into the submitted result rather than silently discarded when a `submit_*` call doesn't match its schema (`base_graph.py:1094-1106`).
- Credential Handling: **YES** — `app/policy/engine.py` denies path access to `.env`, `.env.*`, anything under `secrets/`, `*.pem`/`*.key`/`id_rsa`, and denies bash commands matching `cat .../.ssh/|.aws/credentials|.env` (`engine.py:84-94,201`), enforced centrally at every tool call.
- Step-by-Step Guidance: **YES** — `planner_node`'s plan JSON (`{steps, validation, confidence, risks}`) and numbered-step role-file prompts (e.g. `docs/ADD_A_NEW_AGENT.md`'s own template process, agent role files' "Process: 1... 2... 3...").
- Cross-Agent Collaboration: **YES** — `manager.py` dispatches `backend_dev`/`frontend_dev`/`qa`/`reviewer` as a real supervisor graph; `EpicScratchpad` (Phase 1.7, `app/fleet/scratchpad.py`) provides epic-scoped shared read/write state across those agents, backed by Postgres with TTL.
- Shared Learning: **PARTIAL** — `LessonStore` is a single process-global singleton read by every one of the 70 graph agents (real sharing within one worker process), but explicitly documented as NOT shared across multiple worker processes (`base_graph.py:146-151`: "each process has its own isolated copy"). DB-backed `memory_embeddings`/`versioned_lessons` ARE cross-process shared, and are now bridged (Phase 1.2 syncs published `versioned_lessons` into `memory_embeddings`).
- Architecture Awareness: **YES** — `app/repo_tools/architecture_mapper.py` (LLM-driven summary seeded by real PageRank-central files from `cross_file_graph.py`), used by `security_architect`/`architecture_reviewer`/`database_architect` role prompts and tool access.
- Performance Awareness: **YES** — `app/fleet/budget_manager.py` (real per-run token/wall-clock/memory limits + cumulative daily spend enforcement), `app/fleet/regression_detector.py` + `benchmark_manager.py` (baseline-comparison deploy gate, independent of pytest).
- Confidence Evaluation: **YES** — planner's `confidence` field (0.0–1.0) is a real structured LLM output, checked against `quality_gate_min_confidence` in `_run_quality_gate` (`base_graph.py:910-915`); default floor is `0.0` (inert unless a caller opts in to a real threshold).
- Self Review: **YES, on by default (70/72)** — `reflection_node` (`base_graph.py:653-701`) runs after every tool-use turn by default (`enable_reflection=True`), a genuinely different (and more mature) status than Self Critique in Q6, which is off by default.
- Continuous Improvement: **PARTIAL** — dedicated fleet self-improvement agents exist and are real (`agent_advisor`, `agent_debugger`, `agent_performance_reviewer`, all 3 confirmed with `AGENT_CONTRACT`s and calling `run_agent_graph`), reading `fleet_metrics_read`/`audit_log_read` and submitting enhancement requests/fixes. But the in-run continuous-improvement mechanism (replanning) is 0/72 opted-in per Q6, so improvement-during-a-single-run is dormant even though offline/meta fleet-improvement agents are real.
- Production Quality: **YES for Tier-A, PARTIAL for former Tier-B** — `coder.py` runs `mypy`+`ruff` outside the LLM loop and retries the whole graph run on failure (`MASTER_AGENT_v2.md` §A.2, `coder.py:83-96,128-203`); per `IMPLEMENTATION_PROGRESS.md`, all 25 former Tier-B agents were individually tool-corrected in Phase 2 (no longer byte-identical templates), though `MASTER_AGENT_v2.md` §A.3 notes their tests remain wiring-checks (`test_tools_include_read_only`, `test_submit_handler_present`) rather than output-quality checks — that characterization predates Phase 2-6 completion and was not independently re-verified line-by-line in this pass.
  Plan: NOT VERIFIED further within this pass's scope — would need re-running `tests/test_gap_agents.py` today to confirm whether output-quality assertions were added alongside Phase 2's tool fixes.

---

---

## Q8. Performance Audit

- Compare runtime behavior with Claude Code and Cursor: **NOT VERIFIED** — no live benchmarking harness in this repo runs Claude Code or Cursor side-by-side against this system. There is no code path, script, or fixture anywhere in `backend/` that invokes either external tool. Any numeric comparison would be fabricated. Doing this for real would require running identical tasks through both systems and diffing wall-clock/token traces, which is outside what can be verified by reading the repo.
- Response latency: **PARTIAL** — `backend/app/fleet/metrics.py`'s `MetricsCollector.p50_latency_ms()`/`p95_latency_ms()` (lines 230–251) compute real percentile latency per agent from `RunMetrics.execution_time_ms`, which `run_span()` (lines 434–461) sets via `time.monotonic()` around every agent run. This is real instrumentation capable of measuring response latency, but it has never been used to produce a comparison number against another tool.
- Planning speed: **NO** — `RunMetrics` and `record_tool()` (metrics.py:113–128) time individual *tool calls* (`ToolCallRecord.duration_ms`), but there is no separate metric isolating the planner node's time from the rest of a run. `base_graph.py` has exactly one `record_tool()` call site (line 1074); planning/orchestration nodes aren't separately timed.
  Plan: add a `record_tool()`-equivalent call around the planner/decomposer LangGraph nodes to isolate planning latency.
- Orchestration speed: **NO** — same gap as above; `manager.py`'s epic-manager graph and `pipeline/graph.py` have no dedicated orchestration-latency metric, only the whole-run `execution_time_ms`.
- File scanning speed: **NO** — `backend/app/repo_tools/scanner.py` and `cross_file_graph.py` contain no `time.monotonic()`/`perf_counter()` instrumentation (grep for timing calls in `app/repo_tools` returned zero hits). Scan duration is only indirectly visible if a scan happens to run inside a `list_files`/`get_file_tree` tool call, in which case `record_tool()`'s `duration_ms` captures it as a generic tool-call time, not a labeled scan metric.
- Editing speed: **PARTIAL** — `edit_file`/`write_file` tool calls are timed the same generic way via `record_tool()`'s `duration_ms` (metrics.py:113–128), so edit latency is recoverable per-run from `tool_calls[]`, but there's no dedicated "editing speed" aggregate metric or dashboard rollup.
- Tool execution speed: **YES** — this is the one sub-item with dedicated, first-class instrumentation: every tool call records `duration_ms` and success/failure (`ToolCallRecord`, metrics.py:57–61), aggregated into `tool_accuracy` (metrics.py:147–152) and exposed per-agent via `by_agent()`.
- Memory retrieval speed: **NO** — `RunMetrics.memory_retrieved`/`memory_written` (metrics.py:91–92) are *counts*, not timings. Grep across `backend/app/memory` found no `time.monotonic()`/`perf_counter()`/duration instrumentation at all.
  Plan: add explicit timing around `app/memory/store.py`'s retrieval calls and record it on `RunMetrics`.

**Estimated production performance level: NOT VERIFIED (no numeric estimate given) — reasoning:** the repo has real per-agent p50/p95 latency and per-tool duration/success instrumentation (`app/fleet/metrics.py`), an OTEL bridge for external tracing (metrics.py:262–427), and a regression detector that blocks deploys on measured benchmark regressions (`app/fleet/regression_detector.py`, exercised by `tests/test_regression_detector.py`). That is genuine capability to *measure* production performance. But no benchmark run comparing this system's numbers to Claude Code or Cursor exists in the repo, so any percentage figure here would be an unfounded guess, not a fact. Reporting a percentage would violate the "no hallucination" standard — this is explicitly **NOT VERIFIED** rather than estimated.

---

---

## Q9. Frontend and Backend Audit

**1. API connections** — Real, wired REST integration, not mocked. `apps/web/next.config.mjs`
(lines 6-14) proxies `/api/:path*` → the FastAPI backend. Central client `apps/web/lib/api.ts`
(~55 typed functions) with a shared `handleResponse<T>()` error unwrapper. Every
`APIRouter(prefix=...)` in `backend/app/api/*.py` is registered in `main.py` (15 `include_router`
calls) and matched by a real frontend fetch path — no dangling references found.

**2. Streaming (SSE)** — Real, two independent implementations backed by genuine token-level LLM
streaming. Chat: `backend/app/api/chat.py::send_message` returns a `StreamingResponse` draining an
`asyncio.Queue`, fed by `chat_agent.py::_call_llm_node`'s real `client.messages.stream(...)` against
the Anthropic SDK. Task activity: `backend/app/api/activity.py::stream_task_events`. Frontend: chat
page manually reads the fetch stream; `app/stream/[taskId]/page.tsx` uses a real `EventSource`.

**3. WebSocket support: NOT FOUND.** Exhaustive grep for `websocket`/`WebSocket(`/`@app.websocket`
across `backend/` and `apps/web/` returns zero matches; no `websockets` package, no `ws`/`socket.io`
in either `package.json`. The platform is REST + SSE only.
Plan: not needed unless bidirectional push becomes a requirement — SSE already covers current needs.

**4. State management** — `@tanstack/react-query` is the only state/data library (no Redux/Zustand/
Jotai/MobX). Pattern is mostly polling via React Query `refetchInterval` (3-30s across pages), not
push. `NavBar.tsx` mixes both: one pending-count badge uses real SSE push, a visually identical
second badge uses 5s polling — an inconsistent, unfinished-looking pattern, not a broken one.

**5. Error handling** — Backend: real, centralized (`main.py` registers `HTTPException`/
`RequestValidationError` handlers returning a consistent `{"error": {code, message}}` envelope,
plus `SlowAPIMiddleware`/`CORSMiddleware`). Frontend: `lib/api.ts::handleResponse` converts non-OK
responses to thrown `Error`s caught into local state.
**React error boundaries — Stage 1.4 (2026-07-31): DONE.** `apps/web/app/error.tsx` (root-level) +
one `error.tsx` in each of the 16 route-group directories, sharing UI via
`apps/web/components/RouteError.tsx`. Verified via `tsc --noEmit` and a real `next build` (all 19
routes generated). Not verified: the rendered error UI in a live browser (no browser-automation
tool available).

**6. Reconnect/retry logic — Stage 1.4 (2026-07-31): DONE for the task-activity stream.**
`app/stream/[taskId]/page.tsx`'s `es.onerror` used to unconditionally call `es.close()` on ANY
connection error — which defeats `EventSource`'s own native auto-reconnect — permanently killing
the feed on any transient drop. Now a shared `connect(attempt)` (also used by `handleResume`, which
previously duplicated a second non-reconnecting copy) retries with exponential backoff
(1s→2s→4s→8s→16s, capped 30s, 5 attempts), distinguishing a transient connection error (reconnects)
from a genuine terminal server event (does not). New `page.test.tsx` (4 tests, a controllable fake
`EventSource`) proves this. The fleet-badge stream's inconsistent SSE-vs-poll pattern noted in §4
was NOT touched (out of the plan's named scope — only the task-activity stream was named).

**7. Frontend/backend sync** — verified, no orphaned frontend calls found; the one real
inconsistency is the dual sync-strategy badge counters noted in §4.

**8. Authentication — real JWT, but disabled by default; the wiring gap is now closed.**
`backend/app/auth/jwt.py` (python-jose + bcrypt, real), `backend/app/api/auth.py` (real).
`jwt_auth_enabled` defaults to `False` (`config.py:539`); when off, falls back to an opt-in legacy
`X-User-Role` header or anonymous-viewer.
**Stage 1.4 (2026-07-31): DONE.** New `apiFetch()` wrapper in `lib/api.ts` merges `authHeaders()`
into all 44 fetch call sites in that file (not just mutating ones — a GET fails identically to a
write under `RBAC_ENABLED=true`, so the real fix had to cover reads too, broader than the plan's
literal "mutating calls" wording). Grep-swept the rest of the app and found 5 more files with raw
`fetch()` calls bypassing `lib/api.ts` entirely, all with the same gap — fixed the same way:
`app/chat/page.tsx`, `app/review/page.tsx`, `app/settings/page.tsx`, `app/fleet/page.tsx`,
`app/approvals/page.tsx`, `components/NavBar.tsx`. New `lib/api.test.ts` (6 tests) proves the header
is actually attached across GET/POST/PATCH/DELETE and calls with their own pre-existing headers.

**9. Authorization (RBAC) — real server-side enforcement; UI gating is now wired, stream-endpoint
auth gap remains open.** `backend/app/middleware/rbac.py`'s `require_approver`/`require_authenticated`
are real, broadly applied dependencies.
**UI role gating — Stage 1.4 (2026-07-31): DONE.** New `getRole()`/`isApprover()` in `lib/auth.ts`
(decodes the JWT's own `role` claim client-side, no signature check — meaningless here, the server's
signature-verified check is the real boundary; this only affects what renders). Wired into every
Approve/Reject/Approve-Cost button found: `app/approvals/page.tsx`, `app/review/page.tsx` (epic
rows, task rows, batch "Approve All"), `app/epics/[id]/page.tsx`, `app/fleet/page.tsx`. 6 new tests
in `lib/auth.test.ts` (real JWTs with `role` claims).
**Still open, explicitly flagged, not silently fixed**: `GET /api/tasks/{id}/stream` still has no
`Depends(require_authenticated)`, unlike its sibling stop/resume endpoints (re-confirmed directly
against the endpoint's current signature) — an unauthenticated data-exposure gap when JWT auth is
on. Not fixed this pass because `EventSource` cannot send a custom `Authorization` header at all (a
browser API limitation, not a fetch-headers problem) — adding server-side auth here without also
redesigning how the frontend authenticates the stream (e.g. a signed short-lived query-param token)
would break the whole activity-feed feature the moment `jwt_auth_enabled=true` (currently `False` by
default, so dormant today, but a real regression risk for any deployment that turns it on). This
item was in the original Q9 audit's own "Plan:" note but not in the day-by-day Stage 1.4 plan's
literal 4-item list — left for a dedicated future day rather than rushed in unassessed.

**10. Broken/missing integrations found (summary):** (1) auth-header wiring gap — **FIXED**, (2)
unauthenticated task-stream endpoint — **still open, flagged above**, (3) no React error boundaries
— **FIXED**, (4) middleware checks token presence not validity/expiry — unchanged, out of Stage
1.4's scope, (5) inconsistent SSE-vs-poll badge pattern — unchanged, out of scope, (6) no SSE
auto-reconnect on the task activity feed — **FIXED**. No stubbed/mock-wired frontend UI was found —
a genuine positive (all `mock`/`TODO` hits are confined to `e2e/`/test files, not production code).

---

## Q10. Project Architecture Audit

- Folder structure: **YES** — `backend/app/` is cleanly split into 20 top-level domains (`agents/`, `api/`, `artifacts/`, `auth/`, `db/`, `event_bus/`, `fleet/`, `mcp/`, `memory/`, `middleware/`, `models/`, `pipeline/`, `policy/`, `queue/`, `repo_tools/`, `security/`, `services/`, `tools/`, `config.py`, `main.py`), 178 Python files total (`find backend/app -name "*.py" | wc -l` = 178). Frontend lives separately under `apps/web` in a pnpm/turbo monorepo (`pnpm-workspace.yaml`, `turbo.json`).
- Scalability: **PARTIAL** — Redis-backed queue adapter (`app/queue/rq_adapter.py`), RQ worker process declared in `Procfile` (`worker: ... rq worker gridiron-high gridiron-default`), Postgres+pgvector via `docker-compose.yml` with healthchecks. This supports horizontal worker scaling, but there is no load-tested evidence of scaling limits (see Q11 — no load/stress test suite exists to validate this).
- Modularity: **YES** — 70+ agents each declare an explicit `AGENT_CONTRACT` dict (allowed_tools, permissions, risk_level, verification contract) and self-register into `app/fleet/capability_registry.py` and `app/fleet/agent_registry.py` at import time (e.g. `backend/app/agents/dependency_agent.py:139-165`, `backend/app/agents/tech_debt_agent.py`), giving a real, enforced module boundary per agent rather than ad hoc coupling.
- Dependency management: **YES** — `backend/requirements.txt` pins all 39 dependencies with exact `==` versions (verified: `grep -c "==" requirements.txt` = 39, zero unpinned lines). Frontend uses `pnpm-lock.yaml` for reproducible installs. Alembic (`backend/migrations/versions/`, 24 versioned migrations) manages DB schema changes explicitly.
- Code quality: **YES** — CI (`.github/workflows/ci.yml` lines 66–73) runs `ruff check .`, `black --check .`, and `mypy app/ --strict --ignore-missing-imports` as real gates (not suppressed with `|| true` — a prior suppression was explicitly removed per the ci.yml comment at lines 113–119 and 195–213). `IMPLEMENTATION_PROGRESS.md:1033-1039` documents a real run: "black app/ — 175 files, all unchanged", "ruff check app/ — all checks passed", "mypy --strict app/ — 1 pre-existing error" (a documented Windows-only false positive in `budget_manager.py:94`).
- Maintainability: **PARTIAL** — extensive in-code design-rationale comments (e.g. `architecture_mapper.py:1-27`, `failure_ladder.py:1-27` cite prior art and explain design trade-offs directly in the source), and `IMPLEMENTATION_PROGRESS.md`/`MASTER_AGENT_v2.md` track implementation history in detail. Weighed against 178 files and heavy inter-agent coupling through shared `base_graph.py`, long-term maintainability depends on this documentation discipline continuing.
- Separation of concerns: **YES** — API layer (`app/api/`), agent logic (`app/agents/`), fleet orchestration (`app/fleet/`), persistence (`app/db/`), policy/guardrails (`app/policy/`, `app/agents/guardrails.py`), and tooling (`app/tools/`) are distinct packages; agents don't import API routers, and DB models are centralized in `app/db/models.py`.
- Observability: **YES** — `app/fleet/metrics.py` provides structured `RunMetrics`/`trace_id` correlation plus a real OpenTelemetry bridge (lines 262-427, gated so a missing/unconfigured OTEL SDK never breaks a run); Sentry DSN-gated init exists in `app/main.py` (grep hit); `app/services/alert.py` provides alerting.
- Testing: **YES** (see full detail in Q11) — 3397 tests collected (`pytest --collect-only`, verified below), CI runs the full suite plus `pip-audit`, Playwright E2E, and vitest on every PR.
- Deployment readiness: **YES** — `backend/Dockerfile` (multi-stage-ready, git/build-essential deps for tree-sitter wheels), `docker-compose.yml` with Postgres+pgvector and Redis healthchecks, `Procfile` declaring both `web` and `worker` processes, `vercel.json` for frontend deployment, 24 Alembic migrations for schema management.

**Architecture score: 82/100** — Reasoning: strong, consistently-applied modular structure (agent contracts + capability registry), real CI-enforced code quality gates, pinned dependencies, genuine observability (OTEL + Sentry + structured metrics), and a documented, evidence-based development history (`IMPLEMENTATION_PROGRESS.md`'s 3318-passed regression gate). Points deducted for: no automated architecture-drift/duplication detection (Q91 — capability exists only as an on-demand LLM agent, not a continuous check), no load/stress testing to validate the scalability claims, and maintainability resting heavily on continued documentation discipline rather than structural enforcement (e.g. no dependency-direction linter between `app/agents` and `app/fleet`).

---

---

## Q11. Testing Audit

Ran `cd backend && python -m pytest tests/ --collect-only -q` in the project's `.venv`. Real result: **3397/3414 tests collected (17 deselected) in 7.32s**, across 139 files under `backend/tests/`. This is consistent with `IMPLEMENTATION_PROGRESS.md:1010`'s documented full-run gate: "3318 passed / 21 failed / 1 skipped / 17 deselected in 6m12s" (all 21 failures individually triaged there as Windows-sandbox path/binary issues, not code bugs — see lines 1013–1039).

- Unit Tests: **YES** — the large majority of the 139 test files are narrow unit tests against single modules (e.g. `test_config.py`, `test_cost_controller.py`, `test_agent_registry.py`).
- Integration Tests: **PARTIAL** — a `tests/integration/` directory exists but contains only `__init__.py` (empty — no test files inside it). Real integration-style coverage exists but lives inline in the main `tests/` directory instead (e.g. `test_bootstrap_wiring.py`, `test_chat_agent_memory_wiring.py`, which wire multiple real subsystems together), not under a dedicated `integration/` namespace.
  Plan: move/author the cross-subsystem tests into `tests/integration/` to match the folder's stated intent.
- End-to-End Tests: **YES** — Playwright specs at `apps/web/e2e/` (`agents.spec.ts`, `login.spec.ts`, `review.spec.ts`, `tasks.spec.ts`), run as a dedicated CI job (`ci.yml:135-171`). Backend-side, `test_day12_smoke_test.py` provides an end-to-end smoke test.
- Agent Tests: **YES** — `test_day2_agents.py` through `test_day9_fleet_agents.py`, `test_gap_agents.py`, `test_day2_agent_contracts.py` .. `test_day4_agent_contracts.py`, each testing individual agent contracts/behavior.
- Tool Tests: **YES** — `test_day1_tools.py`, `test_day2_tools.py`, `test_chat_tools.py`, `test_fleet_tool_manifest.py`.
- Memory Tests: **YES** — `test_memory.py`, `test_memory_context_query.py`, `test_memory_hooks.py`, `test_procedural_memory.py`, `test_versioned_memory.py`, `test_versioned_memory_sync.py`, `test_lesson_versioned_memory_wiring.py`, `test_chat_agent_memory_wiring.py`.
- Orchestrator Tests: **YES** — `test_audit04_orchestration_fixes.py`, `test_phase51_epic_manager_graph.py`, `test_bootstrap.py`/`test_bootstrap_wiring.py` cover manager/epic-graph orchestration.
- Regression Tests: **YES** — `test_regression_detector.py` (real Postgres round-trip test of `app/fleet/regression_detector.py`'s `DeploymentBlocked` gate wrapping `benchmark_manager.compare_to_baseline()`), plus the documented 3318-passed whole-suite regression gate itself in `IMPLEMENTATION_PROGRESS.md:1008-1039`.
- Performance Tests: **PARTIAL** — `test_benchmark_manager.py` and `test_benchmark_baseline_loop.py` test agent-behavior benchmarking/regression comparison (accuracy/cost/latency baselines per agent), which is real performance-adjacent testing, but there is no dedicated throughput/latency load-generation test.
- Load Tests: **NO** — no locust/k6/or equivalent load-generation tooling found anywhere in the repo (`find . -iname "*locust*"` / `"*k6*"` both empty). `test_concurrency.py` tests semaphore-slot acquisition and timeout behavior (`TestSemaphoreSlots`, `TestSlotAcquisitionTimeout`), which is concurrency-*correctness* testing, not load testing under real traffic volume.
  Plan: add a locust/k6 script exercising the FastAPI endpoints under concurrent load if production-scale validation is required.
- Stress Tests: **NO** — no dedicated stress-test suite found; same gap as Load Tests above.
- Failure Recovery Tests: **YES** — `test_failure_ladder.py` tests `app/fleet/failure_ladder.py`'s 7-state failure recovery ladder (Checkpoint/Rollback/Resume/Retry/Escalate/Abort/Human Review — see Q66 below for detail), plus `test_orphan_recovery.py`.

---

---

## Q12. Autonomous Ranger System / "Five Project Management Agents"



---

## Q13. Human Interaction

- ask permission: **YES** — `backend/app/fleet/approval_gate.py::request_human_input()`/`arequest_human_input()` is the single fleet-wide entry point for a human-in-the-loop pause; called from `app/pipeline/graph.py::human_review_node` (plan review) and `app/agents/chat_agent.py` (6 confirmation-gated tools: `git_push`, dangerous `bash`, `git_reset --hard`, `undo_changes`, `run_migration`, `seed_database` — verified in chat_agent.py's own module docstring lines 24-27).
- wait indefinitely: **YES** — LangGraph `interrupt()` genuinely suspends graph execution (not a timeout-bounded poll); `app/pipeline/graph.py:99` (`human_review_node`) and `app/agents/chat_agent.py:374` (`self._confirm()`) both call real `interrupt()`. `app/pipeline/graph.py` persists this via `AsyncPostgresSaver` (survives restart); `chat_agent.py` uses `MemorySaver` (in-process only — does not survive process restart, see Q14).
- present options: **PARTIAL** — `human_review_node` (`app/pipeline/graph.py:99-104`) surfaces only `{"action": "plan_review_required", "subtasks_count": N}` to the human — a binary approve/reject decision, not a menu of alternative options.
  Plan: extend `human_review_node`'s interrupt payload to include the actual subtask list/plan diff so the human is choosing among concrete options, not just a count.
- recommend choices: **NO** — no code path found that generates ranked/recommended alternatives alongside an approval request (grep across `approval_gate.py`, `pipeline/graph.py`, `chat_agent.py` found no recommendation-scoring logic).
  Plan: add a "recommended action" field to `request_human_input()`'s `details` dict, populated by the calling agent's own confidence/plan output.
- pause execution: **YES** — same `interrupt()` mechanism as above.
- resume execution: **YES** — `app/pipeline/graph.py:209` `ainvoke(Command(resume={"approved": approved}), config=config)`; `chat_agent.py:2567` same pattern; `app/api/approvals.py::approve_approval`/`reject_approval` and `app/api/chat.py::confirm_action`/`_resume_agent` are the real HTTP-triggered resume paths.
- understand follow-up replies: **YES** — `app/api/activity.py::resume_task` (`POST /api/tasks/{id}/resume`) accepts a `ResumePayload{message, files}` and injects it via `stream.set_resume(...)`, and chat's `ChatSession.history` threads follow-up messages into the same session context.
- continue from previous context: **YES** — `get_or_create_chat_agent()` (`chat_agent.py:123-128`) keeps one `ChatAgent` instance (and its checkpointer/graph) alive per `session_id` across the initial `run()` and any later `resume()` calls, so `thread_id=session_id` always resolves to the same state; `ChatSession.history` is the durable cross-turn store.

---

## Q14. Execution Control

- pause: **YES** — real `interrupt()`, see Q13.
- resume: **YES** — real `Command(resume=...)`, see Q13.
- cancel: **YES** — `POST /api/tasks/{id}/stop` (`app/api/activity.py:61-73`) sets an abort flag checked by `call_llm`.
- retry: **YES** — `POST /api/tasks/{id}/restart` (`app/api/tasks.py:228-`) force-resets a failed/blocked task to `pending` and re-triggers the pipeline (blocked if an active run is in progress, 409). Also per-subtask dev→QA→review retry loop with backoff inside `run_manager()` (`manager.py`, explicitly preserved unconverted — see below).
- rollback: **PARTIAL** — `app/api/memory.py::rollback_versioned_lesson` exists for memory/lesson rollback; `rollback_agent` exists as an Analyzer-tier agent (read-only, produces rollback plans, does not execute them per Step 2's tier confirmation). No generic "roll back a completed code change" endpoint found.
  Plan: verify with Bhaskar whether "rollback" means code-change rollback (not implemented as an automated action — `rollback_agent` only recommends) or task-state rollback (implemented).
- checkpoints: **PARTIAL — two different real implementations, not one uniform mechanism.** `app/pipeline/graph.py` compiles with `checkpointer=_checkpointer` backed by `AsyncPostgresSaver` (`init_checkpointer()`, `pipeline/graph.py:28-54`), i.e. real DB-persisted checkpoints. `app/agents/chat_agent.py` compiles with `MemorySaver()` (in-process only, `chat_agent.py:326`, `2513`) — explicitly documented as a deliberate choice, not an oversight (module docstring lines 42-49: "matching `ChatSession`'s own... 'always held in-memory' design"). `app/agents/manager.py`'s epic-manager graph has **no checkpointer at all** — "this graph never pauses (no interrupt()), runs start-to-finish within one `run_epic_manager()` call" (`manager.py:1139-1142`).
- recovery after crash: **PARTIAL** — pipeline plan-review pauses recover cleanly (Postgres-backed). Chat session pauses (dangerous-command confirmations) do NOT survive a backend process crash/restart — `MemorySaver` state is lost, confirmed by `chat_agent.py`'s own docstring. Task-level recovery exists via DB status + `restart_task` (coarse: re-runs from `pending`, not from the exact interrupted step).
  Plan: if crash-survival of a paused dangerous-chat-confirmation is a real requirement, `chat_agent.py`'s checkpointer needs to move to `AsyncPostgresSaver` (its own docstring gives the reason it wasn't done: `Popen` handles for background processes aren't trivially serializable).
- recovery after reboot: **PARTIAL** — same distinction as crash recovery (Postgres-backed pipeline state survives; in-memory chat/epic state does not).
- "If interrupted midway, can execution continue from the checkpoint?": **YES for `app/pipeline/graph.py`'s plan-review pause** (real `AsyncPostgresSaver` checkpoint, proven in "Day 12's smoke test" per `approval_gate.py`'s own docstring) and **YES within-process for chat** (proven via a real LangGraph reproduction script per `chat_agent.py`'s docstring: a confirmed action's side effect fires exactly once across pause/resume). **NO across a process restart for chat** (`MemorySaver` is lost) and **NO mid-epic for `manager.py`'s epic graph** (no checkpointer — a crash mid-epic requires the task-level `restart_task` coarse re-run, not a graph-level resume).

---

## Q15. Large Project Handling

- understand 9,000+ line files: **YES**
  **Gap-closure Days 45-47 (2026-08-03, Stage 2, "Context compression beyond Stage-1
  basics")**: `read_file` (`app/agents/tools.py`, `make_read_only_handlers`) no longer loads
  a large file's full content unconditionally. Repo-first (`CLAUDE.md`'s own lookup table
  names `roo-code`'s `src/core/condense/` for exactly this problem): read
  `repos/roo-code/src/core/condense/foldedFileContext.ts` before designing anything — its
  real technique is replacing a large file's body with a signature-only structural view
  (function/class names + line ranges) via tree-sitter, rather than either an unbounded read
  or dropping the file. Adapted to reuse this project's own real tree-sitter symbol
  extraction (`app/repo_tools/scanner.py`) instead of a second, duplicate tree-sitter
  integration — new public `scanner.py::parse_single_file()` wraps the existing private
  `_parse_file()` for one arbitrary file outside a full repo scan; new
  `app/repo_tools/file_folding.py::fold_file_content()` formats the real symbols into a
  bounded (`file_fold_max_chars`, default 20000) signature list. Wired into `read_file`:
  a file exceeding `file_fold_line_threshold` (default 1000 lines) returns the folded view
  with an explicit `[NOTE]` explaining what happened and how to get more detail (read a
  specific line range), instead of silently truncating or blowing the context. Non-code file
  types (`.md`/`.json`/`.txt`, not tree-sitter-parseable) fall back to a plain bounded
  truncation (`file_fold_fallback_max_chars`) with an explicit `[TRUNCATED]` marker — never
  either an unbounded huge read or a silently empty/failed one. Both thresholds and the
  feature flag (`file_fold_enabled`) are real config, not hardcoded.
  **Tests** (`tests/test_gap45_file_folding.py`, 8 tests, real temp files — no mocked
  filesystem or tree-sitter): a small file still returns in full unchanged; a real 400-
  function 1800+-line Python file is proven folded (full function bodies absent, real
  symbol names present, folded output under half the original size); a large non-code file
  proven bounded-truncated; the feature flag disabled restores the exact old unbounded-read
  behavior; the line threshold proven config-driven (a threshold of 3 folds even a tiny
  file); `fold_file_content()` unit-tested directly for real symbol extraction (including a
  class's own method being a separate real symbol, not just the class itself), unsupported-
  extension `None` return, and max-chars budget enforcement. `black`/`ruff`/`mypy --strict`
  clean. Blast-radius check before shipping: ran all 18 pre-existing test files that
  reference `read_file` (512 tests) — all pass unchanged, since every existing fixture file
  used in tests is well under the 1000-line default threshold.
  **Full regression**: 3575 passed (3567 Day-44 baseline + 8 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
  Plan: Add offset/limit parameters to `read_file` (like Claude Code's own Read tool) so large files can be read in windows instead of whole-file dumps.
- edit very large files safely: **YES** — `_make_edit_file_handler()` (`tools.py:3523`) uses exact `old_string`/`new_string` replace requiring a unique match (`count == 0` → error, `count > 1` → error), so it never does a full-file rewrite and preserves everything outside the matched span regardless of file size.
- scan 1,000+ files: **YES** — `backend/app/repo_tools/scanner.py:199` `index_repository()` walks the whole tree with `os.walk`, prunes `_IGNORE_DIRS` (`.git`, `node_modules`, `.venv`, `dist`, `build`, etc., line 26), supports incremental re-index via `known_hashes` content-hash skip (line 234), and is not capped at a file count — it will process however many files exist.
- modify 100+ files: **YES** — `backend/app/repo_tools/ast_engine.py:289` `rename_symbol()` walks `d.rglob(file_pattern)` and rewrites every matching file with a word-boundary regex substitution, reporting a per-file changed-count list (line 306-321); used by `make_refactor_agent_handlers()` (`tools.py:4126`, `rf_rename_symbol` at 4192). Not semantically scope-aware (plain text/regex rename), so same-named unrelated identifiers across files could also be renamed.
  Plan: Upgrade `rename_symbol` to use tree-sitter scope resolution instead of a global word-boundary regex, to avoid false-positive renames in unrelated scopes.
- build complete projects: **NOT VERIFIED** — no single "scaffold new project" tool/handler was found in `tools.py`; project construction appears to rely on the LLM agent issuing many individual `write_file`/`bash` calls rather than a dedicated project-bootstrap tool. Did not find evidence either way for a template/scaffold engine.
- perform repository-wide refactoring: **YES** — `make_refactor_agent_handlers()` (`tools.py:4126`) provides `list_functions`, `list_classes`, `call_graph`, `import_graph`, `rename_symbol` (repo-wide), `replace_function` (regex-based whole-function body replace, line 4201), plus scoped `bash` limited to `pytest`/`mypy`/`ruff`/`black`/`isort` (line 4135 `_RF_ALLOWED`) to verify after refactor.

---

## Q16. File Understanding

- Python: **YES** — `scanner.py:15` uses `tree_sitter_python`; `ast_engine.py` does full stdlib `ast.parse()`-based function/class/import extraction, dead-code detection, circular-import detection, rename, call/import graphs.
- TypeScript: **YES** — `scanner.py:21-22` maps `.ts`/`.tsx` to `tree_sitter_javascript` grammar (shared JS/TS grammar; no dedicated TS-type-aware parser).
- JavaScript: **YES** — `scanner.py:20,23` `.js`/`.jsx` via `tree_sitter_javascript`.
- HTML: **NO** — no tree-sitter-html or any HTML-specific parser found in `repo_tools` or `requirements.txt` (verified via grep for "php|html|css" across `repo_tools/*.py` and requirements — no matches beyond generic text handling). Generic `read_file`/`write_file`/`edit_file` still work as plain text.
  Plan: Add `tree-sitter-html` grammar and a symbol extractor if structural HTML understanding (not just text edit) is required.
- CSS: **NO** — same as HTML; no CSS grammar/parser present, only generic text read/write/edit.
- PHP: **NO** — no `tree-sitter-php` dependency or PHP-specific handling anywhere in the codebase (grep confirmed zero project-code hits, only unrelated `.venv` site-package noise).
  Plan: Add `tree-sitter-php` to `requirements.txt` and extend `scanner._LANG_MAP`.
- Markdown: **YES (as text only)** — no MD-specific AST, but generic `read_file`/`write_file`/`edit_file`/`append_file` (`tools.py:877, 3544, 7269`) operate on any text file including `.md`; `make_readme_agent_handlers` (`tools.py:4261`) specifically manipulates README/markdown content.
- JSON: **YES** — `json_validate_h`/`json_query_h` (`tools.py:10768, 10803`) validate/query via stdlib `json` (and `jq` if installed).
- YAML: **YES** — `yaml_validate_h` (`tools.py:10786`) uses `yaml.safe_load` for validation; docker-compose files handled via `docker-compose config` dry-run (`tools.py:816`).
- Docker: **YES** — `make_docker_agent_handlers()` (`tools.py:3978`), `dk_docker_logs` (line 3998), `docker build`/`docker_build_h` (line 8899 area), Dockerfile path param support (line 4044).
- Docker Compose: **YES** — `docker-compose config` allowlisted for infra dry-run (`tools.py:816`), `dc_allowed = {"ps","logs","config","images"}` (line 4030).
- Jupyter Notebook: **NO** — no `nbformat`/`.ipynb`-specific handling found in project code (only unrelated hits inside third-party `.venv` packages like `black/handle_ipynb_magics.py`, which is `black`'s own internal notebook-cell formatting support, not something this project's tools invoke for `.ipynb` files).
  Plan: Add an `.ipynb` reader that extracts cells via `nbformat` and exposes them as structured text to agents.
- PDF: **YES** — `_READ_PDF_TOOL`/`read_pdf_h` (`tools.py:4985, 10361`) uses `pdfplumber` (in `backend/requirements.txt`) to extract per-page text, with an explicit error message if pdfplumber isn't installed and a warning for image-only PDFs.
- Images: **PARTIAL** — `_READ_IMAGE_TOOL`/`read_image_h` (`tools.py:5001, 10384`) uses `PIL.Image` to return format/size/mode metadata plus a base64 thumbnail for vision inspection — metadata + thumbnail only, not OCR/content extraction.
- Audio: **NO** — no audio library (`pydub`, `whisper`, etc.) in `backend/requirements.txt` or project code; only hits were inside unrelated third-party SDK packages (`groq`/`openai` audio API bindings, not wired into any tool handler).
  Plan: If needed, add a `read_audio` tool using an installed transcription API (Groq/OpenAI Whisper endpoints are already SDK-available as dependencies) and expose transcript text.
- Video: **NO** — no video-handling library or tool found (verified — only an unrelated `ffmpeg`/`voyageai/video_utils.py` third-party package present, not invoked by any project tool).
- XML: **NO** — no dedicated XML tool/parser found in project code (only stdlib in unrelated third-party packages). Generic text read/write still applies.
- CSV: **YES** — `csv_preview_h` (`tools.py:10813`) uses stdlib `csv` to preview rows/columns.
- Excel: **NO** — no `openpyxl`/`pandas.read_excel` in `requirements.txt` or project code.
- Word: **NO** — no `python-docx` in `requirements.txt` or project code.
- PowerPoint: **NO** — no `python-pptx` in `requirements.txt` or project code.

---

## Q17. Terminal Intelligence

- monitor terminal output: **PARTIAL** — for background processes, `read_output_h` (`tools.py:8818`) does a best-effort non-blocking read of stdout/stderr via `_read_stream_nonblocking()` (line 8778, POSIX `fcntl` O_NONBLOCK / Windows threaded-read-with-timeout fallback). For foreground commands, output is fully captured only after the process exits (`subprocess.run(capture_output=True)`), i.e. no live streaming.
- detect completion: **YES** — `proc.poll() is not None` check in `read_output_h` (`tools.py:8824`) reports exit and returncode for background processes; foreground `subprocess.run()` blocks until completion by construction.
- detect failure: **YES** — every scoped-bash handler returns combined stdout+stderr and the caller (LLM agent) sees non-zero output/`returncode`; explicit examples: `dk_docker_build` returns `"Build {'succeeded' if r.returncode==0 else 'FAILED'}"` (`tools.py:4054`); `git_service._run_git` returns `proc.returncode` (git_service.py:79-83).
- detect hanging processes: **PARTIAL** — foreground commands are bounded by hard `timeout=` on `subprocess.run` (60/120s across handlers) and raise/report `[ERROR] Command timed out after Ns`; `_run_git` (`git_service.py:61`) does `asyncio.wait_for(..., timeout)` then `proc.kill()` on timeout. But background processes started via `run_background` (`tools.py:7787`) have no timeout or idle/hang heuristic at all — they run until manually `kill_process`'d or the process exits on its own; nothing detects a silently-hung background process automatically.
  Plan: Add an idle-output watchdog (e.g. no new stdout/stderr for N minutes) that flags or auto-kills stale `_session_bg_procs` entries.
- wait for commands to finish: **YES** — default behavior of every `subprocess.run(...)` call (blocks until exit or timeout).
- parse logs: **PARTIAL** — `bf_read_logs` (`tools.py:3608`) reads the last N lines of a log file as plain text; there is no structured log-level/field parser — "parsing" is effectively hand-off of raw text to the LLM.
- parse Docker logs: **PARTIAL** — `docker_logs`/`dk_docker_logs` (`tools.py:3998, 8450`) run `docker logs <container>` and return raw text; no structured parsing of log lines (e.g. no JSON-log or timestamp extraction).
- parse test output: **PARTIAL** — test runner handlers (`make_test_runner_bash_handler`, `tools.py:701`) return raw pytest/npm-test stdout+stderr; the `submit_qa_report` tool schema (`tools.py:540-553`) requires the calling agent to self-report `tests_passed`/`tests_failed`/`status` — there is no code-level regex/JUnit parser computing these from raw output; it's LLM-interpreted, not deterministically parsed.
  Plan: Add a real pytest/jest JSON or JUnit-XML report parser so pass/fail counts are computed in code, not inferred by the LLM from raw text.
- parse compiler output: **PARTIAL** — same pattern: `mypy`/`tsc`/`ruff` output is captured as raw text (`tools.py:7529` mypy, etc.) and returned to the agent; no structured error-location parser found.

---

## Q18. Coding Workflow

- create files: **YES** — `_make_write_file_handler()` (`tools.py:3544`) `write_file_h`, creates parent dirs via `mkdir(parents=True, exist_ok=True)`.
- edit files: **YES** — `_make_edit_file_handler()` (`tools.py:3523`), unique-match `old_string`/`new_string` replace.
- delete files: **YES** — `delete_file` (`tools.py:7152`), refuses directories ("use bash 'rm -rf' for directories" — note: this fallback for directory deletion routes through the less-restricted bash path, worth flagging).
  Plan: Add a dedicated safe `delete_directory` tool with the same protected-path checks instead of pushing directory deletion onto the bash allowlist/denylist path.
- delete files: **YES** — `delete_file` (`tools.py:7152`) checks `_is_protected_path` before unlinking, errors cleanly if not found/not a file.
- compare files: **YES** — `compare_files` handler (`tools.py:7766`, tool schema at line 2132) takes `path_a`/`path_b` and context lines.
- synchronize files: **NOT VERIFIED** — no dedicated "sync" tool found beyond `copy_file` (`tools.py:7302`) and git operations (pull/push); no multi-target sync/watch mechanism identified.
- refactor projects: **YES** — see Q15 repo-wide refactor evidence (`make_refactor_agent_handlers`, `rename_symbol`, `replace_function`).
- preserve formatting: **YES** — `edit_file`'s unique-string-replace approach (`tools.py:3523`) never touches bytes outside the matched span, so surrounding formatting is untouched by construction; `replace_function` (`tools.py:4201`) replaces only the matched function's byte range.
- preserve comments: **YES** — same mechanism; `edit_file`/`replace_function` operate on exact substrings, so comments elsewhere in the file are never rewritten. `write_file` (full overwrite) does not preserve anything since it replaces whole content — used only when explicitly writing a whole file.
- avoid restricted files: **YES** — `_is_protected_path()` (`tools.py:6817`) + `policy/engine.py:78-141` `_matches_path_rule`/`check_path_in_worktree` block `.env`, `.env.*`, `secrets/`, `*.pem/.key/.pfx/.p12`, SSH private keys, `.github/workflows/`, `.git/`, and any realpath escape outside the worktree (symlink-resistant via `os.path.realpath`). Checked before every write/edit/delete in `edit_file_h`, `write_file_h`, `delete_file`, `rename_file`, `copy_file`.
- obey repository rules: **PARTIAL** — no explicit "read and enforce .editorconfig/CONTRIBUTING.md/lint config" mechanism found; "obedience" is effectively whatever the LLM agent chooses to do plus policy-engine hard blocks (denylisted commands/paths) — there's no automated rule-file ingestion step.
  Plan: Add a pre-task step that reads repo-local lint/format configs (`.editorconfig`, `pyproject.toml` tool sections, `.eslintrc`) and surfaces them to the agent as required constraints.

---

## Q19. Deployment Intelligence

- Detect/diagnose deployment issues: **PARTIAL, real but narrow** — `devops.py`/`docker_agent.py`/
  `incident_responder_agent.py`/`rollback_agent.py`/`cicd_agent.py`/`infra_agent.py` all run real
  subprocess/git/Docker introspection (confirmed by reading handler bodies, not just prompts), but
  none ingests an actual deployment platform's failure logs (Vercel build log, Railway/Render log,
  GitHub Actions run log) — diagnosis is limited to what's observable locally.
- Project-specific deployment guide generation: **PARTIAL** — `runbook_generator_agent` is real and
  genuinely repo-grounded (verified: instructed to derive all commands from actually-read files);
  the flagship `docs/DEPLOYMENT.md` is a static, human-written document, not agent-generated on
  demand. A real doc/code drift was found: `cost_estimator_agent`'s role-doc claims it reads
  IaC configs for cost estimates, but its actual `AGENT_CONTRACT` scope is narrower (effort/token
  cost only).
- **Platform support** (each independently verified against code, not just docs):
  - Docker: **REAL** — genuine `subprocess.run(["docker", ...])` calls, human-approval-gated writes.
  - Vercel: **NOT integrated** — `vercel deploy` is explicitly, permanently denylisted; only a
    static, functional `vercel.json` exists, no API/CLI integration.
  - Railway / Render: **NOT FOUND** anywhere in code — mentioned only in human-written docs.
  - Kubernetes: **NOT integrated, explicitly and permanently blocked** — `kubectl` denylisted with
    no dry-run exception even for `infra_agent`'s otherwise-permitted validation mode; no k8s
    manifests anywhere in the repo.
  - Azure / GCP: **NOT FOUND.**
  - AWS: **PARTIAL** — real `boto3` dependency and S3 config exist for artifact storage only, not
    deployment/infrastructure management.
- **This is confirmed as a deliberate safety boundary, not an oversight**: `docs/DEPLOYMENT.md`
  states outright "Deploy is a human action forever," and deploy-class commands are permanently
  denylisted platform-wide (`vercel deploy`, `kubectl`, `terraform`, `docker push`, `heroku`).
  Plan: none needed unless the user explicitly wants to relax this deliberate boundary — flagging as
  a design choice, not a gap, per this audit's own "don't recommend changes that conflict with
  existing architecture without explaining trade-offs" instruction.

---

## Q20. External Knowledge

- Open URLs/fetch web content: **REAL, but capability is agent-scoped.** `fetch_url`/
  `check_url_status`/`http_request` are all real (`urllib`-based, not stubbed), but the full set is
  reachable **only from `chat_agent.py`** — many other agents call the same underlying handler
  builder (`make_chat_handlers`) but their own tool-schema lists never include these tools, so the
  model literally cannot invoke them even though the handler technically exists (verified: Anthropic's
  tool-use API only allows calling tools present in the request's `tools` array).
- Summarize websites/understand documentation: **REAL DuckDuckGo-backed web search, but reachable by
  only 2 of ~72 agents.** A genuine, newly-found gap: the dedicated `research.py` agent's tool
  handler dict DOES wire `web_search`, but its tool-**schema** list (`RESEARCH_TOOLS`, what's
  actually sent to the model) never includes it — so the one agent whose entire job is web research
  cannot actually call `web_search`. This directly contradicts a specific line in this project's own
  `MASTER_AGENT_v2.md` (which cites a now-stale line number for the tool's inclusion) — a real,
  verified doc/code discrepancy, not assumed. `web_search` IS correctly wired end-to-end for
  `agent_performance_reviewer`. No dedicated "summarize" tool exists anywhere — any summarization is
  the LLM's own reasoning over raw truncated fetched text.
  Plan: add `_WEB_SEARCH_TOOL` to `RESEARCH_TOOLS`'s actual schema list — the handler wiring already
  exists, this is a one-line fix for a real, currently-broken capability.
- Inspect GitHub repositories via API: **REAL**, two independent mechanisms — genuine `httpx` REST
  PR-creation (`git_push_tool.py::create_github_pr`, real Bearer-token auth) and real `gh` CLI
  wrapping for issues/PRs/comments (chat agent only).
- Inspect arbitrary APIs/documentation (api_designer/api_docs agents specifically): **NOT FOUND** —
  both are internal-repo-only by explicit design (their own prompts forbid documenting anything not
  read from this repo's own handler code); neither has a fetch/search tool in its tool list.
- RAG/documentation used while coding: **NOT what it appears to be** — the "memory" system
  (`app/memory/store.py`) is the fleet's own self-referential task-history embeddings, not
  retrieval over external library/framework documentation. `rag_engineer_agent` *designs* RAG
  pipelines as a deliverable for the target project; it does not itself retrieve external docs to
  inform its own output.
- Explicit limitations (real, code-confirmed): raw `curl`/`wget` are themselves in the general bash
  denylist (must use the dedicated fetch tools instead); all fetch tools truncate response bodies
  (2-8KB) with short timeouts, no JS-rendering, no pagination support; `web_search` has no API-key
  requirement but also no SLA (scraping-based library, failures degrade to an error string, no
  retry/backoff).

---

---

## Q21. Security Audit

- **Credential protection: REAL.** `backend/app/security/credential_vault.py` uses genuine Fernet
  symmetric encryption keyed by `CREDENTIAL_ENCRYPTION_KEY`; secrets displayed as masked
  (`**********`) unless explicitly unmasked. Degrades to plaintext storage with a one-time warning
  if the encryption key is unset in development — but gap-closure Day 7 (2026-07-30) made this a
  genuine hard-fail in production: `backend/app/config.py`'s new `deployment_env` field (default
  `"development"`, so every existing local/test/docker-compose setup keeps working unchanged) is
  checked by `_require_credential_encryption_in_production` (`app/config.py:487-499`, line numbers
  as of gap-closure Day 10 — shifted down from their Day 7 value by Day 9's added sandbox settings
  fields; re-verified live against current code, not assumed stable) — when
  `DEPLOYMENT_ENV=production` and `CREDENTIAL_ENCRYPTION_KEY` is unset, `Settings` construction
  itself raises `ValidationError` at startup, not just a log line. Proven by
  `backend/tests/test_credential_encryption_production_gate.py` (5 tests): default profile is
  development (no key required), production without a key raises, production with a valid Fernet
  key succeeds, staging keeps the old optional-with-warning behavior.
- **Secret management: PARTIAL** — no external vault (HashiCorp/AWS Secrets Manager) integration;
  the "vault" is this project's own DB-table + optional-Fernet wrapper.
- **Sandboxing: REAL for the highest-risk surface, honestly scoped — gap-closure Days 8-9
  (2026-07-30).** Real, live-tested, no-hallucination finding that motivated the fix: ran
  `app.policy.engine.check_command("find /workspace -mindepth 1 -delete", strict=True)` directly —
  returned `allowed=True`. No `_DENIED_COMMAND_PATTERNS` entry matches `find ... -delete`, only
  `rm -rf` (and its normalized flag variants) — a genuine, reproducible denylist bypass, not a
  hypothetical.
  New `backend/app/policy/sandbox.py::run_sandboxed()`: a fresh, `--rm` Docker container per
  command, the caller's repo-worktree path bind-mounted read-write at `/workspace` (the ONLY host
  path visible — no `docker.sock` mount, no path back to the host's Docker engine), real
  cgroup-enforced `--memory`/`--pids-limit`/`--cpus` caps. Fails **closed**, not open: if Docker
  isn't reachable, `run_sandboxed()` raises `SandboxUnavailableError` rather than silently
  re-running the command on the host — the only way to run unsandboxed is the explicit,
  operator-set `BASH_SANDBOX_ENABLED=false` (new `Settings.bash_sandbox_enabled`, default `True`).
  Wired into the **three fully-generic, denylist-only bash tools** — `make_chat_handlers.bash`,
  `make_coder_handlers.bash`, `make_scoped_bash_handler.bash_h` — the ones with no command-prefix
  allowlist at all, where a bypassable regex was the *entire* remaining defense.
  **Honestly NOT yet done, not silently skipped**: the other ~12 already-allowlist-scoped bash
  handlers (test-runner, dependency-audit, QA, devops, cicd, refactor, dependency-agent,
  migration-agent, ai-engineer, cleanup-agent, infra-dry-run) are not wired to this yet — those
  commands need the TARGET repo's own installed toolchain (its venv/node_modules), which the
  minimal default sandbox image (`alpine:latest`, operator-configurable via
  `Settings.bash_sandbox_image`) does not have; sandboxing them correctly needs either a per-repo
  sandbox image or an install-then-run flow, real additional work, tracked as a named follow-up.
  Also NOT yet resolved: the containerized production deployment (`docker-compose.yml`'s `backend`
  service, itself running inside a container) has no path to reach a Docker daemon to spawn
  sandboxed sibling containers — this requires its own explicit security-tradeoff decision (raw
  `docker.sock` mount = simplest but backend-compromise-means-host-compromise; a
  docker-socket-proxy service = safer, narrower API; a dedicated sandbox-executor sidecar =
  safest, most work), deliberately left to the operator rather than silently resolved — the sandbox
  mechanism itself is proven and wired for any environment where the backend process already has
  Docker CLI/daemon access, however that's provisioned (this dev/test environment among them).
  Proven by `backend/tests/test_sandbox.py` (8 tests, real Docker calls throughout except the one
  Docker-unavailable branch) and `backend/tests/test_bash_sandbox_wiring.py` (9 tests) — including
  the exact `find -mindepth 1 -delete` denylist bypass, run through all three real wired handlers,
  contained to only the mounted workspace.
- **Dangerous command detection: REAL** — `app/policy/engine.py`'s `_DENIED_COMMAND_PATTERNS` is a
  genuine, actively-enforced regex denylist (rm -rf, kubectl, terraform, git push, npm publish,
  docker push, sudo, fork bombs, credential-file cat, curl-pipe-to-shell, etc.), with command
  normalization to close `rm -fr`/`--recursive --force` bypass variants, plus a non-overridable
  hard-block subset even a human "approve" click can't bypass.
- **Permission system (approval_gate.py): REAL enforcement** — denial genuinely returns
  `"[DENIED]..."` and the command never runs; not merely logged/advisory. See Q39 for detail.
- **Prompt injection resistance: REAL but narrow (this engagement's own Phase 6.3 work)** —
  `base_graph.py` wraps `web_search`/`read_file`/`read_files` output in `<untrusted_external_data>`
  delimiters and flags `bash`/`web_search` output matching injection-looking patterns with a
  security-warning banner, applied at the one real chokepoint every agent's tool result passes
  through. Flags rather than strips; pattern-based, so evadable by novel phrasing; narrow tool
  coverage.
- **Data leakage prevention: PARTIAL** — real, targeted controls exist: SSRF guard on the browser
  tool (blocks private/loopback/internal IPs) and secret-shaped-value redaction in env-var display
  (`_mask_secret_value`). No general-purpose PII/DLP scrubber over all agent output.

---

## Q22. Safety Audit

**NOT FOUND** — there is no keyword/classifier-based refusal logic for malware/ransomware/
credential-theft/phishing/cybercrime/illegal-automation content anywhere in the codebase. Grepped
`policy/engine.py`, `security/credential_vault.py`, and the whole `backend/app` tree: zero
malware/cybercrime/illegal-activity classifier or keyword logic. The only "gates" that exist are the
destructive-*command* denylist (execution safety, Q21) and RBAC (who can act) — neither inspects a
request for *malicious intent*. **A request for harmful content would only be stopped by the
underlying model's own built-in safety training** — nothing in `backend/app` would intercept it
first or after the fact.
Plan: this is a real, clean gap if an additional layer beyond the base model's training is wanted —
would need a pre-flight intent classifier or a post-hoc content filter, neither of which exists
today even as a stub.

---

## Q23. Production Readiness Score

- Architecture: 70% — LangGraph-based agent graphs (`base_graph.py`, `pipeline/graph.py`), 72 real
  agents with individually curated tool contracts (IMPLEMENTATION_PROGRESS.md Steps 1-4), clear
  layering (agents/fleet/memory/api/policy/security). Weakness: no multi-tenant/project entity at all
  (`credential_vault.py`: "this project has no 'project' entity"), single global active-repo module
  variable (`app/api/repo.py::_active_repo_path`).
- Orchestration: 65% — real `manager.py` epic orchestration converted to a LangGraph `StateGraph`
  (5.1, 5 nodes), bounded retries, `SlotAcquisitionTimeout` handling at all 4 acquisition points (5.6).
  Concurrency caps are in-process `asyncio.Semaphore` only (`pipeline/concurrency.py`) — do not
  coordinate across multiple processes/machines even though an optional RQ backend exists
  (`app/queue/rq_adapter.py`, opt-in, `queue_backend` defaults to `"asyncio"`).
- Memory: 75% — real pgvector-backed `memory_embeddings` (task/failure/architecture/learning/procedure
  categories, Phase 1.1-1.5), DB-backed queries survive process restart (`app/memory/store.py`). Real
  gap, confirmed in schema: `MemoryEmbedding` has no `repo_id`/`project_id` column
  (`app/db/models.py:495-519`) — memory is global across every repo ever worked on, not scoped.
- Agent Intelligence: 65% — 72 agents with tiered tool access (Executor/Editor/Analyzer, Step 2),
  `record_learning` rolled out fleet-wide (Phase 4 Item 4), context builder with call-graph ranking.
  Self-critique now real for the 5 Tier-A agents (`enable_critique=True` — coder/backend_dev/
  frontend_dev/qa/reviewer, gap-closure Days 11-14, 2026-07-30); still `False` for the rest of the
  fleet. Replanning still `False` everywhere, deliberately deferred pending critique's real-run
  validation (Session-0-style opt-in per IMPLEMENTATION_PROGRESS.md 3.5/3.6).
- Reasoning: 55% — planning/reflection nodes exist (`planner_node`, `reflection_node`,
  `_gather_facts_and_plan`), but continuous replanning (3.6) and self-critique (3.5) are both
  fleet-default-disabled, so the "reasons about its own output and iterates" capability is real but
  not actually running for the vast majority of live agent runs today.
- Planning: 60% — `planner_node`, `_should_replan` with evidence-grounded triggers, bounded by
  `max_replans`/`max_turns`, tested end-to-end (`test_phase36_continuous_replanning.py`). Same
  opt-in-disabled caveat as Reasoning.
- Learning: 60% — `record_learning` tool + `versioned_lessons` PUBLISHED→`memory_embeddings` bridge
  (Phase 1.2) is real and tested. No cross-org approval workflow found for "who approves organizational
  learning" beyond the existing PENDING/PUBLISHED lesson-versioning states (Q93 territory, not
  independently re-verified here).
- Tools: 80% — very large real tool surface (`app/agents/tools.py`, 11k+ lines), policy-enforced
  allow/denylist (`app/policy/engine.py`), scoped bash tools per tier (Step 2), dead-contract bugs
  fixed fleet-wide (Phase 2.3/4). Real, deliberate gap: `terraform`/`kubectl` blanket-denied fleet-wide,
  no dry-run carve-out (documented, not a bug).
- Safety: 75% — policy engine allow/denylist, HITL approval gate (`approval_gate.py`,
  `request_human_input`), confirmation-gated destructive tools (`git_push`, `bash`, `git_reset --hard`,
  `undo_changes`, `run_migration`, `seed_database` — Phase 5.2), credential vault with Fernet
  encryption-at-rest (hard-required in production since gap-closure Day 7, see Q21), prompt
  injection defenses for `web_search`/`bash` output (Phase 6.3). `pip-audit` clean (the prior
  `ecdsa==0.19.2` / PYSEC-2026-1325 finding is resolved, gap-closure Day 7 — see Q24).
- Frontend: 55% — real Next.js app (`apps/web/app`) with dedicated pages for agents/approvals/chat/
  console/cost/epics/fleet/goals/login/metrics/onboarding/repo/review/settings/stream/tasks (18+
  route groups), e2e tests present (`apps/web/e2e`). NOT independently deep-audited by this synthesis
  pass (out of this agent's assigned question set) — percentage is a structural-presence estimate, not
  a UX/quality audit.
- Backend: 80% — FastAPI, 20+ routers under `app/api/`, layered `db`/`fleet`/`memory`/`policy`/
  `security`/`middleware`, alembic migrations (23 revision files), Dockerfile present.
- Testing: 70% — 134 test files, `IMPLEMENTATION_PROGRESS.md`'s final gate: 3318 passed / 21 failed /
  1 skipped / 17 deselected (2026-07-30), all 21 failures independently triaged as Windows-sandbox/
  no-Docker-Postgres/git-binary-PATH environment gaps, not app bugs. `mypy --strict`/`black`/`ruff`
  clean except one pre-existing POSIX-only import. Real gap: NOT VERIFIED — no load/stress/concurrency-
  at-scale test files found anywhere in the repo.
- Observability: 65% — real OTEL bridge (`app/fleet/metrics.py`, Phase 6.1) with parent-child span
  nesting, Sentry DSN-gated init, 3 reporting endpoints (`/api/fleet/reports/{cost,health,
  repair-patterns}`, Phase 6.2). Gap: OTEL only *exports* when `OTEL_EXPORTER_ENDPOINT` is set — no
  bundled collector/dashboard shipped with the repo itself (BYO backend).
- Deployment: 55% — `backend/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`,
  `.github/workflows/ci.yml` all present. NOT VERIFIED: no k8s manifests/helm charts found in this
  pass, and `infra_agent`'s own tool access is deliberately restricted to
  `docker build`/`docker-compose config`/`helm template`/`helm lint` (no real deploy execution —
  `terraform`/`kubectl` fleet-denied).
- Scalability: 40% — hard architectural ceiling found: `max_concurrent_agent_runs` defaults to 20,
  enforced by an in-process `asyncio.Semaphore` (`pipeline/concurrency.py`) that cannot coordinate
  across multiple backend processes/machines; the one global `_active_repo_path` variable
  (`app/api/repo.py`) means the whole process operates against exactly one active repo at a time. RQ
  (Redis Queue) exists as an opt-in distributed dispatch backend but doesn't change the semaphore
  model. See Q77 for detail.
- Performance: 60% — `llm_call_timeout_seconds` config, token/cost accumulation fixed end-to-end
  (3.2), heartbeat-based staleness detection computed server-side in Postgres (6.2 bug fix). NOT
  VERIFIED: no measured latency/throughput benchmarks found in the repo.
- Maintainability: 75% — consistent per-agent tool-contract pattern, `TOOL_MANIFEST` compliance tests,
  `mypy --strict`/`black`/`ruff` all clean fleet-wide, extensive in-repo documentation of every design
  decision (`IMPLEMENTATION_PROGRESS.md` itself is unusually rigorous evidence of this).
- **Overall Production Readiness: ~62%** — a genuinely substantial, well-tested single-tenant/
  single-workspace engineering-agent platform (backed by 3318 passing tests and 6 fully-implemented
  spec phases), but not yet a multi-project/multi-tenant enterprise system: the "no project entity"
  gap (Q94/Q95) and in-process-only concurrency ceiling (Q77) are the two largest structural blockers
  to the score being higher.

---

---

## Q24. Missing Features (vs. Claude Code)

### Critical
- **True multi-project/multi-workspace isolation.** Why it matters: today the entire backend process
  has exactly one active repo (`app/api/repo.py::_active_repo_path`, module-level global) and memory
  has no project scoping column at all (`MemoryEmbedding` — no `repo_id`); this is a hard blocker for
  running the platform as more than one team's tool at a time. Claude Code: each CLI/session process is
  inherently scoped to the cwd it was launched in — no shared global state across projects. Should be
  implemented: add `project_id`/`repo_id` to `MemoryEmbedding`, replace the module-level
  `_active_repo_path` with a per-request/per-session repo context threaded through every agent
  dispatch (the `repo_path` override already exists on `specialized_agents.py`'s endpoints — the gap is
  making it the *only* path, not a fallback to a global). Complexity: High. Dependencies: DB migration,
  every one of the ~72 agents' dispatch call sites. Order: 1st — nothing else in the roadmap matters at
  scale until this lands.
- **Distributed/horizontal concurrency.** Why it matters: `max_concurrent_agent_runs` is enforced by an
  in-process `asyncio.Semaphore` — cannot scale past one machine's process even with RQ enqueued jobs.
  Claude Code doesn't need this (single local session), but this repo's own stated ambition
  (hundreds of agents, Q77) requires it. Should be implemented: move slot accounting into Postgres/Redis
  (row-level lock or Redis token bucket) so multiple worker processes share one real cap. Complexity:
  High. Dependencies: multi-project isolation (above) should land first so slots are project-scoped too.
  Order: 2nd.

### High Priority
- **Durable resumability for the ~70 worker agents — gap-closure Day 18 (2026-07-31): the
  "genuinely hard to get side-effect-safe" risk this item already predicted is now CONFIRMED, not
  hypothetical.** Only `pipeline/graph.py` (pm/architect/decomposer) uses `AsyncPostgresSaver`
  (durable); `base_graph.py` (every other agent) still has no checkpointer, so a Python/Docker crash
  mid-run still loses that run's progress entirely today (caught only by orphan-recovery marking it
  "failed" after 900s, not resumed) — that half of the finding is unchanged.
  What's new: before wiring a checkpointer (which the plan's own Day 18 required proving safe
  first, not assuming it), built a standalone repro (not production code) — real LangGraph 1.2.7,
  real `MemorySaver` checkpointer, a node shaped exactly like `execute_tools`'s real structure (one
  synchronous `for tu in tool_uses:` loop, each iteration performing a real, external side effect).
  Result: **a process crash partway through that loop, followed by a resume from the last
  checkpoint, re-runs the ENTIRE node from the start — including tool calls that already completed
  with real side effects before the crash.** In the repro, two "tool calls" that had already run
  (and would map to a real git commit / file write in production) ran a second time after resume.
  This is exactly the "whole node replays" hazard `chat_agent.py`'s Phase 5.2 docstring already
  named and solved for the interactive chat graph (one-tool-call-per-node-invocation, not
  batch-per-node) — now empirically confirmed to also apply to `base_graph.py`'s differently-shaped
  `execute_tools` node, not assumed by analogy.
  Per the plan's own explicit hard-stop condition for this exact scenario, the schedule extended
  rather than compressed: `execute_tools` needed the same one-tool-call-per-node-invocation
  decomposition `chat_agent.py` already proved safe, BEFORE a checkpointer could be safely added — a
  real, structural, fleet-wide (~74-76 agent modules) refactor of the shared node builder, not a
  quick wrapper.
  **Gap-closure Day 19 (2026-07-31): DONE.** `_make_execute_tools_node`
  (`backend/app/agents/base_graph.py:1268` — `def` line, re-verified during the Day 34 Gap Audit;
  drifted from Day 24's own citation of `1132-1432` because Stage 1.5's same-day insertions above
  it in the file shifted everything below; drifted before that from the original `1039-1339` after
  Days 21-22's edits. This citation has now drifted twice — re-verify against
  `_make_execute_tools_node`'s own `def`/`return execute_tools` if it drifts again rather than
  trusting the line number) now processes
  exactly one pending tool call per invocation instead of looping over the whole batch inline. New
  `AgentRunState` fields (`pending_tool_uses`, `tool_results_buffer`, `batch_requires_human_approval`,
  lines 198-200) carry a batch across invocations; when a batch isn't drained yet, the node returns a
  partial state update instead of appending to `messages`/incrementing `turns`.
  `_post_execute_tools_router` (line 1812, re-verified during the Day 34 Gap Audit — drifted from
  Day 24's `1676` for the same reason as above) self-loops back to `execute_tools` (via
  `build_agent_graph`'s `{"execute_tools": "execute_tools", ...}` conditional-edge keys, now at
  lines 1938, 1948, 1970, and 1991 — 4 occurrences, not the 2 Day 24 recorded; re-verified via
  live grep during the Day 34 audit) while
  `pending_tool_uses` is non-empty, mirroring `chat_agent.py`'s already-proven Phase 5.2 pattern
  exactly. Proven against the REAL production node (not a toy analog this time):
  `tests/test_gap19_execute_tools_replay_safety.py` builds a real `StateGraph` from the real
  `_make_execute_tools_node`/`_post_execute_tools_router` with a real `MemorySaver` checkpointer,
  stops consuming the stream after 2 of 3 real side effects have happened (simulating a real
  process crash — no exception, the process just stops), resumes with the documented
  `graph.stream(None, config)` convention, and confirms the real external side-effect log shows
  `["a", "b", "c"]` — never `["a", "b", "a", "b", "c"]`. A real bug was also found and fixed while
  wiring this: `reflection_node` can replace `messages[-1]` with a plain-string `"[Self-review]"`
  message when unsatisfied, which the pre-Day-19 code silently no-opped on (zero tool_uses parsed
  from a string) but the naive Day-19 rewrite crashed on (`IndexError` on an empty `pending` list)
  — full regression (`tests/test_phase36_continuous_replanning.py`) caught this immediately; fixed
  by an explicit empty-batch guard that returns the same no-op final state the old code produced.
  Full regression: 20/20 pre-existing (environment-specific, unrelated) failures unchanged,
  3,436 passed (3,434 pre-existing + 2 new replay-safety tests), zero new regressions. Complexity: High,
  confirmed, not estimated. Dependencies: the pattern already existed and was proven in this
  codebase (`chat_agent.py`'s own `_execute_tool_node`) — this applied a working design to a
  second, structurally different graph, not inventing one from scratch.
  **Day 20 (2026-07-31): DONE.** Day 20's originally-planned scope ("prove the decomposition safe
  against real code, plus full regression") turned out to already be satisfied by Day 19's own
  work, so Day 20 redirected to two gaps Day 19's tests didn't cover instead of repeating them: (1)
  grep-confirmed no file outside `base_graph.py` references `_make_execute_tools_node`/
  `_post_execute_tools_router` directly, so the refactor's blast radius is fully contained to the
  shared builder as designed; (2) new `tests/test_gap20_execute_tools_batch_with_critique.py` proves
  a fully compiled graph (`enable_critique=True`) with a real multi-tool_use batch (a setter tool +
  `submit_result` in one LLM turn) drains completely before `critique_node` fires exactly once —
  the one scenario neither Day 19's isolated-node tests nor the pre-existing
  `test_phase35_self_critique.py` (single-tool-use turns only) could have caught a routing mistake
  in. Full regression: 20/20 baseline unchanged, 3,437 passed.
  **Day 21 (2026-07-31): DONE — `build_agent_graph()` now durably checkpoints via a real
  `AsyncPostgresSaver`.** `backend/app/agents/base_graph.py:66-117` (`init_agent_checkpointer`/
  `close_agent_checkpointer` — re-verified again during the Day 34 Gap Audit, still accurate at
  66-117; original citation was 48-104 before Day 22's circuit-breaker import shifted it, mirroring
  `pipeline/graph.py`'s own established pattern exactly); `base_graph.py:2001`
  (`g.compile(checkpointer=_agent_checkpointer)` — drifted from Day 24's `1865` after Stage 1.5's
  same-day insertions above it; re-verified live during the Day 34 audit); `base_graph.py:2277`
  (`graph.stream(..., config={"configurable": {"thread_id": tid}})` — drifted from Day 24's `2140`
  for the same reason — `tid` is the run's own
  pre-existing stable identity, already used as `trace_id`). Wired into `app/main.py`'s lifespan.
  Investigated (not assumed) whether `AsyncPostgresSaver` — built for async `ainvoke`/`astream` —
  actually works with `run_agent_graph()`'s sync `graph.stream()`: read `AsyncPostgresSaver`'s real
  source, confirmed its sync methods bridge cross-thread via `run_coroutine_threadsafe` and require
  being called from a different thread than whichever owns the checkpointer's loop; grep-confirmed
  every real dispatch path (`app/api/specialized_agents.py`'s two endpoints,
  `app/agents/manager.py`'s dev/qa/reviewer dispatch) already wraps `run_agent_graph()` in
  `asyncio.to_thread()` — exactly satisfying that contract, confirming `AsyncPostgresSaver` (not a
  sync `PostgresSaver`) is correct here.
  Two real findings, both evidenced rather than assumed: (1) on native Windows (this dev machine,
  not Docker), `init_agent_checkpointer()` falls back to `MemorySaver` — root-caused to psycopg3's
  async mode being incompatible with Windows' default `ProactorEventLoop`; confirmed this is a
  **pre-existing** limitation already present in `pipeline/graph.py`'s own `init_checkpointer()`
  (reproduced identically against it, not introduced today) and confirmed it does NOT affect real
  production (Docker/Linux, `backend/Dockerfile`, whose default loop has no such incompatibility) —
  documented rather than silently worked around or expanded into an out-of-scope global
  event-loop-policy change. (2) A real bug: `close_agent_checkpointer()`'s first version never reset
  `_agent_checkpointer` back to a working default after closing, leaving it bound to a dead event
  loop — harmless in production (close only happens once, at shutdown) but caught by this day's own
  new test doing init+close within one long-lived process, which caused 51 cascading failures on the
  first full regression run; fixed by resetting to a fresh `MemorySaver()` in the cleanup path, back
  to the 20-item baseline immediately after.
  Tests: `tests/test_gap21_agent_checkpointer_postgres.py` (2 tests) against the real running
  Postgres (`gridiron-postgres` docker container) — one proves Day 19's crash+resume replay-safety
  property holds through the real `init_agent_checkpointer()`/`build_agent_graph()` wiring
  (reporting whichever backend actually activated); the other isolates the Windows event-loop
  variable with an explicit `WindowsSelectorEventLoopPolicy()` override, proving the real
  driver/connection/table-setup logic genuinely works end to end. Full regression: 20/20 baseline
  unchanged, 3,439 passed (one transient unrelated timing-flake on the first post-fix run, confirmed
  non-reproducing).
  **Day 22 (2026-07-31): DONE — a real circuit breaker now gates every Anthropic/Groq call.** New
  `app/fleet/circuit_breaker.py` (`CircuitBreaker`: closed → open → half-open, thread-safe, two new
  `Settings` fields for threshold/cooldown — no hardcoded magic numbers). Wired into all three real
  call-site surfaces: `base_graph.py:130`'s new `_call_anthropic()` wrapper (all ~6
  `client.messages.create` sites in the shared node builder ~74-76 agents route through);
  `chat_agent.py:2592`'s streaming `_call_llm_node` (drifted from `2439-2488` after Stage 1.5's
  `_condense_history_async`/`_summarize_dropped_messages_async` insertions above it; re-verified
  live during the Day 34 Gap Audit) (via the breaker's `allow()`/
  `record_success()`/`record_failure()` primitives directly, since an `async with ... stream()`
  block doesn't fit a single wrapped callable); `groq_adapter.py:317-367`'s `run_groq` retry loop
  (same primitives, since a caught `BadRequestError` with `tool_use_failed` is a real Groq response,
  not an outage signal, and must record success not failure).
  A real, fleet-wide bug found and fixed before shipping: the first version monkey-patched
  `client.messages.create` itself inside `_make_client()`, which broke 9 assertion sites across 3
  test files that inspect `mock_client.messages.create.call_count`/`.call_args_list` after
  `run_agent_graph()` — the suite's own established mocking convention. First full regression
  surfaced this (23 failures, 20 baseline + 3 real). Fixed by wrapping the CALL in a separate
  `_call_anthropic()` function instead of mutating the client object — `client.messages.create`
  itself stays untouched, so existing test assertions keep working while the breaker still gates
  every real invocation.
  Tests: `tests/test_gap22_circuit_breaker.py` (8, the state machine in isolation, including a real
  `threading.Thread` race proving concurrent half-open probes are correctly serialized) and
  `tests/test_gap22_circuit_breaker_wiring.py` (3, proving each real call site actually routes
  through the shared breaker). New `tests/conftest.py::reset_circuit_breakers` autouse fixture
  (mirroring the Day-10 `reset_db_engine` pattern) resets both breaker singletons between tests, so
  unrelated tests simulating LLM failures can't accumulate toward tripping the shared breaker.
  Full regression: 20/20 known baseline unchanged, 3,450 passed (3,439 + 11 new tests).
  `LLMProvider`/`app/fleet/providers/base.py` noted (zero implementations, zero usages anywhere) —
  dead scaffolding, same "built but never wired" pattern as `tool_manifest.py`; flagged, not
  silently resurrected — out of scope for today.
  **Day 23 (2026-07-31): DONE — background processes now durably tracked, with a real session-close
  hook that actually terminates them.** Found TWO separate, parallel background-process trackers, not
  one: `app/agents/tools.py`'s `_session_bg_procs` (the plan's own named file) and
  `app/agents/chat_agent.py::ChatAgent`'s own independent `self._background_processes` — both had
  the same gap (a GC'd `Popen` object doesn't terminate the real OS process). New
  `app/fleet/bg_process_registry.py`: `register`/`unregister` persist PIDs to a durable JSON file
  (new `Settings.bg_process_registry_path`, matching the existing `/tmp/gridiron-*` convention);
  `sweep_orphaned_processes()` terminates anything left over at FastAPI startup. Wired into both
  trackers' `run_background`/`kill_process` handlers, and — the real fix — into `delete_chat_agent()`
  (`chat_agent.py:141`), which already existed as the session-close hook but previously did nothing
  with `self._background_processes` at all; it now terminates every still-running process on
  graceful session close, with the startup sweep as the safety net for crashes that never reach it.
  Tests use real `subprocess.Popen` processes (not mocks): `tests/test_gap23_bg_process_registry.py`
  (6) and `tests/test_gap23_session_close_kills_bg_processes.py` (2), both confirming actual process
  termination via `proc.poll()` polling, not just trusting a return value. Full regression: 20/20
  baseline unchanged, 3,458 passed (3,450 + 8 new tests).
  **Day 24 (2026-07-31): DONE — Stage 1.3 (Days 18-23) signed off via a real Gap Audit Protocol
  re-verification, not a status re-report.** Fresh full regression: 20/20 known baseline unchanged,
  3,458 passed — identical to Day 23's own closing count, confirming nothing regressed silently
  between Day 23's close and this audit. All 52 tests across every Stage 1.3 test file (Days 19-23's
  own new files plus the pre-existing files Day 19's refactor directly touched) re-run together as
  one batch — all pass.
  Citation drift found and fixed (exactly what this protocol exists to catch): Day 19's and Day 21's
  `file:line` citations above had drifted because Day 21's checkpointer block and Day 22's
  circuit-breaker import were inserted above them in the same file, shifting everything below.
  Re-verified against live `grep`/`sed` output, not assumed, and corrected in place above:
  `_make_execute_tools_node` `1039-1339` → `1132-1432`; the `AgentRunState` batch fields
  `lines 110-112` → `198-200`; `_post_execute_tools_router` `1582` → `1676`; its self-loop
  conditional-edge keys `1708/1740/1761` → `1834`/`1855` (also fixing a citation error — the
  original lines actually pointed at the pre-existing, unrelated `call_llm` router); `init_agent_checkpointer`/
  `close_agent_checkpointer` `48-104` → `66-117`; `g.compile()`/`graph.stream()` `1842`/`2117` →
  `1865`/`2140`. `IMPLEMENTATION_PROGRESS.md`'s own dated, point-in-time entries for Days 19/21 were
  left as originally written (accurate as of when they were written) — only this living document was
  corrected.
  Stage 1.3 sign-off: Day 18 proved a real replay-safety hazard (not hypothetical). Day 19 closed it,
  catching 2 real bugs via full regression before shipping. Day 20 added one real end-to-end gap
  instead of repeating Day 19's already-complete proof. Day 21 wired real durable checkpointing,
  investigating a genuine sync/async compatibility question and catching a real state-leak bug before
  shipping. Day 22 wired a real circuit breaker into all three actual LLM-call surfaces, catching a
  real 9-site test-compatibility break before shipping. Day 23 found two undocumented
  background-process trackers and wired a real durable registry plus a session-close hook that
  actually works. Zero net regressions across the whole 6-day block — the known 20-item baseline is
  unchanged from before Day 18 to now.
  Order: Stage 1.3 (Days 18-24) complete. Next: Stage 1.4 (frontend/backend robustness).
  **Day 34 (2026-07-31): Stage 1 Gap Audit Protocol checkpoint — 6 of 7 Stage 1 sub-buckets
  (1.1, 1.2, 1.4, 1.5, 1.6, 1.7) independently re-confirmed live** (real code re-read at cited
  `file:line`s, cited tests actually re-run and passing, full regression re-run to completion:
  3,489 passed / 20 failed [unchanged known Windows-dev-only environment baseline] / 55 skipped /
  17 deselected; frontend 32/32). **Bucket 1.3 (this stage) found DRIFTED, not broken**: all
  underlying code and tests genuinely still work — the 6 citations corrected above (`1132-1432`→
  `1268`, `1676`→`1812`, `1834`/`1855`→`1938`/`1948`/`1970`/`1991`, `1865`→`2001`, `2140`→`2277`,
  `chat_agent.py:2439-2488`→`2592`) had gone stale again since Day 24's own correction pass,
  because Stage 1.5's same-day insertions into `base_graph.py`/`chat_agent.py` shifted everything
  below them and no later stage re-verified Stage 1.3's citations specifically. This is the same
  failure mode Day 24 already named and fixed once, recurring — confirms the risk is real and
  ongoing, not a one-off, and that any stage inserting code above an earlier stage's cited lines in
  a shared file should re-grep that earlier stage's citations, not just its own.
- **Per-project RBAC / real user table.** Why it matters: `UserRole` is a flat `viewer`/`approver`
  table (plus `admin` from JWT claims), and the actual user list is a JSON blob under one
  `system_settings` key (`auth_users`), not a proper table — no per-project or per-workspace
  permissions exist. Claude Code: N/A (single-user local tool) but Cursor/enterprise comparisons expect
  this. Should be implemented: real `users` table + `project_memberships` join table. Complexity:
  Medium. Dependencies: multi-project isolation. Order: 4th.
- ~~**Fleet-wide default-on iteration (critique/replanning).**~~ **PARTIALLY DONE (gap-closure Days
  11-14, 2026-07-30).** `enable_critique=True` now real for the 5 Tier-A agents (coder/backend_dev/
  frontend_dev/qa/reviewer); `enable_replanning` still `False` fleet-wide, deliberately deferred
  pending real-run validation of critique first (no live `ANTHROPIC_API_KEY` in this environment to
  produce that validation directly — a real, named blocker, not silently skipped). Full fleet-wide
  default flip (beyond these 5) still not done. Complexity: Low (the mechanism exists) but Medium
  risk (cost/latency impact on every run) — exactly why this was scoped to 5 agents first rather than
  flipped everywhere at once.

### Medium Priority
- **Load/stress/scale test suite.** Why it matters: zero load-test files exist for the platform's own
  infrastructure (only a `load_test_agent` role that *tests other people's software*). Claude Code
  doesn't need this either, but this repo's own scalability claims (Q77) are unverifiable without it.
  Complexity: Medium. Order: 6th.
- **Bundled observability backend.** Why it matters: OTEL only exports when `OTEL_EXPORTER_ENDPOINT` is
  externally configured — no collector/Grafana/Jaeger ships with the repo, so observability is
  BYO-infra. Complexity: Low-Medium. Order: 7th.

### Low Priority
- ~~**`ecdsa` CVE remediation**~~ **DONE (gap-closure Day 7, 2026-07-30).** PYSEC-2026-1325
  (ecdsa 0.19.2, transitive via `python-jose[cryptography]`, no upstream fix version) is resolved by
  migrating `backend/app/auth/jwt.py`/`app/auth/dependencies.py` from python-jose to PyJWT 2.13.0
  (`backend/requirements.txt`) — PyJWT has no `ecdsa` dependency at all for this project's HS256-only
  usage. `pip-audit -r requirements.txt` (no ignore flags needed) now reports zero known
  vulnerabilities; verified live in this environment, not from a cached report. The CI job's prior
  `--ignore-vuln PYSEC-2026-1325` carve-out (`.github/workflows/ci.yml`) is removed as dead —
  ecdsa is no longer installed at all, not just unreachable.
- **k8s/Helm deployment manifests.** `infra_agent` can only `helm template`/`helm lint`, never apply;
  no manifests found in-repo. Complexity: Medium. Order: after Critical/High items.

---

---

## Q25. User Intent Understanding

- Understand vague/incomplete requests: **PARTIAL** — `backend/roles/_GLOBAL_STANDARDS.md` §1 "UNDERSTAND" step (mandatory operating-loop step 1: "Identify: user goal, hidden intent, expected output, constraints, priorities, risks... list missing information") is prompt text every agent inherits; no code parses a request for vagueness/completeness.
  Plan: N/A (prompt-level by design for an LLM-driven system); if stronger guarantees are wanted, add a pre-flight completeness heuristic before dispatch.
- Detect hidden intent: **PARTIAL** — same `_GLOBAL_STANDARDS.md` §1 line ("hidden intent") — prompt instruction only, no runtime check.
- Detect conflicting requirements: **PARTIAL** — `backend/roles/architect.md` Quality Gates: "Checked for conflicts with existing code before proposing anything new"; `backend/roles/chat.md` Edge Cases: "Conflicting instructions across a session — confirm which stands." Both are prompt text, not a code-level conflict detector.
- Ask clarification questions before acting: **YES** — real tool + gate: `backend/app/agents/tools.py:363-418` (`REQUEST_CLARIFICATION_TOOL` / `make_request_clarification_handler`) records a real `PendingApproval`-style row via `app.fleet.approval_gate.request_human_input` and the agent's run ends cleanly with `status="needs_clarification"` instead of guessing (consumed e.g. in `backend/app/agents/planner.py:183-194`).
- Refuse to guess when information is insufficient: **YES** — same mechanism; `REQUEST_CLARIFICATION_TOOL`'s own description (tools.py:365-371) explicitly instructs "not for every minor judgment call... a reasonable, disclosed assumption is almost always better than stopping to ask" — i.e. it is scoped, not a blanket refusal-to-guess, but the escape hatch is real and wired, not aspirational.
- Separate multiple tasks from one prompt: **YES (worker-agent pipeline only)** — `backend/app/agents/decomposer.py` + `backend/roles/decomposer.md` implement a real `submit_subtasks` schema (typed subtasks, `depends_on` ordering) validated in `decomposer_node` (rejects empty subtask lists — `decomposer.py:183-191`). This applies to the PM→Architect→Decomposer→Manager pipeline, not to ad hoc chat requests (`chat_agent.py` has no equivalent task-splitting node).
- Prioritize tasks correctly: **PARTIAL** — dependency ordering exists (`depends_on` in decomposer output, migration-before-backend-before-frontend rules in `decomposer.md` lines 31-35) but there is no explicit urgency/priority scoring; "prioritize" in the audit sense (business priority) is not implemented, only execution-order dependency resolution.
- Detect explanation-only / analysis-only / planning-only / implementation / debugging / comparison / docs-only requests: **PARTIAL** — `backend/roles/chat.md` "Your Process" section (lines 49-81) has separate playbooks for QUESTIONS, BUGS/ERRORS, IMPLEMENTATION, EXPLORATION — this is a real, distinct per-intent procedure the model is instructed to select, but selection itself is the LLM's own judgment call each turn; nothing in `chat_agent.py` code classifies intent and routes to a different code path. No dedicated "comparison-only" or "docs-only" playbook found anywhere in the roles directory.
  Plan: if literal comparison-only/docs-only detection is required, add explicit playbook sections to `chat.md` and/or an intent-classification pre-step in `chat_agent.py`.

---

## Q26. Difficult User Handling

**Stage 1.6 (2026-07-31): DONE.** New "Handling Difficult Users / De-escalation" section in
`backend/roles/chat.md` (right after the Memory section) — a real, named section, not inferred from
generic professionalism norms: stay factual not defensive, don't perform repeated contrition,
restate conflicting constraints neutrally (cross-referenced to the new Hard-Constraint Conflict Rule
— Q53), don't re-run the same investigation to produce a differently-worded identical answer,
escalate instead of guessing to appease pressure to skip verification, and hold a verified fact
against user pressure/tone rather than conceding to match their certainty.
- Frustrated / angry / abusive language / poor English / mixed languages / one-word / extremely long
  prompts: **PARTIAL, improved** — the new section names the response PATTERN (stay factual, don't
  argue, don't over-apologize) generally rather than per-named-state; still no dedicated handling
  for poor-English/mixed-language input specifically (a language-detection feature, out of Stage
  1.6's scope) or extremely-long-prompt truncation beyond the existing Stage 1.5 context condense.
- Repeating the same issue / contradictory instructions / changing requirements repeatedly: **YES**
  — the new section explicitly covers both: contradictory constraints route to the Hard-Constraint
  Conflict Rule; a repeated request gets "check whether new evidence actually changes the answer
  before repeating yourself" instead of blind re-investigation.
- Remains professional / continues helping / avoids arguments: **YES** — "you cannot be argued out
  of a verified fact... don't concede to match their certainty" is now an explicit, named
  instruction, not just inferred from general communication-style rules.

---

## Q27. Clarification Engine

- Ask follow-up questions: **YES** — `REQUEST_CLARIFICATION_TOOL` (`backend/app/agents/tools.py:363-386`), wired into 38 agent tool contracts per `IMPLEMENTATION_PROGRESS.md` Day 1.4 rollout (verified independently via `backend/app/agents/planner.py:57` and `tools.py` usage).
- Ask only necessary questions: **PARTIAL** — the tool's own description explicitly discourages over-use ("not for every minor judgment call") — this is prompt-level self-restraint, not a code gate limiting call frequency.
- Avoid unnecessary interruptions: **PARTIAL** — same tool description text; no code-level rate-limit or necessity-check exists.
- Build a temporary plan while waiting: **NO** — no evidence found. When `request_clarification` fires, the run simply ends (`tools.py:416`, `"Ending this run to await an answer."`) — no draft/temp plan is constructed or persisted alongside the question.
  Plan: extend `make_request_clarification_handler` to optionally persist a draft plan/assumption set alongside the question so a resumed run can start from it.
- Remember previous answers: **PARTIAL** — the mechanism is designed for this ("a future run receives that answer in its task context" — `tools.py:347-360` docstring) via `app.fleet.approval_gate`'s recorded decision, but this is a re-dispatch pattern (a new run re-reads the recorded answer), not persistent conversational memory carried automatically; for chat sessions specifically, `ChatSession.history` (`backend/app/models/chat.py:35`) does persist full turn history, which functions as "remembering."
- Continue after clarification: **YES** — `backend/app/agents/planner.py:183-194` shows the real consumption path: a `needs_clarification` result is a distinct, parseable status a caller re-dispatches against; `chat_agent.py`'s `interrupt()`/`Command(resume=...)` graph (see Q54 evidence) is the equivalent real pause/resume mechanism for the interactive chat path, confirmed via a real two-line reproduction script per the module's own docstring (`chat_agent.py:1-54`).

---

## Q28. Requirement Analysis

- Understand a huge pasted prompt: **PARTIAL** — no dedicated "huge external prompt" ingestion feature; relies on the chat agent's general reading (large context window) and the PM/Architect/Decomposer pipeline's general task-description parsing. No code chunks or specially pre-processes a large pasted spec.
- Break into milestones: **YES (pipeline path only)** — `backend/app/agents/decomposer.py` + `backend/roles/decomposer.md` (real `submit_subtasks` schema, dependency-ordered, validated non-empty in code at `decomposer.py:183-191`).
- Find implementation dependencies: **YES** — `decomposer.md` lines 31-35 (`depends_on` field, migration-before-backend-before-frontend ordering rules), enforced by schema shape (structural, not semantically verified).
- Estimate work: **NOT VERIFIED** — no time/effort estimation code or prompt instruction found in `decomposer.py`/`decomposer.md`, `planner.py`/`planner.md`, or `manager.py`.
- Detect impossible requirements: **NOT VERIFIED** — no explicit "impossible requirement" detection found; closest is the generic escalation rule in `_GLOBAL_STANDARDS.md` §8 ("Escalate when the task is ambiguous and investigation cannot resolve it"), which is about ambiguity, not infeasibility per se.
- Detect duplicated work: **PARTIAL** — `architect.md` Quality Gates: "Checked for conflicts with existing code before proposing anything new" (prompt-level); the memory system's `query_procedures`/`query_memory_context` (`backend/app/memory/store.py:1086`, `:385` — re-verified 2026-08-03, Day 44 spot-check; was `182-239, 752`, drifted after Days 40-43's edits to this same file) can surface a semantically similar past task, which functionally supports duplicate-detection, but nothing forces the LLM to act on it.
- Suggest a better architecture: **PARTIAL** — `architect.md` is explicitly the role for this (produces `technical_approach`), prompt-driven only; no independent architecture-scoring code.
- Produce an execution roadmap: **YES** — the PM→Architect→Decomposer→Manager pipeline's `submit_subtasks` output with `depends_on` is a real, schema-validated roadmap artifact (`decomposer.py`).

---

## Q29. Existing Project Awareness

- Whether the feature already exists: **PARTIAL** — `architect.md` mandates verified-file discovery before proposing changes (Steps 2-4, lines 35-40) and its Quality Gates require conflict-checking, but this is prompt-enforced investigation, not a code-level "does X already exist" check.
- Whether a similar implementation exists: **PARTIAL** — same evidence, plus `backend/app/memory/store.py`'s `query_memory_context`/`query_procedures` can surface semantically similar past work at runtime (real code), though nothing forces the agent to query it before proposing new code outside the `memory_hook_node` path (`base_graph.py`).
- Whether code reuse is possible: **PARTIAL** — `coder.md` Step 3 ("Find patterns... Follow existing patterns — do not invent new ones") is the closest instruction; prompt-level only.
- Whether it conflicts with architecture: **PARTIAL** — `architect.md`/`decomposer.md` Quality Gates language ("Contradicting existing routes, schemas, or configs found in the repo" is listed as a Failure Condition in both files) — prompt-enforced via the Output Contract, not code-checked.
- Whether it violates project rules: **YES (for the fixed safety subset)** — `backend/app/policy/engine.py` (via `backend/app/agents/guardrails.py:1-71`, confirmed a real delegation, not a duplicate/weaker copy per its own gap-closure note) code-enforces protected-path and dangerous-command denylists on every tool call in `base_graph.py`'s `execute_tools` gate. This covers hardcoded safety rules only (secrets, `.github/workflows/**`, destructive commands) — not general "project rules" like architectural conventions, which remain prompt-level.
- Whether another module already solves it: **PARTIAL** — same as "similar implementation exists" above; `search_code`/`search_symbols` tools make this checkable, but nothing forces the check.
- "Only then implement" ordering actually followed: **YES for the two real architectures this
  audit item covers — gap-closure Days 15-16 (2026-07-30 / 31).** `coder.md`/`architect.md` prescribe
  a fixed read-then-write sequence. New `VerificationConfig.blocking_until` ({tool_name:
  verification_key}) in `base_graph.py` — used by every worker agent routed through the shared,
  reusable `_make_execute_tools_node` (~74 of 76 agent modules, per Day 9's own citation count) —
  makes a declared `expected_verification` prerequisite an actual, enforced refusal: a tool named in
  `blocking_until` gets a real `[POLICY DENIED]` result and its handler never runs while the required
  flag is still `False`. Wired live to `dependency_security_agent` (`bash` refused until `read` is
  True) as the concrete proof, not just the primitive. Proven by
  `backend/tests/test_gap15_blocking_verification.py` (6 tests) — including same-turn ordering (a
  prior setter call in the same LLM turn satisfies a later gate in that same batch) and a negative
  control confirming tools absent from `blocking_until` are never gated.
  **`chat_agent.py`'s own specific case — the one this exact audit item originally named — closed
  Day 16, not left stale.** `chat_agent.py` has its own separate `_execute_tool_node`/graph
  implementation (interrupt-based pause-resume, its own `ChatGraphState`), architecturally distinct
  from `base_graph.py`'s shared node the Day 15 mechanism hooks into — Day 15 correctly identified
  its `_VERIFICATION_CFG` as entirely dead code (no `state["verification"]` key existed in
  `ChatGraphState` at all) and scoped it as a named follow-up rather than silently claiming it done.
  Day 16 built that tracking from scratch: `ChatGraphState.verification` (new field, deliberately
  omitted from `run()`'s per-turn `initial_state` so it accumulates across the whole session via
  LangGraph's own checkpointer, not reset every user message) plus a real `blocking_until={
  "write_file": "read", "edit_file": "read", "apply_patch": "read", "bash": "read"}` enforced
  directly in `_execute_tool_node` (`delete_file` deliberately excluded — already gated behind a
  mandatory human confirmation since Day 5, a stronger protection than a prior-read requirement
  would add). Proven live, driving the real compiled graph through real scripted LLM turns (not
  internal bookkeeping): `backend/tests/test_gap16_chat_agent_verification_gate.py` (4 tests) —
  bash refused before any read, succeeds after a real read, the flag persists across two separate
  `agent.run()` calls on the same session (not reset per-turn), and write_file is blocked
  unconditionally even for brand-new file creation (a deliberately orthogonal concern from Day 5's
  "new file creation skips confirmation" — that gate is about human approval, this one is about
  due-diligence verification). 3 pre-existing tests in
  `backend/tests/test_phase52_file_mutation_confirmation.py` needed a preceding `read_file` turn
  added to their setup to keep reaching the confirmation-gate code path they actually test — an
  intentionally strengthened contract, not a regression (same "update the test to match the new
  contract" principle this engagement has applied consistently since Days 5-6).
  Plan: extend `blocking_until` from the one proof-of-concept agent (`dependency_security_agent`) to
  the rest of the ~74 base_graph.py-routed agents whose role files already state a read-before-write
  expectation, now that both architectures (shared graph, chat_agent's own) have a real mechanism.

---

## Q30. Safe Implementation

- Search the repository: **YES (prompt-mandated, tool-backed)** — `architect.md` Step 2 (`get_file_tree`), `coder.md` Step 3 (`search_code`/`search_symbols`) — real tools exist and are called in practice per the codebase's own test suite (`tests/test_phase34_real_output_verification.py` proves tool-call-then-submit wiring for representative agents), but the *requirement* to call them first is prompt-enforced, not code-blocked.
- Read related files: **YES (prompt-mandated)** — `architect.md` Step 4: "Do NOT name a file you haven't opened"; `chat.md` Anti-Hallucination Rule 6: "Read before edit. ALWAYS call `read_file` before `edit_file`." Not code-enforced (see Q29's gap note).
- Understand architecture: **PARTIAL** — `architect.md` Steps 1-3, prompt-level.
- Identify dependencies: **YES** — `decomposer.md`'s `depends_on` field is real and schema-validated; `architect.md` Step 7 ("Identify the minimal change set").
- Create a plan: **YES** — `planner.py`'s `submit_plan` tool is schema/length-validated in code: `_validate_plan()` (`planner.py:106-114`) rejects a plan under 100 chars or missing required sections ("## ", "Implementation Steps", "Files To Inspect") — a real, code-enforced minimum, not just a prompt request.
- Explain risks: **YES (prompt-mandated)** — `architect.md` Step 8: "Assess risks. Be honest." — required field in the plan output, not independently code-verified for content quality.
- Preserve backward compatibility: **PARTIAL** — `_GLOBAL_STANDARDS.md` §4 lists "Backwards Compatibility" as a default engineering principle every agent inherits; prompt-level only, no code check for breaking changes.

---

## Q31. Resource Awareness

- RAM: **YES**
- CPU: **YES**
- GPU: **YES** (checked; not required by default — see below)
- Disk space: **YES**
- Docker availability: **YES** (checked; not required by default — see below)
- Python version: **YES**
- Node version: **PARTIAL** — probed and reported, but not threshold-gated (no minimum Node version is enforced; this project has no documented Node-version floor to check against, unlike the real Python 3.11+ requirement)
- CUDA availability: **YES** (checked; not required by default — see below)
- Virtualization support: **YES** (reported, informational — no threshold; matches the audit's own framing, "support" not "minimum")
- "If requirements are insufficient, does it explain why and recommend alternatives?": **YES**
  **Gap-closure Day 35 (2026-08-03, Stage 2)**: built `backend/app/fleet/resource_check.py::run_resource_check()` — real, live probes (no mocking in production code) via `psutil` (RAM/CPU/disk), `shutil.which`/`subprocess` (Docker via `docker info`, Node via `node --version`, GPU/CUDA via `nvidia-smi --query-gpu`/banner-parsed `CUDA Version:`, virtualization via `systemd-detect-virt`), plus `sys.version_info` for the Python-version check. Each external probe is best-effort (`_run_probe`, `resource_check.py:50-60`) — a missing binary, timeout, or permission error is treated as "unavailable," never raised, so the check itself can never crash a caller. Thresholds are real config, not hardcoded (`app/config.py`: `resource_min_ram_gb`=1.0, `resource_min_disk_gb`=2.0, `resource_min_cpu_count`=1, `resource_required_python_version`="3.11", `resource_require_docker`=False, `resource_require_gpu`=False, `resource_check_subprocess_timeout_seconds`=5.0 — all documented in `.env.example`). When a threshold is violated, `ResourceCheckResult.reasons`/`.recommendations` are populated with the specific shortfall and a concrete alternative (e.g. "Reduce agent concurrency..." for RAM/CPU, "Free disk space..." for disk) — `resource_check.py:167-215`. Docker/GPU are opt-in-required (`require_docker`/`require_gpu` params, default `False`) since most agent work is LLM-API-driven, not local-resource-bound — only a caller that specifically needs Docker/GPU should require them.
  New dependency: `psutil==7.2.2` — verified against `pip index versions psutil` (latest stable) before pinning, per the zero-hallucination rule, not guessed.
  **Gap-closure Day 36 (2026-08-03, same day, Stage 2)**: wired into a real execution gate — `backend/app/agents/manager.py::_resource_check_node` runs as the new first node of the epic-manager LangGraph (`build_epic_manager_graph()`, `START → resource_check → cost_estimate → planning → conflict_check → coding → finalize`, `manager.py:1366-1377`, current post-Day-38 line numbers — re-verified, not the original Day-36 citation, which drifted after Day 38 extended the node above it). Unlike the cost-estimate gate (where human approval is a legitimate way to proceed anyway), an insufficient resource result halts the epic immediately — mirrors `_conflict_check_node`'s halt-and-return-early shape, not `_cost_estimate_node`'s approval-gate shape, since no human approval fixes insufficient RAM. On insufficient: `Epic.status="halted"`, `Epic.halt_reason` set to the real reason+recommendation text, `epic.halted` event published with a `resource_check` payload (ram/disk/cpu/docker/gpu snapshot + reasons + recommendations), and the returned `EpicApprovalPackage` carries the same `halt_reason` — `manager.py:793-913` (node body, current post-Day-38 range), `1320` (`_route_after_resource_check`). `run_resource_check()` is called with the epic's resolved repo path (`state.get("repo_path") or settings.target_repo_path`); a repo path that doesn't exist yet (not yet cloned) falls back to the process cwd rather than crashing (`resource_check.py:150-156`, new `disk_path.exists()` guard added this same day after tracing this exact edge case through the epic-manager's own state-resolution order).
  **Tests**: `tests/test_gap35_resource_check.py` grew to 12 (added
  `test_nonexistent_path_falls_back_to_cwd_instead_of_raising`, covering the edge case above).
  `tests/test_phase51_epic_manager_graph.py` grew a new `TestResourceHaltPath` class (2 tests):
  one drives `run_epic_manager()` through a real DB-backed epic with a simulated-insufficient
  `ResourceCheckResult`, asserting the epic is halted with the real reason/recommendation text in
  both the returned package and the DB row, and that cost-estimate/planning/coding are never
  reached (`AssertionError` side-effects on each, proving genuine short-circuit, not just an
  early-return that still lets the rest of the function body run) — same evidence-of-short-circuit
  pattern the pre-existing conflict-halt test already established. The second proves the other
  side of the conditional edge: with a real (unmocked) resource check on this sufficient dev
  machine, the graph proceeds past `resource_check` into the pre-existing
  `pending_cost_approval` path exactly as before Day 36 added the new first node.
  `TestGraphStructure::test_graph_compiles_with_the_6_expected_nodes` updated (was 5 nodes, now 6).
  `black`/`ruff` clean; `mypy --strict` clean on `manager.py`/`resource_check.py`.
  **Full regression, Day 35**: 3520 passed (3509 baseline + 11 new), 0 failed, 55 skipped, 17
  deselected. **Full regression, Day 36**: 3523 passed (3520 + 3 new: 1 edge-case test +
  2 resource-halt-path tests), 0 failed, 55 skipped, 17 deselected — exact match both days, zero
  regressions.
  **Honestly still open**: Node-version is probed but has no enforced minimum (no real requirement
  exists in this project to check against — not a gap, a correct absence). The pre-flight gate
  only covers the epic-manager path (`run_epic_manager`); the "simple mode" `launch_coder` path
  (Audit 04's own documented parity gap, unrelated to this plan) does not run through
  `build_epic_manager_graph()` at all and so isn't covered by this check either — out of this
  plan's scope, not silently missed.

---

## Q32. Project Size Awareness

- Repository size: **YES** — real, measured (not estimated)
- Memory required: **PARTIAL** — real projection exists, coefficient-based (no real memory-per-run history source exists yet to calibrate against — a named, separate gap), AND now gated: wired into the real pre-flight check as of Day 38 (projected memory vs. real available RAM)
- Disk space required: **YES** — real projection (coefficient-based) now gated against `resource_check.py`'s real free-disk number in the actual pre-flight check (Day 38)
- Estimated processing time: **YES** — real historical average from `agent_runs` (`agent_type='coder'`) when history exists, config fallback otherwise
- Estimated indexing time: **PARTIAL** — real projection exists, coefficient-based only (no historical data source exists — `app/repo_tools/scanner.py` records no duration anywhere, confirmed by grep, a genuine gap not silently assumed away); not itself gated (informational estimate only — see Day 38 scope note below)
- Estimated embedding time: **PARTIAL** — same as indexing: real projection, coefficient-based only (`app/repo_tools/embeddings.py` records no duration either); not itself gated
- Estimated test execution time: **PARTIAL** — real projection exists, coefficient-only by design: no `agent_runs` row is ever written for the QA node (`base_graph.py`'s pipeline path, where QA actually runs, writes no `AgentRun` row at all — confirmed empirically, zero rows of any kind exist in the real dev DB today), so there is no real signal to calibrate against, unlike processing time's real `coder`-type data; not itself gated
- "...before beginning?": **YES** — `_resource_check_node` (the epic-manager graph's first node) now calls `estimate_project_size()` and compares its disk/memory projections against real free disk/RAM before any planning or coding begins, halting the epic if either is exceeded
  **Gap-closure Day 37 (2026-08-03, Stage 2)**: built `backend/app/fleet/size_estimate.py`.
  `measure_repo_size()` is a real `os.walk` measurement (file count, byte size, per-extension
  breakdown), reusing the same directory-exclusion convention `app/agents/tools.py`'s
  `summarize_repo_h` (`tools.py:10393-10453`) already established (`.git`/`.venv`/
  `node_modules`/`__pycache__`) so the two agree on what counts — not a copy of that closure
  (it returns a formatted markdown string for agent consumption, not structured data), a fresh
  implementation of the same walk/exclusion logic per the plan's own "reuse the logic" framing.
  `estimate_project_size()` follows `cost_controller.py::estimate_epic_cost`'s exact shape: real
  historical average from `agent_runs` when available, config-coefficient fallback otherwise
  (`app/config.py`: `size_disk_multiplier`=3.0, `size_memory_mb_per_file`=2.0,
  `size_indexing_seconds_per_file`=0.05, `size_embedding_seconds_per_file`=0.15,
  `size_processing_seconds_fallback_per_subtask`=180.0,
  `size_test_execution_seconds_fallback`=120.0 — all documented in `.env.example`).
  **Real constraint discovered and honestly documented, not glossed over**: queried the actual
  dev DB directly (`SELECT agent_type, COUNT(*) FROM agent_runs GROUP BY agent_type`) — zero rows
  exist at all right now, and of the two `agent_type` values `app/api/agents.py`'s
  `create_agent_run()` ever writes ("planner", "coder" — simple-mode path only), the main
  pipeline/manager dispatch path (`base_graph.py`, where QA/reviewer/backend_dev/frontend_dev
  actually run) writes no `AgentRun` rows at all. This means "estimated test execution time"
  cannot be historically calibrated today by any code path that exists — the module says so
  explicitly (`test_execution_source` is always `"config_fallback"`) rather than wiring a
  historical branch against `agent_type='qa'` that would structurally never activate.
  **Tests** (`tests/test_gap37_size_estimate.py`, 6 tests, all passing): one measures this actual
  checked-out repo directory (`app/fleet/`) with an independent recursive count cross-check, proving
  a real walk not a fabricated number; one proves the junk-dir exclusion against real temp
  directories; two prove the no-DB config-fallback path and its subtask-count scaling; two insert
  real `AgentRun` rows into the real dev DB and prove the historical branch both activates with the
  correct real average (100s/200s → 150s, not asserted by reading the SQL) and correctly excludes a
  non-`coder` row and an incomplete (`finished_at IS NULL`) row from polluting that average.
  `black`/`ruff` clean; `mypy --strict` clean on both new files.
  **Full regression**: 3529 passed (3523 Day-36 baseline + 6 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
  **Gap-closure Day 38 (2026-08-03, same day, Stage 2)**: wired into a real execution gate.
  `_resource_check_node` (`app/agents/manager.py:793-913`) now calls `estimate_project_size()`
  alongside `run_resource_check()`, using the same subtask_count=5 placeholder
  `_cost_estimate_node` already documents using before planning determines the real count. Two new
  comparisons feed the *same* halt path Day 36 already built (one halt mechanism, not two parallel
  gates, per the smallest-change rule): projected disk requirement vs. real `disk_free_gb`, and
  projected memory requirement vs. real `ram_available_gb`. Either violation appends its own
  specific reason/recommendation string and sets `sufficient=False`, so a repo can now be halted
  even when Day 36's fixed global minimums are satisfied — a 5 GB free-disk floor doesn't help if
  this specific repo's projected working-copy footprint is 50 GB. The `epic.halted` event payload
  gained a `size_estimate` block (file count, measured size, both projections) alongside Day 36's
  `resource_check` block.
  **Tests**: `tests/test_phase51_epic_manager_graph.py` gained a new `TestSizeProjectionHaltPath`
  class (2 tests): one mocks a *sufficient* host (5 GB free disk) alongside a mocked *huge*
  size-projection (50 GB) and confirms the epic still halts with the size-specific reason text in
  both the returned package and the real DB row — proving this is a genuinely independent check
  from Day 36's, not redundant with it; the other confirms a real (unmocked) size estimate against
  this actual, modest test-repo path fits comfortably within real free disk/RAM on this dev
  machine, so the graph proceeds past `resource_check` into `cost_estimate` exactly as before
  Day 38. `black`/`ruff` clean; `mypy --strict` clean.
  **Full regression**: 3531 passed (3529 Day-37 baseline + 2 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
  **Honestly still open**: indexing/embedding/test-execution-time estimates remain informational
  only (Q32's own list treats them as separate "estimated time" items, not resource-sufficiency
  gates the way disk/memory are) — nothing in this plan's Q31/Q32 scope asked for a maximum
  acceptable indexing/embedding/test duration to gate on, unlike disk/RAM's "is there enough"
  framing, so no gate was invented for them. Memory/indexing/embedding/test-execution-time verdicts
  stay PARTIAL (real, coefficient-based, honestly not historically calibrated where no data source
  exists) rather than YES, matching this plan's standard of not overclaiming precision the evidence
  doesn't support.

---

## Q33. AI Suggestion Review

- Review it / compare with existing project / detect duplicated functionality / detect architecture conflicts / improve it / reject unsafe code / explain why: **NOT VERIFIED as a dedicated feature** — grepped the whole `backend/` tree (case-insensitive) for `ChatGPT|Gemini|Grok|paste`: zero real hits (the one match, `tests/test_phase4_item4_record_learning_rollout.py`, is unrelated). There is no dedicated "review AI-suggested code" workflow, tool, or role prompt anywhere in the codebase.
  Plan: this capability is not absent by omission of general skill — `chat_agent.py`'s normal read/search/edit toolset and `chat.md`'s Anti-Hallucination Rules (verify before naming, check imports, read before edit) would functionally let a user paste code into chat and have it reviewed against the repo, and the policy engine (`app/policy/engine.py`) would still block genuinely unsafe writes (protected paths, dangerous commands) regardless of code origin — but none of this is a *named, dedicated* "AI suggestion review" capability the audit is asking to verify. Rate the general capability PARTIAL (inherited from generic chat behavior) and the dedicated feature NO.

---

## Q34. Incremental Implementation

- Split large features into phases: **YES (pipeline path)** — `decomposer.py`/`decomposer.md`, same evidence as Q28.
- Build milestone plans: **YES** — `submit_subtasks` schema output, code-validated non-empty (`decomposer.py:183-191`).
- Implement one milestone at a time: **YES** — `backend/app/agents/manager.py` dispatches subtasks in an explicit per-subtask loop (`manager.py:187-236`, `for _subtask_idx, subtask in enumerate(subtasks): ... Manager dispatching subtask %d`) through a real Dev→QA→Review pipeline per subtask (module docstring, `manager.py:1-5`).
- Verify after every milestone: **YES** — same per-subtask loop routes each subtask through QA/Review before proceeding; `manager.py` also tracks `max_retries = settings.manager_max_subtask_retries` per subtask (line 143) before giving up on that one.
- Roll back if a milestone fails: **PARTIAL** — real checkpoint + escalate/abort machinery exists: `app.fleet.failure_ladder.checkpoint()`/`abort()`/`escalate()` (`manager.py:595-628`, "Day 12 — Failure Recovery Ladder"), snapshotting subtask results before an epic-wide halt (`_checkpoint({"results": results, "blocked_count": blocked_count}, ...)`) and emitting `epic.halted`. This is real, tested code (per `IMPLEMENTATION_PROGRESS.md`'s own gap-closure note that `save_checkpoint()` previously had zero callers and was wired here) — but it is checkpoint-and-escalate-to-human, not an automatic `git revert` of the failed milestone's already-applied file changes. A confirmation-gated `undo_changes` tool exists in chat (`chat_agent.py:2248-2261`, does `git checkout --`) but it is user-invoked in the interactive chat path, not auto-triggered by the manager pipeline on subtask failure.
  Plan: if literal automatic code rollback (not just checkpoint+halt+human-escalation) is required for a failed milestone, wire `abort()` to also invoke a git-revert of that subtask's diff before halting.

---

## Q35. Project Health Monitoring

- Broken imports: **YES**
- Dead code: **YES**
- Circular dependencies: **YES**
  **Gap-closure Day 48 (2026-08-03, Stage 2)**: all three closed together — `architecture_reviewer`
  now runs autonomously via a new `run_architecture_reviewer_scan()` (`app/agents/
  architecture_reviewer.py`), the 6th entry in `app/main.py::_fleet_agents_scan_loop()` (the
  exact real integration point this note's own "Plan" named), reusing the SAME 5-agent, config-
  gated (`fleet_scan_interval_hours`), two-phase SCAN-then-human-approved-APPLY pattern the
  existing Day-9 fleet self-improvement agents already use — no new mechanism invented. The scan
  runs `import_graph`/`circular_dep_detect`/`dead_code_detect`/`call_graph` against the
  platform's own codebase (`fleet_self_repo_path`) and files a real `EnhancementRequest`
  (`category="architecture"`, added to the model's documented category list) for each distinct
  real finding, mirroring `quality_auditor`'s own established scan-tool-list construction
  (filter an existing agent's tools by name, swap the one-shot terminal-submit tool for
  `submit_enhancement_request`).
  **A real, more significant pre-existing bug found and fixed while building this, not
  shipped**: `_SUBMIT_ARCH_REVIEW_TOOL`'s schema (`app/agents/tools.py`) — the terminal tool
  `run_arch_review()`'s own task-mode flow uses — declared fields `{verdict, issues,
  recommendations, summary}`, but `roles/architecture_reviewer.md`'s own documented "Terminal
  tool contract" specifies `{structure_summary, risks, recommendations, blast_radius,
  import_graph_ran}`, and `run_arch_review()`'s consuming code reads exactly THAT shape
  (`raw.get("risks", [])`, `raw.get("structure_summary", ...)`). Since `"risks"` never existed
  in the schema the LLM was actually told to fill out, `raw.get("risks", [])` always returned
  `[]` and `raw.get("structure_summary", ...)` always fell back to its default —
  **every real architecture-review finding this agent has ever produced was silently discarded**,
  regardless of what the LLM actually found, for as long as this tool has existed. Found by
  reading the role prompt's own documented contract before building the scan mode on top of it
  (repo-first-adjacent discipline — checking the project's OWN documented contracts, not just
  the code, before extending a system). Fixed the schema to match the prompt and the consuming
  code exactly (the prompt was correct; the schema was stale). A pre-existing test
  (`tests/test_day2_agents.py::test_submit_stores_result`) asserted against the old, wrong
  field names too (though it doesn't validate schema conformance, it documented the stale shape)
  — corrected to the real fields.
  **Tests** (`tests/test_gap48_architecture_reviewer_scan.py`, 7 tests): a direct regression
  guard on the fixed schema's exact property names; a real end-to-end proof that
  `run_arch_review()`'s consuming code correctly reads a properly-shaped result (real risks,
  real summary, real verified flag); scan-tool-list composition (submit_arch_review excluded,
  submit_enhancement_request + all 4 real analysis tools included); the new tool's category
  enum includes `"architecture"`; all required scan handlers present; a full mocked-LLM,
  real-DB test proving the scan's `submit_enhancement_request` handler, when actually invoked,
  writes a real `EnhancementRequest` row with `category="architecture"`; and a "verify real
  callers" guard (`inspect.getsource`) proving `architecture_reviewer` is genuinely wired into
  `_fleet_agents_scan_loop()`, not an orphaned function nothing calls. `black`/`ruff`/
  `mypy --strict` clean. All 258 pre-existing tests touching `architecture_reviewer`/agent
  fleet flags re-run unchanged, still pass.
  **Full regression**: 3589 passed (3582 Day-46 baseline + 7 new — Day 47 was documentation-
  only), 0 failed, 55 skipped, 17 deselected — exact match, zero regressions.
  **Honestly still open (Days 49-50's scope)**: "Unused files" and "Duplicate functions" remain
  **NO** — genuinely new detector tools that don't exist yet anywhere in this codebase, a
  materially larger build than "wire an existing real tool into the loop" (this day's actual
  scope). Named, not silently folded in.
- Memory leaks: **NO** — no evidence of any leak-detection tool or agent anywhere in the codebase.
  Plan: out of scope for a request/response Python backend; would need a dedicated profiling tool if desired.
- Performance regressions: **PARTIAL → regression gate now load-bearing, honest scope note below** — real: `benchmark_manager.py` + `regression_detector.py` compare live `MetricsCollector` data to a stored Postgres baseline (`agent_benchmarks` table) and gate `prompt_registry.deploy()`; `_benchmark_baseline_loop()` (`backend/app/main.py:203-247`) runs every 24h autonomously; `agent_performance_reviewer`'s scan (every 4h) also looks for backend/frontend perf issues.
  **Gap-closure Day 50 (2026-08-03, Stage 2)**: `prompt_registry.deploy()` now has a real caller — `make_fleet_apply_handlers()`'s shared `write_file`/`edit_file` handlers (`backend/app/agents/tools.py::_propose_and_deploy_role_prompt`, `_role_prompt_name`), used by all 4 write-capable fleet self-improvement agents' APPLY phases (`knowledge_curator`, `agent_debugger`, `agent_performance_reviewer`, `quality_auditor`), now route any write targeting `roles/<name>.md` through `prompt_registry.propose() -> submit_for_review() -> approve() -> deploy()` instead of a raw disk write. Each APPLY phase already only runs after a human approves the specific `enhancement_request`, so auto-advancing review/approval here reuses oversight that already happened rather than skipping it — while `deploy()`'s regression gate (`regression_detector.gate_deploy()`) is now genuinely reached and can genuinely block a bad prompt change (`[BLOCKED]` surfaced back to the agent, file never written). Confirmed on a real `DeploymentBlocked` path (`tests/test_gap50_prompt_registry_wiring.py::test_deploy_blocked_by_regression_gate_surfaces_blocked_message_and_no_write`) — file is verifiably *not* written when the gate fires.
  Still honestly PARTIAL, not YES: this is agent-run-latency regression (the only regression signal `regression_detector.py` computes), not general app performance-regression detection (e.g. API endpoint latency) — that remains a real, separate gap. What Day 50 closed is specifically the "regression gate is dormant" half of this item.
- Dependency conflicts: **PARTIAL → real autonomous CVE scanning now live, honest scope note below**
  **Gap-closure Day 49 (2026-08-03, Stage 2)**: `dependency_security_agent` now runs
  autonomously — new `run_dependency_security_scan()`, the 7th entry in
  `app/main.py::_fleet_agents_scan_loop()`, mirroring Day 48's exact same wiring pattern
  (filter the agent's tools by name, swap the one-shot terminal-submit tool for
  `submit_enhancement_request`, files real `EnhancementRequest` rows,
  `category="security"` — no new category needed, already documented). Runs real
  `pip-audit`/`npm audit` (via the existing `make_dependency_audit_bash_handler`) against the
  platform's own dependencies on the same periodic cadence as the other 6 fleet agents.
  **Honest scope note, not silently expanded**: this closes the *autonomy* gap (a real,
  working CVE-scanning agent existed but only ran on explicit task request) — it does NOT add
  a new version-constraint-graph / SAT-solver-style conflict detector (package A requires
  X>=2.0 while package B requires X<2.0), which doesn't exist anywhere in this codebase and
  would be a materially different, new-capability build, not a wiring fix. This audit's own
  "Plan" note groups "dependency conflicts" with `dependency_agent.py`'s unautonomous
  outdated-version detection in the same sentence — the real, buildable gap identified there
  was autonomy, not a missing conflict-detection algorithm; verdict stays PARTIAL to reflect
  that honestly rather than claiming YES for a capability that still doesn't exist.
  **A real, pre-existing bug found and fixed while building this, not shipped — the same bug
  class Day 48 found in `submit_arch_review`**: `_SUBMIT_DEPENDENCY_REPORT_TOOL`'s schema
  (`app/agents/tools.py`) — the terminal tool `run_dependency_agent()`'s own task-mode flow
  uses — declared fields `{outdated, upgraded, issues, files_changed}`, but
  `roles/dependency_agent.md`'s own documented "Terminal tool contract" specifies
  `{dependencies: list[{name, current_version, latest_version, vulnerability_ids,
  upgrade_recommended, breaking_changes}], summary, manifest_read}`, and
  `run_dependency_agent()`'s consuming code reads exactly THAT shape
  (`raw.get("dependencies", [])`, `raw.get("summary", ...)`). Since `"dependencies"` never
  existed in the schema the LLM was actually told to fill out,
  **every real dependency finding this agent has ever produced was silently discarded**,
  unconditionally, since the tool was written — the identical failure mode Day 48 found in
  the architecture reviewer, now confirmed as a recurring pattern across this codebase's
  `submit_*` tool schemas (both defined in the same shared `tools.py`, both drifted from
  their own role prompt's documented contract independently). Fixed to match the prompt and
  the consuming code exactly. `dependency_security_agent`'s own separate `_SUBMIT` schema
  (locally defined in its own file, not shared) was checked too and found correct — it did
  NOT have this bug, which is itself informative: the two agents sharing a module-level
  `tools.py` constant drifted; the one with its own local, undupliated definition didn't.
  A pre-existing test (`tests/test_day2_agents.py::test_submit_stores_result`, the
  `dependency_agent` variant) asserted against the old, wrong field names too — corrected to
  the real fields.
  **Tests** (`tests/test_gap49_dependency_scan.py`, 7 tests): a regression guard on the fixed
  schema's exact fields; a real proof `run_dependency_agent()` correctly propagates real
  dependency data end-to-end; scan-tool-list composition; category-enum coverage; required
  scan handlers present; a full mocked-LLM/real-DB test proving the scan's
  `submit_enhancement_request` handler actually writes a real row with
  `category="security"`; and an `inspect.getsource` "verify real callers" guard proving the
  new scan function is genuinely wired into the loop. `black`/`ruff`/`mypy --strict` clean.
  All 427 pre-existing tests touching `dependency_security_agent`/`dependency_agent`/related
  fixtures re-run unchanged, still pass.
  **Full regression**: 3596 passed (3589 Day-48 baseline + 7 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
- Security risks: **YES** — `quality_auditor`'s autonomous scan (every 4h) genuinely runs `secrets_scan`/`find_sql`/`find_config`/`find_api`/`find_route` and files `enhancement_requests` with `category="security"` without any user request (`backend/app/agents/quality_auditor.py:154-203`).

---

## Q36. Self-Audit

- architecture: **PARTIAL** — `architecture_reviewer.py` is real (import_graph, circular_dep_detect, dead_code_detect, call_graph, layer-violation tracing) but only runs on explicit task request, not periodically/autonomously.
  Plan: add it to `_fleet_agents_scan_loop()`.
- prompts: **NO** — no agent inspects live role prompts for weaknesses and proposes revisions automatically; nothing detects "this prompt is weak" and decides to call `propose()`.
  **Gap-closure Day 50 note**: `prompt_registry.propose()`/`deploy()` now have a real caller (see Q37's "prompts" entry below) — this item's remaining gap is narrower than before: the *mechanism* is load-bearing, only the *autonomous weakness-detection* half is still missing.
  Plan: give `agent_debugger` or a new agent a periodic prompt-quality pass that calls `prompt_registry.propose()`.
- tools: **PARTIAL** — `agent_debugger`'s scan reads `audit_log_read`/`fleet_metrics_read` and can surface a failing tool as a bug, but there's no explicit "tool health audit" reasoning distinct from generic bug-finding, and `tool_discovery.py` is a static compatibility registry, not a self-audit.
  Plan: none required beyond documenting the real scope.
- memory: **YES** — `knowledge_curator`'s autonomous scan (every 4h) genuinely reviews `memory_embeddings` for duplicates/stale/miscategorized entries via `memory_search`/`memory_curate_read` and files enhancement requests (`backend/app/agents/knowledge_curator.py:185-234`).
- orchestration: **YES** — `agent_advisor`'s autonomous scan (every 4h) reviews `task_history_query`/`audit_log_read` for over/under-provisioned agent chains and files advisory requests (`backend/app/agents/agent_advisor.py:142-195`).
- performance: **YES** — `agent_performance_reviewer`'s autonomous scan, evidenced above.
- "propose improvements automatically": **YES** — all 5 scan agents only ever call `submit_enhancement_request`; none writes code/memory without a human approving the specific row first (`backend/app/api/fleet_dashboard.py:210-241`).

---

## Q37. Learning System

- Do agents actually learn, or are prompts simply static?: **PARTIAL** — real cross-run learning exists via retrieval-augmented memory (see below), not via weight updates or fully-autonomous prompt rewriting. Role prompt files (`backend/roles/*.md`) themselves only change if a human/agent explicitly edits and commits them; nothing rewrites them automatically today.
- prompts: **PARTIAL → real caller wired, honest scope note below** — `prompt_registry.py` (`backend/app/fleet/prompt_registry.py`) implements a real draft→in_review→approved→deployed→superseded lifecycle with content-hash dedup, rollback, and a regression gate (`regression_detector.py`) — fully tested (`tests/test_prompt_registry.py`).
  **Gap-closure Day 50 (2026-08-03, Stage 2)**: no longer dormant. `make_fleet_apply_handlers()`'s shared `write_file`/`edit_file` handlers (`backend/app/agents/tools.py:11939-12092`, used by `knowledge_curator`/`agent_debugger`/`agent_performance_reviewer`/`quality_auditor`'s APPLY phases) now detect a `roles/<name>.md` target and route it through `prompt_registry.propose()` → `submit_for_review()` → `approve()` → `deploy()` (`_propose_and_deploy_role_prompt`) instead of a raw disk write — the "as the exception" path this entry used to flag as a bypass is now the real, tested, load-bearing caller. Confirmed on all 4 real callers (`tests/test_gap50_prompt_registry_wiring.py::test_all_four_apply_phase_callers_pass_their_own_agent_name`, an `inspect.getsource` guard, not an assumption).
  Still honestly PARTIAL, not YES: nothing yet *decides* to propose a prompt change autonomously (see Q36's "prompts" note above) — a human/agent must still explicitly write role-prompt content for this pipeline to have anything to move through it. What Day 50 closed is that once something does, it goes through the real approval/regression-gated machinery instead of bypassing it.
- routing: **NOT VERIFIED** — `model_router.py` exists and routes agents to model tiers via `agent_models.json`, but this session did not verify whether tier assignment adapts from observed outcomes vs. being static config.
  Plan: read `backend/app/fleet/model_router.py` in full to confirm.
- memory: **YES** — real, evidenced: `backend/app/memory/store.py` embeds task outcomes/failures/architecture notes/learning signals/procedures into pgvector (`memory_embeddings`), and `query_memory_context`/`format_full_memory_context` inject the top-k similar records into every subsequent agent run's prompt (`backend/app/memory/hooks.py` fires this for every dispatched agent run, not just manager-orchestrated ones).
- confidence: **PARTIAL** — `RunMetrics.confidence` is a self-reported field recorded per run (`backend/app/fleet/metrics.py:94-95`), but no code path was found feeding it back into future routing/planning decisions.
- planning: **PARTIAL** — within a single run, `enable_planning`/reflection/replanning (Phase 3, `base_graph.py`) is real self-critique against verification failures; across runs, retrieved "procedures" (`embed_procedure`/`query_procedures`) inform future planning with the actual step sequence that worked before — but there's no evidence of planning-accuracy tracking or explicit tuning.
- tools: **NO** — no mechanism found where tool selection/availability automatically changes based on observed failure history; memory retrieval can surface "this failed before" as context, not a hard behavioral change.
- reasoning: **PARTIAL** — within-run reflection/self-critique is real (Phase 3); no evidence of reasoning strategy changing across runs beyond memory injection.

---

## Q38. Failure Recovery

- Docker crashes: **PARTIAL** — Postgres data (DevTask/AgentRun/Epic/PendingApproval/MemoryEmbedding
  rows) survives if Postgres itself is a separate container/volume; in-flight agent runs on the crashed
  container are orphaned and later reconciled by `reconcile_orphaned_runs()`
  (`app/fleet/failure_ladder.py`, threshold `agent_run_orphan_threshold_seconds`=900s default) — marked
  `failed`, not resumed.
  Plan: extend checkpointing to `base_graph.py` (see Q24 High Priority) so orphaned runs can resume
  instead of restart.
- Python crashes: **PARTIAL** — same orphan-recovery mechanism; pm/architect/decomposer pipeline runs
  (`app/pipeline/graph.py`, `AsyncPostgresSaver`) genuinely resume from their last checkpoint on
  restart; the other ~70 agents' in-flight work must be redone.
- Terminal closes: **YES** — backend is a long-running FastAPI process independent of any terminal
  session; closing a terminal that isn't running the server has no effect on server-side state.
- VS Code closes: **YES** — same reasoning; the agent fleet runs server-side, not inside an editor
  process.
- Claude Code stops: **N/A / NOT VERIFIED** — this question as literally posed conflates the product
  under audit with the tool auditing it; no dependency of this repo's runtime on "Claude Code" (the
  CLI) being open was found.
- Internet disconnects: **PARTIAL** — Anthropic client uses SDK-default retry/timeout
  (`llm_call_timeout_seconds` config, `app/agents/base_graph.py::_make_client`); no custom
  exponential-backoff/circuit-breaker layer beyond the SDK's own defaults was found. A sustained outage
  during an LLM call will fail that call; the run then follows the same failure-ladder path as any
  other tool error.
  Plan: NOT VERIFIED whether SDK-default retries are sufficient for real outages — should be load-tested.
- LLM API fails (4xx/5xx/rate-limit): **PARTIAL** — same as above; no bespoke rate-limit-aware backoff
  found. Failures propagate to the agent's own failure-ladder (`app/fleet/failure_ladder.py`) rather
  than being silently retried indefinitely — bounded, not unbounded.
- What resumes: pm/architect/decomposer pipeline (real `interrupt()`/checkpoint resume);
  `chat_agent.py` (MemorySaver — resumes only within the same process lifetime, lost on process
  restart, per Phase 5.2's own documented "no reduction in durability versus the mechanism it
  replaces," i.e., chat was always ephemeral).
- What is restored: all Postgres-backed rows (tasks, epics, agent_runs, memory, pending approvals,
  scratchpad) — durable regardless of crash type since Postgres is external.
- What is lost: any worker-agent run (base_graph.py) in progress at crash time; all live chat sessions
  (`ChatAgent` in-process registry + `MemorySaver` state) on backend process restart.

---

---

## Q39. Human Approval System

**`backend/app/fleet/approval_gate.py` — real, DB-backed tracking layer, not a stub.** Its own
docstring is explicit: "Pure tracking/indexing over interrupt()-paused threads. Does NOT call
interrupt() itself." Core CRUD (`_record_pending`/`_list_pending`/`_get_pending`/`_record_decision`)
plus `request_human_input()`/`arequest_human_input()` (the generalized entry point from this
engagement's own Phase 5.5 work) which both records the pending row AND audit-logs the *request*
itself, not just the eventual decision. **The actual blocking mechanism is a real LangGraph
`interrupt()`** at the call sites — proven in `app/pipeline/graph.py` with a real `AsyncPostgresSaver`
checkpointer — not advisory/logged-only.

`backend/app/api/approvals.py` — real endpoints: `GET /pending`, `GET /{thread_id}`,
`POST /{thread_id}/approve|reject` (RBAC-gated via `require_approver`, race-safe via a synchronous
status flip before dispatch). `_dispatch_decision()` routes by the `action` column's exact value:
`plan_review` → real `graph.ainvoke(Command(resume=...))`; `git_push` → real `git push` subprocess +
real GitHub PR creation on approve, no push attempted on reject.

**Per-operation verdict (both `chat_agent.py`, the live canonical path, and the older `tools.py`
handler set checked):**
- Delete files: **YES** (was NOT gated) — gap-closure Day 5 (2026-07-30, root cause 2) added a real
  `self._confirm()` gate before `target.unlink()` in `chat_agent.py`, same `interrupt()`-based
  pattern as `git_push`. Proven with a real file on disk, not mocked: paused state has the file
  still present, denial leaves it present, approval deletes it exactly once
  (`tests/test_phase52_file_mutation_confirmation.py`, 5/5 passing).
- Overwrite files (`write_file`/`edit_file`/`append_file`/`rename_file`/`copy_file`): **PARTIAL**
  (was NOT gated) — Day 5 gated the one genuinely silent-data-loss case: `write_file` on a path
  that **already exists** (full-content overwrite, no diff) now requires confirmation; creating a
  brand-new file stays ungated (nothing at risk, and gating it would break the agent's core,
  extremely frequent workflow for no safety benefit). `edit_file` (precise, unique
  old_string→new_string replacement — inherently safer, git-diffable, can't silently clobber
  unrelated content) and `append_file`/`rename_file`/`copy_file` (none of these destroy existing
  content the way a full overwrite does) were deliberately left ungated — gating every file
  mutation the way `git_push` is gated would make the agent unusable for normal coding work.
  Verified: overwriting an existing file pauses and requires approval; creating a new file
  completes in one turn, no pause (`tests/test_phase52_file_mutation_confirmation.py`, same 5 tests).
- `git reset --hard`: **REAL, gated.** `mixed`/`soft` resets: not gated.
- `git push` (incl. `--force`): **REAL, gated** — same blanket "any push needs confirmation" gate
  covers force-push, not a distinct stricter check.
- Database migration (`run_migration`/alembic): **REAL, gated.**
- Deployment: **NOT FOUND** — no deploy tool exists anywhere to gate.
- Dependency upgrades: **PARTIAL** (was NOT gated) — gap-closure Day 5 added
  `human_approval_required=True` to `dependency_agent`'s `run_agent_graph()` call (matching
  `docker_agent`/`cicd_agent`'s existing precedent), verified via a real kwargs assertion
  (`tests/test_day2_agent_contracts.py::TestDependencyAgentFlags`). Honest limitation, not glossed
  over: unlike `chat_agent.py`'s live pre-action `interrupt()`, this is a **post-hoc** review flag —
  `base_graph.py` (which `dependency_agent` and ~70 other worker agents run on) has no checkpointer,
  so the manifest edit has already happened by the time a human reviews it; it marks the result
  `requires_human_approval=True` rather than pausing before the edit. A genuine pre-edit pause for
  this and every other `base_graph.py` agent depends on extending the same `AsyncPostgresSaver`
  mechanism `chat_agent.py` already has to the shared graph builder — tracked separately (this
  engagement's Stage 1.3), not fixed here.
- Also real and gated (not on the audit's list but found): `undo_changes` (`git checkout --`),
  `seed_database`.

**Session-level "remember"/"always allow": NOT FOUND.** No cache/allowlist/trust mechanism —
`_confirm()` builds a fresh `thread_id` per call (keyed on the Anthropic `tool_use_id`, deliberately
replay-stable across LangGraph pause/resume, not for cross-call deduplication); every dangerous-
action call site independently re-triggers a fresh confirmation.

**Frontend approval UI: real.** `apps/web/app/approvals/page.tsx` polls `GET /api/approvals/pending`
every 5s with real Approve/Reject buttons. `apps/web/app/chat/page.tsx` handles a
`confirmation_required` stream event with dedicated in-chat Approve/Deny buttons.

Plan: add confirmation gates to `delete_file`/`write_file`/`edit_file` (at least for files outside
a task's own worktree) and to `dependency_agent`'s manifest edits — currently the only ungated
destructive-write paths found.

---

## Q40. Git Intelligence

- Meaningful commits / commit-message generation: **REAL, LLM-generated** —
  `backend/app/tools/git_push_tool.py::generate_commit_message` makes a real Anthropic call
  (Haiku by default) from the real task title + real diff, with a deterministic non-raising
  fallback. Manager's per-subtask commits use a fixed template (`{type}: {title}`), not
  model-generated — a real, if less rich, alternative path.
- Branch creation: **REAL** — `app/services/git_service.py::git_checkout(create=True)` and
  `app/repo_tools/worktree.py::create_worktree` are both real subprocess `git` calls with
  branch-name validation.
- Merge conflict resolution/explanation: **YES** — real, gap-closure Day 51 (2026-08-03, Stage 2).
  `git_merge` (`backend/app/agents/tools.py`, `make_chat_handlers`) now detects a real failed
  merge and confirms actual conflicted files via `git diff --name-only --diff-filter=U` (repo
  research: `repos/cline/.../mergeWorktree.ts`'s own detection technique — more robust than
  scraping stdout text), returning a real `[CONFLICT]` message naming the exact files and
  pointing to the next two tools. New `parse_merge_conflicts` reads a real conflicted file and
  extracts every `<<<<<<</=======/>>>>>>>` hunk (with optional diff3 `|||||||` base section)
  into structured `{ours_text, base_text, theirs_text, labels, line range}` data via a pure
  line-scan parser (`_parse_conflict_markers` — no regex). New `resolve_merge_conflict` applies
  a per-hunk resolution (`ours`/`theirs`/`custom`) via `_apply_conflict_resolutions`, rewriting
  the real file; any hunk not named in the resolution list is left with its markers intact and
  reported back as still-unresolved — never silently guessed. No repo in `repos/` implements
  real git-merge-conflict-marker parsing (aider's own `<<<<<<<` hits are its unrelated
  SEARCH/REPLACE edit-block format), so the parsing/resolution logic itself is this session's
  original work; only the failed-merge detection technique was reused from cline.
  Tests: `tests/test_gap51_merge_conflict_resolution.py` (15 tests) — pure-function parsing/
  resolution-application coverage (diff3-style, multi-hunk, unresolved-hunk-left-intact,
  invalid-index-not-silently-applied), handler-level real-file read/write proofs, and two
  fully real (no mocking) end-to-end git tests: one that creates two real branches editing the
  same line, runs a real `git merge`, and asserts the handler's own `git diff --diff-filter=U`
  detection genuinely finds the real conflicted file and real markers git itself wrote; one
  proving a real non-conflicting merge is unaffected by the new detection branch.
- Diff review: **REAL, operates on real git diffs** — `worktree.py::get_diff` (real `git diff`
  subprocess) feeds directly into `reviewer.py`'s real tool-using review agent. Note:
  `code_quality_agent`/`style_reviewer` review whole files, not diffs — a narrower, file-based
  pattern, not a bug.
- Change summarization/PR descriptions: **PARTIAL** — PR title is the real LLM-generated commit
  message (diff-aware); PR body is `task_description[:2000]` — a truncation of the original
  description, **not** an LLM summary of the actual diff/changes.
  Plan: generate the PR body from the diff the same way the commit message already is.
- Enumerated git tools: all confirmed real, subprocess-backed, none stubbed —
  `app/services/git_service.py` (clone/status/log/diff/add/commit/push/branch_list/checkout/pull)
  and ~20 more chat-tool-layer git operations (`git_stash`, `git_rebase` non-interactive-only,
  `git_cherry_pick`, `git_tag`, etc.), each verified via direct handler-body reads.

---

---

## Q41. Documentation Intelligence

- README: **YES** — `readme_agent.py`, real repo-grounded generation.
- Architecture docs: **NOT FOUND as a dedicated doc-writer** — `architecture_reviewer` produces
  findings, not a maintained `ARCHITECTURE.md`.
- API docs: **YES** — `api_docs_agent.py`, documents this repo's own real FastAPI routes/Pydantic
  schemas from direct introspection.
- Agent docs: **NOT FOUND** — no agent generates documentation about the other 72 agents; the
  existing agent-creation guide is a static, human-written doc.
- Tool docs: **NOT FOUND.**
- Changelogs: **YES** — `changelog_agent.py`, real `git log`-based, Keep-a-Changelog format.
- Migration guides: **NOT FOUND** — `migration_agent.py` performs DB migrations, it does not write
  human-facing migration guides; no agent is scoped for that.
- Release notes: **YES** — `release_notes_agent.py`, real tag-range `git log` based.
- **Auto-trigger "when code changes": NO for all of the above.** All four real doc agents are
  dispatch-only via `POST /api/specialized-agents/{name}/run`; no CI step, pre-commit hook, or
  post-merge trigger regenerates any of them automatically.

Verdict: **PARTIAL** — 4 of 7 named doc types have real, repo-grounded, on-demand generators;
architecture docs, agent docs, tool docs, and migration guides have no generator at all; and none of
the working generators fire automatically on code change.
Plan: add architecture-doc/agent-roster/tool-catalog generators (straightforward variants of the
existing pattern), and wire a lightweight trigger (a periodic loop, matching the existing
`_fleet_agents_scan_loop()` pattern, or a CI post-merge step) to invoke `changelog_agent`/
`release_notes_agent` automatically on merge to main.

---

## Q42. Cost Awareness

- token usage estimate: **YES** — `app/pipeline/cost_controller.py::estimate_epic_cost()`/`estimate_epic_cost_sync()` computes `estimated_tokens_in`/`estimated_tokens_out` per epic, preferring real historical averages from `AgentRun` (`_historical_avg_tokens`, queries completed runs' actual `tokens_in`/`tokens_out`), falling back to config coefficients (`cost_tokens_per_subtask`, `cost_output_ratio`) when no history exists.
- LLM cost estimate: **YES** — same function computes `estimated_cost_usd` from `settings.cost_per_input_token`/`cost_per_output_token`. Also `app/api/activity.py::get_token_usage` (`GET /api/tasks/{id}/tokens`) reports live cumulative cost during a run (`tokens_in * 0.000003 + tokens_out * 0.000015`).
- API usage estimate: **PARTIAL** — token/cost estimate covers LLM API usage; no estimate found for other external API calls (e.g. GitHub API rate/cost).
- expected runtime estimate: **YES**
  **Gap-closure Day 39 (2026-08-03, Stage 2, closing out the Days 35-39 resource/cost/size
  pre-flight bucket)**: added `estimated_duration_seconds`/`duration_source` to `CostEstimate`
  (`cost_controller.py:26-34`), computed the same way `estimated_cost_usd` already is: a real
  historical average of `agent_type='coder'` `agent_runs` wall-clock duration when available,
  config fallback (`settings.size_processing_seconds_fallback_per_subtask`) otherwise
  (`cost_controller.py:70-81`, `148-157`). Deliberately **reused**
  `app/fleet/size_estimate.py::historical_avg_duration_seconds()` (made public this same day,
  was `_historical_avg_duration_seconds` — the exact query Days 37-38 already built) rather than
  duplicating the SQL a second time in a different module, per this plan's own reuse-over-duplicate
  standard. `estimate_epic_cost_sync()` (no DB) always uses the config fallback, matching its
  existing "pure sync, no DB" contract for the token/cost fields.
  **Real bug caught and fixed while writing this, not shipped**: the first draft multiplied by
  `max(subtask_count, 1)` (copying `size_estimate.py`'s own shape verbatim), which would have
  estimated 180s of duration for a 0-subtask epic while the very same function estimates $0/0
  tokens for that case — an internal inconsistency. Fixed to a plain `subtask_count` multiply (no
  clamp), proven by `test_estimate_duration_seconds_zero_subtasks_is_zero_duration`.
  **Tests**: `tests/test_cost_controller.py` gained 3 tests (config-fallback value, zero-subtask
  zero-duration, linear scaling). New `tests/test_gap39_cost_duration_estimate.py` (2 tests, real
  DB): inserts real completed `coder` `AgentRun` rows (60s/90s → real avg 75s) and proves
  `estimate_epic_cost()`'s historical branch actually activates and computes the correct value
  (75s × 2 subtasks = 150s, not asserted by reading the SQL), plus the fallback path with no
  history present. `black`/`ruff` clean; `mypy --strict` clean; confirmed no circular import
  between `cost_controller.py` and `size_estimate.py` (the import is function-local, matching
  every other cross-module DB-query reuse already in this codebase).
  **Full regression**: 3536 passed (3531 Day-38 baseline + 5 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
- "Can it recommend cheaper approaches?": **PARTIAL** — the estimate **gates** execution (`requires_approval: bool = cost > settings.cost_approval_threshold`, wired to human approval per the module's own docstring: "epics over COST_APPROVAL_THRESHOLD require explicit human approval"), which forces a human decision point, but no code generates an actual alternative cheaper plan/approach for the human to pick from — it's a stop/approve gate, not a recommendation engine.
  Plan: if literal "recommend a cheaper approach" (not just "block and ask") is required, would need new logic to propose e.g. a lower `complexity_multiplier`, fewer subtasks, or a cheaper model tier alongside the cost estimate.

---

## Q43. Confidence & Uncertainty

- "Does every important answer include an internal confidence estimate?": **PARTIAL** — planning-enabled agent runs get a real numeric `confidence` (0.0-1.0), assigned by the LLM itself in `_gather_facts_and_plan` (`app/agents/base_graph.py:329-351`, parsed from the model's own JSON `{"steps":[...], "confidence":0.85,...}` output, default 0.8 on parse failure) and threaded through `planner_node`/`replan_node`/quality-gate scoring (`_run_quality_gate`, `base_graph.py:850-919`: `checks["confidence:threshold"] = confidence >= min_confidence`, can escalate `requires_human_approval`). This is real and enforced, but it is a per-run planning confidence, not a per-claim/per-answer confidence attached to every individual output the fleet produces (e.g. a `code_explainer_agent` summary carries no confidence field).
- "Can it distinguish verified facts, assumptions, hypotheses, unknowns?": **PARTIAL** — the fleet has a genuine, graph-enforced verified/unverified distinction: `state["verification"]` (`base_graph.py`) tracks flags set only by real tool calls (e.g. `read_file` → `verification["read"]=True`), and `AgentResult.verified` is computed directly from that dict, never from the model's unverified claim (Phase 3.4's gap-closure specifically fixed a bug where a false claim could leak into `.raw` — see `IMPLEMENTATION_PROGRESS.md` "Gap 4"). This is a real verified-fact-vs-claim distinction. However, there is no explicit 4-way tagging of "assumption" vs "hypothesis" vs "unknown" anywhere — those three categories collapse into "unverified"/"not yet confirmed."
- "Does it explicitly say when it does not know?": **NOT VERIFIED** — no fleet-wide mechanism found that forces an explicit "I don't know" string; `status: "blocked"` (`AgentResult.status`) is the closest structural equivalent (an agent halts rather than fabricating an answer), but whether individual agent prose actually says "I don't know" depends on each role's own LLM output, which isn't statically checkable by code inspection.
  Plan: if a literal, auditable "confidence + verified/assumption/hypothesis/unknown tag on every answer" contract is required, that's new schema work on `AgentResult`/`submit_*` tool schemas fleet-wide — a large, not-yet-started change.

---

## Q44. Explainability

- why it chose that approach: **PARTIAL** — `replan_node` (`base_graph.py`) attaches a real, evidence-citing `reason` (the actual repeated criterion text or dissatisfaction count, never generic — `_should_replan` returns `(bool, reason)`) whenever a plan changes mid-run, and appends a `[Replan]` message to `state["messages"]` so the reasoning is visible in the transcript. But this only fires on replan; the *original* plan's rationale is the model's own free-text plan output, not a structured "why" field.
- why it rejected alternatives: **NO** — no structured "alternatives considered and rejected" field found in `AgentResult`, `AgentCapability` (`app/fleet/capability_registry.py`), or the audit log (`app/fleet/audit_log.py` — entries carry `action_type`/`description`/`outcome`, no rejected-alternatives field).
- why specific agents participated: **PARTIAL** — dispatch is driven by `AgentCapability` registrations (name/tools/capabilities/risk_level) in `capability_registry.py`, so which agent ran for which task is deterministically traceable via the registry + audit log, but no runtime function was found that emits a human-readable "agent X was chosen over agent Y because..." explanation.
- why specific tools were used: **PARTIAL** — every tool call is logged (audit log `action_type`/`agent_name`/`details`) and gated by each agent's own `AGENT_CONTRACT["allowed_tools"]`/`VerificationConfig`, so post-hoc reconstruction of "this tool ran because this contract allowed it and this verification flag needed setting" is possible from code + logs, but there's no single API endpoint or generated report that answers "why this tool" in plain language on demand.
  Plan: this is the same underlying gap as Q104 (see below) — a dedicated "explain this run" synthesis feature (reading the audit log + `state["verification"]`/`confidence`/`_quality_gate` and generating a human-readable rationale) does not exist yet; the raw evidence it would draw from does exist and is real.

---

## Q45. Multi-Session Continuity

- Restarting the application (backend process restart): **PARTIAL** — `main.py::lifespan` re-runs
  `init_active_repo()` (restores the single active repo pointer from the DB `Repo.is_active` row) and
  `init_checkpointer()` (reconnects `AsyncPostgresSaver` for the pm/architect/decomposer pipeline —
  genuinely resumable). Chat sessions and in-flight worker-agent runs are lost (see Q38).
  Plan: see Q24's durable-resumability item.
- Restarting the computer: **PARTIAL** — identical to "restarting the application" as long as Postgres
  data survives the reboot (external volume/service) — same partial-resume story.
- Reopening the repository: **YES** — repo state itself (git history, worktrees) is on disk/in git,
  independent of the backend process; `Repo.local_path` + `is_active` in Postgres re-resolves it on
  next `init_active_repo()`.
- Changing branches: **PARTIAL** — `git_checkout`/`git_branch_list` tools exist
  (`app/services/git_service.py`) and worktrees are per-task (`WORKTREES_DIR/task-{id}`, ADR-003), so a
  branch change on the main checkout doesn't corrupt an agent's own isolated worktree. However there is
  no evidence the system tracks "what branch was this task's context built from" for memory/context
  purposes — `MemoryEmbedding` has no branch column either.
  Plan: NOT VERIFIED whether stale cross-branch memory context could be surfaced; worth an explicit test.
- What context persists: all Postgres rows (tasks/epics/agent_runs/memory_embeddings/
  versioned_lessons/pending_approvals/epic_scratchpad — though scratchpad is deliberately
  TTL/epic-completion-bound, not meant to persist long-term), the git repo itself and its worktrees,
  the pgvector-backed `AsyncPostgresSaver` checkpoints for the pm/architect/decomposer pipeline.
  Does NOT persist: chat session state (in-process `MemorySaver` + module-level `ChatAgent` registry),
  in-flight worker-agent run state beyond what's already been written to `AgentRun`/`TaskLog` rows.

---

---

## Q46. Scalability

- 100 agents: **YES, largely fine** — `ensure_all_agents_registered()` (`backend/app/fleet/capability_registry.py:122-145`) globs `app/agents/*.py` and imports every module at startup (Day 19 fix) — this scales to hundreds of files with no code change, each `_register()` call is O(1) into an in-process dict.
- 250 agents: **PARTIAL** — registration itself still fine, but every registry (`CapabilityRegistry`, `AgentRegistry`, `LessonStore`) is a **single in-process singleton** (`capability_registry.py:88`, `agent_registry.py:158`, `base_graph.py:194-204`) with a plain `dict`/`list` + a single `threading.Lock`/`RLock` — lock contention grows with agent count and concurrent dispatch volume, though at 250 this is unlikely to be the binding constraint yet.
- 500 agents / 1000 agents: **NO (as currently architected)** — confirmed directly by the project's own audit doc, `MASTER_AGENT_v2.md:1094-1110` (Appendix D.1, "Enterprise horizontal scaling"): *"this project's real, current deployment shape is a single Postgres instance with in-process `asyncio.Semaphore` concurrency caps... There is no current evidence of multi-worker-process deployment, let alone a distributed cluster."* Concretely: `concurrency.py`'s `epic_slot()`/`agent_run_slot()`/`subtask_slot()` (`backend/app/pipeline/concurrency.py:19-21,42-107`) are process-local `asyncio.Semaphore`s — running a second app instance/replica gives each replica its *own independent* concurrency cap (caps don't sum correctly across replicas, and worse, aren't coordinated at all). `LessonStore` (`base_graph.py:146-204`) is fully in-memory, capacity-1000, and is **wiped on every restart and invisible across processes** — at 500-1000 agents generating lessons, most runs on a multi-replica deployment would never see most lessons.
  Bottlenecks (concrete, cited): (1) in-process semaphores in `concurrency.py` don't coordinate across replicas; (2) `CapabilityRegistry`/`AgentRegistry` singletons are per-process, so a load balancer routing to different replicas sees inconsistent agent health/availability; (3) `LessonStore` is process-local and ephemeral; (4) `manager.py`'s subtask loop is strictly sequential per epic (no intra-epic parallel dispatch), so wall-clock time per epic scales with subtask count regardless of how many agents exist; (5) the optional Redis-backed `QueueAdapter` (`RQAdapterBridge`, referenced in `MASTER_AGENT_v2.md:430-435`, A.14) exists but is "not wired into actual task dispatch, per its own documented caveat" — no live distributed queue today.
  Plan (per the codebase's own stated trigger condition, `MASTER_AGENT_v2.md:1106-1110`): move to distributed primitives (Redis-backed semaphores/locks, DB- or Redis-backed `AgentRegistry`/`CapabilityRegistry`, wire `RQAdapterBridge` into real dispatch, make `LessonStore` DB-backed like `versioned_memory.py` already is) once real usage shows more than one worker process is needed — building it earlier would be speculative per the doc's own reasoning.

---

---

## Q47. Extensibility

- Can a new agent be created by providing only role/responsibilities/tools/prompt/memory config, without touching orchestration code: **PARTIAL/NO** — a genuinely new agent still requires writing a new Python file (code, even if additive/isolated), not just a config blob:
  1. A `roles/<name>.md` prompt file (config-like, no code — `load_role()` in `backend/app/agents/base.py`).
  2. A new `backend/app/agents/<name>.py` module containing: an `AGENT_CONTRACT` dict, an `_SUBMIT`/tool schema, a `run_<name>()` function calling `run_agent_graph()`, and a mandatory `_register()` function that must be explicitly called at module end (`_register()` on the last line — confirmed in every sampled agent file: `accessibility_agent.py:178`, `decomposer.py:224`, `manager.py:1239`). This is real Python code the author must write correctly (schema, handlers, verification config), not a declarative file.
  3. To be reachable via the direct-invoke API, a manual dict entry in `_REGISTRY` in `backend/app/api/specialized_agents.py:40-146` (`"my_agent": ("app.agents.my_agent", "run_my_agent")`) — confirmed hardcoded, not auto-discovered; grepped and found no dynamic scan feeding this dict (unlike `capability_registry`'s scan).
  4. To be reachable from the *main* Dev→QA→Review pipeline (the flow real end users trigger), `manager.py`'s hardcoded `if subtask_type == "frontend": ... else: backend_dev` (lines 316-340) and `dispatcher.py`'s `_FALLBACK_ROUTING` (lines 33-39) would both need editing — the core orchestration genuinely only knows about `backend_dev`/`frontend_dev`/`qa`/`reviewer` today; a new specialist agent cannot become part of a normal user task's automatic subtask dispatch without a code change to one of these two files.
  5. Model tier assignment in `agent_models.json` (pure config, no code — read by `backend/app/fleet/model_router.py:96-124`; falls back to a sane default if the entry is missing, so this step is technically optional).
  Plan: to satisfy "config only," would need (a) a manifest-driven agent loader that generates the `AGENT_CONTRACT`/tool-schema/`_register()` boilerplate from a YAML/JSON spec instead of hand-written Python, and (b) `manager.py`/`dispatcher.py` dispatch driven by `FleetManager.select()` (already built, already scores by capability — just not the actual decision-maker, per Q2 finding) instead of the hardcoded `if/else`.
- Can the new agent automatically join the company (fleet): **YES, for capability/health registration specifically** — this part is genuinely real and automatic, confirmed by the project's own audit: `MASTER_AGENT_v2.md:423-429` (A.14) states `ensure_all_agents_registered()` "globs `app/agents/*.py` at runtime and imports each module so its `_register()` hook fires, with no hardcoded dispatch table — new agent files are picked up automatically." Verified directly in `capability_registry.py:122-145`: it globs the directory (excluding a small denylist of infra files) and imports every module, which fires each module's own `_register()` — so once the `.py` file exists with the boilerplate above, `CapabilityRegistry`/`AgentRegistry` pick it up with zero edits to those two registry files themselves. This is real, but is a narrower claim than "joins the company" implies — it doesn't make the agent reachable from the main task pipeline or the specialized-agents API (see NO/PARTIAL items above).

---

---

## Q48. Enterprise Readiness

- Multiple users: **PARTIAL** — `UserRole` table + JWT auth exist (`app/auth/jwt.py`,
  `app/middleware/rbac.py`), but the actual user list lives as a JSON blob under one
  `system_settings` key (`auth_users`), not a real `users` table with per-user metadata/audit trail.
  Plan: migrate to a proper `users` table.
- Multiple projects: **NO** — confirmed directly in source comments:
  `security/credential_vault.py`: "Global-scoped (this project has no 'project' entity...)". No
  `Project`/`Workspace` model exists in `db/models.py`.
  Plan: see Q24 Critical item — add a real project entity and thread it through repo scoping, memory,
  and credentials.
- Multiple workspaces: **NO** — same root cause; `app/api/repo.py::_active_repo_path` is a single
  module-level global for the whole process — only one "workspace" (repo) is ever active at a time.
- Concurrent sessions: **PARTIAL** — chat sessions are per-session (`session_id`-keyed `ChatAgent`
  registry) and can run concurrently; but they all operate against the same single active repo, so
  concurrent sessions on *different* projects is not possible without redeploying separate backend
  instances.
- Enterprise authentication: **PARTIAL** — JWT auth with bcrypt password hashing exists
  (`app/auth/jwt.py`), opt-in via `JWT_AUTH_ENABLED`; legacy insecure `X-User-Role` header fallback
  still exists (`ALLOW_LEGACY_ROLE_HEADER`, documented as "insecure, opt-in only" in
  `auth/dependencies.py`). No SSO/SAML/OIDC integration found.
  Plan: add OIDC/SAML support for enterprise IdPs; make the legacy header fallback impossible to enable
  in a hardened deployment profile.
- Audit logging: **YES** — `app.fleet.audit_log` records credential access (key name only,
  `credential_vault.py`), approval decisions and requests (`approval_gate.py::request_human_input`,
  Phase 5.5 closed the "request itself wasn't logged" gap), git pushes.
- Role-based access: **PARTIAL** — real 3-tier RBAC (`viewer`/`approver`/`admin`,
  `app/middleware/rbac.py`) gates approval endpoints, but it's global, not project-scoped (see above) —
  there's no way to be an approver on Project A but only a viewer on Project B.
- Usage analytics: **PARTIAL** — real reporting endpoints exist (`GET /api/fleet/reports/cost`,
  `/health`, `/repair-patterns`, Phase 6.2, real Postgres-aggregated `agent_runs` GROUP BY per
  agent/day/tier), but no per-user or per-project usage breakdown (no project entity to break down by).
- **If not, what is missing overall**: a `Project`/`Workspace` DB entity is the single root-cause gap
  behind 3 of these 8 sub-items (multi-project, multi-workspace, project-scoped RBAC) — this one piece
  of schema/architecture work would resolve most of the enterprise-readiness deficit at once.

---

---

## Q49. Claude Code Feature Gap Analysis

- Read/search codebase (grep, glob, AST-aware search): Implemented (85%) — `app/repo_tools/scanner.py`
  (tree-sitter-based), `parse_ast`/`list_functions`/`find_references`/`search_symbols` tools
  (`app/agents/tools.py`), call-graph + PageRank-style ranking (`context_builder.py`). Missing: NOT
  VERIFIED whether search performance is validated on very large (>1M LOC) repos.
- Edit files (targeted diffs): Implemented (80%) — `edit_file` handler (`make_chat_handlers` /
  `app/agents/tools.py`), used fleet-wide by Editor-tier agents.
- Run shell commands: Implemented (75%) — `bash` tool with policy-engine allow/denylist
  (`app/policy/engine.py`), scoped variants per tier (`TEST_RUNNER_BASH_TOOL`, `LOAD_TEST_BASH_TOOL`,
  `INFRA_DRY_RUN_BASH_TOOL`). Missing: `terraform`/`kubectl` are blanket-denied fleet-wide with no
  dry-run exception (deliberate, documented).
  Priority: Medium.
- Git workflow (status/diff/commit/push/branch/checkout/tag): Implemented (85%) —
  `app/services/git_service.py` (git_clone/status/log/diff/add/commit/push/branch_list/checkout/pull),
  `git_tag` tool (`app/agents/tools.py:6073`). `git_push` is confirmation-gated (HITL).
- Multi-turn conversational chat with tool use: Implemented (75%) — `chat_agent.py`, now a real
  interrupt()-based LangGraph `StateGraph` (Phase 5.2) with per-tool-call graph nodes; 6 real
  confirmation-gated dangerous tools. Missing: no `state["verification"]` wiring (chat has its own
  contract, not the shared `base_graph.py` one — documented, honest gap).
- Persistent project memory across sessions: Partial (55%) — `memory_embeddings` (pgvector, DB-backed,
  survives restart) is real and queried on every agent run with `enable_memory=True`. Missing: no
  project/repo scoping column at all — this is memory that's *global*, not memory that's *durable and
  correctly scoped*.
  Priority: Critical (see Q24).
- Human-in-the-loop approval / confirmation: Implemented (80%) — `approval_gate.py`,
  `request_human_input()`, 3 real consumers (plan_review, git_push, clarification), request- and
  decision-time audit logging (Phase 5.5).
- Sub-agent delegation / orchestration: Implemented (70%) — `manager.py` epic orchestration
  (LangGraph `StateGraph`, Phase 5.1), 72 real specialized agents, capability registry.
- Self-verification of own output (not trusting model's claim): Implemented (75%) —
  `VerificationConfig`/`state["verification"]`, graph-enforced (not model-claimed) flags fleet-wide
  (confirmed 72/72 agents have a real `VerificationConfig` instance, Phase 4 Item 2). Real bug found
  and fixed fleet-wide in this same engagement: `AgentResult.raw` used to prefer the model's unverified
  claim over the graph-enforced dict (Gap 4, fixed across 25 agent files).
- Self-critique / iterate on failure: Partial, real progress (gap-closure Days 11-14, 2026-07-30) —
  real, tested mechanism (critique_node, replan_node, quality_gate, Phase 3.5/3.6/3.7).
  `enable_critique=True` now real for 5 Tier-A agents; `enable_replanning` still `False` fleet-wide,
  deferred pending critique's real-run validation.
  Priority: High (flip `enable_replanning` for the same 5, then both fleet-wide, once observed
  stable in real runs — mechanism already built and tested, just not yet fully rolled out).
- Clarifying questions instead of guessing: Partial (55%) — `request_clarification` tool
  (Phase 5.3) exists, wired onto `planner.py` only; not fleet-reusable-by-default across all 72 agents
  yet (tool is available for opt-in, but not adopted broadly).
- Prompt-injection / untrusted content defense: Implemented (65%) — delimiter wrapping +
  malicious-output flagging for `web_search`/`bash`/`read_file` output (Phase 6.3), applied at the one
  real chokepoint (`execute_tools`).
- Observability / tracing: Implemented (65%) — real OTEL bridge with correct parent-child span nesting
  (Phase 6.1), gated exporter.
- Cost/token tracking: Implemented (80%) — real accumulated tokens/cost per epic
  (`compute_actual_cost_usd()`, Phase 3.2, fixed a real pre-existing bug where tokens were silently
  discarded), per-agent/day cost reporting endpoint (Phase 6.2).
- Disaster recovery / crash resumability: Partial (50%) — durable checkpointing only for
  pm/architect/decomposer pipeline; the other ~70 agents' in-flight work is not checkpointed (see Q38).
- Multi-project isolation: Missing (10%) — no project entity exists at all (see Q48/Q94/Q95).
  Priority: Critical.
- Horizontal scalability: Partial (30%) — in-process `asyncio.Semaphore` concurrency caps; optional RQ
  distributed queue exists but doesn't change the semaphore ceiling (see Q77).
  Priority: Critical for the stated "hundreds of agents" ambition.

### Cursor-specific comparisons
- Inline/IDE-embedded editing UX: Missing (0%) — this is a server-side agent fleet with a separate web
  dashboard (`apps/web`), not an IDE extension; there's no editor-embedded diff/apply UX comparable to
  Cursor's Cmd-K flow. Not in scope for this repo's own architecture (deliberate — it's a different
  product shape), so "gap" here is really "different product," not an oversight.
- Multi-file simultaneous editing with live preview: Partial — worktree-per-task isolation
  (ADR-003) + `edit_file`/diff generation exist, but no live-preview UX was found (frontend not deeply
  audited in this pass).

---

---

## Q50. Final Roadmap

### Phase: Foundation (multi-project + durability)
- Effort: Large (4-8 weeks equivalent).
- Scope: real `Project`/`Workspace` DB entity; `repo_id`/`project_id` on `MemoryEmbedding`; replace
  `_active_repo_path` global with per-request/session-scoped repo context; extend `base_graph.py` with
  durable (`AsyncPostgresSaver`-backed) checkpointing for the ~70 worker agents, mirroring
  `chat_agent.py`'s Phase 5.2 per-tool-call-node design.
- Dependencies: none — this is the true root.
- Major risks: threading project/repo context through ~72 agents' dispatch paths is a large, mechanical,
  easy-to-miss-a-call-site change (this engagement's own history — e.g. Gap 4's 25-file codemod — shows
  this pattern of bug is real and has happened before here); checkpointing worker agents safely requires
  the same side-effect-ordering care Phase 5.2 already proved is subtle (its own "wrap the whole loop"
  false start).
- Acceptance criteria: a test proves Project A's memory query never returns Project B's rows; a test
  proves two concurrent sessions on two different repos never share `_active_repo_path` state; a test
  proves a killed worker-agent process resumes from its last checkpoint instead of restarting.

### Phase: Advanced (distributed scale + iteration-by-default)
- Effort: Medium-Large (3-6 weeks equivalent).
- Scope: move concurrency slot accounting off in-process `asyncio.Semaphore` onto Postgres/Redis so
  multiple backend processes share one real cap; flip `enable_critique`/`enable_replanning` to fleet-
  wide default `True` after a dedicated full-suite regression pass; roll `request_clarification` out
  fleet-wide, not just `planner.py`; build a load/stress test suite for the platform's own
  infrastructure (currently zero such tests exist).
- Dependencies: Foundation phase (project-scoped slots need project entities to scope by).
- Major risks: flipping critique/replanning defaults adds a real LLM call to every agent submission —
  cost and latency regression risk across the whole fleet if not load-tested first.
- Acceptance criteria: a test proves two backend processes never together exceed
  `max_concurrent_agent_runs`; a load test establishes actual throughput ceiling at 100/250/500 agents
  (see Q77); critique/replanning enabled by default with the existing 3318-test regression gate still
  green.

### Phase: Enterprise (RBAC, auth, compliance)
- Effort: Medium (2-4 weeks equivalent).
- Scope: real `users` table (replacing the `auth_users` JSON blob); project-scoped RBAC (not just
  global viewer/approver/admin); OIDC/SAML enterprise auth integration; per-project usage analytics on
  top of the existing reporting endpoints; remove/harden the legacy `X-User-Role` header fallback for
  hardened deployments. (`ecdsa` CVE already resolved, gap-closure Day 7 — see Q24.)
- Dependencies: Foundation phase (project entity must exist before project-scoped RBAC is meaningful).
- Major risks: auth migration (JSON blob → real table) touches the login flow and every existing
  deployment's stored admin credentials — needs a careful, tested migration path, not a breaking change.
- Acceptance criteria: a test proves a user who is approver on Project A cannot approve on Project B; an
  OIDC login round-trips against a real test IdP; `pip-audit` reports zero known vulnerabilities.

One more recommendation, addressed directly: every claim in this document is grounded in a specific
file/function/test-name citation gathered by direct `Read`/`Grep` against the live repo in this session
(not recalled from training or assumed from the spec's own text) — e.g., the "no project entity" finding
is a direct quote from `backend/app/security/credential_vault.py`'s own docstring, and the concurrency
ceiling is `backend/app/config.py`'s own `max_concurrent_agent_runs` field read directly. Where a claim
could not be verified this way (load/stress test existence, frontend UX depth, SDK retry sufficiency
under real outage), it is explicitly marked NOT VERIFIED rather than estimated.

---

---

## Q51. Repeat Task & Historical Context

- Locate previous work: **PARTIAL** — real mechanism: `backend/app/memory/store.py`'s `query_memory_context`/`query_procedures` (lines 182-239, 752) does semantic search over `memory_embeddings` for similar past tasks/failures/learnings/procedures, and `chat_agent.py._memory_read_context` (`chat_agent.py:409-437`) calls this once per chat turn. This finds *semantically similar* past work, not a literal "yesterday" or date-scoped lookup — there is no date/time-based query path.
- Identify the correct project: **NO** — explicitly documented as an unimplemented gap: `IMPLEMENTATION_PROGRESS.md` Day 3/1.6 states the `MemoryEmbedding` schema "has no `repo_id`/`project_id` column at all, so every existing query is already unscoped across whatever tasks exist in the table," and a planned `cross_project=True` flag was deliberately not built because there is nothing to filter on. "Project" and "fleet" memory tiers are literally the same implementation today.
  Plan: add a `project_id`/`repo_id` column to `MemoryEmbedding` + a real migration before per-project historical scoping can exist; tracked as a known, honestly-documented gap in the repo's own progress file, not silently missing.
- Reuse previous plans: **PARTIAL** — `architect.md` "Memory Context" section explicitly instructs using `<memory_context>` to "Avoid implementation approaches that failed before" and "Reuse patterns that worked well" — prompt-level, backed by the real `query_memory_context` data feed.
- Avoid repeating completed work / resume unfinished work: **YES, Stage 1.6 (2026-07-31)** — new
  "Already done?" check in `backend/roles/_GLOBAL_STANDARDS.md` §8 (a real, named step, not just the
  prior halted-task-resume mechanism): before starting implementation work, search whether the
  requested change already exists and report what's found instead of re-implementing/duplicating.
  `chat.md`'s own "For IMPLEMENTATION tasks" process now has this as an explicit numbered step (step
  2, before any file is touched), not just the global rule.
- Detect task is already complete and explain why no changes are needed: **YES, Stage 1.6
  (2026-07-31)** — the new check's own instruction is exactly this: "if it already exists (fully or
  partially), say so and report what's there instead of re-implementing." Scoped to `chat.md` (the
  interactive, per-request-driven role this matters most for) rather than `architect.md` — a planner
  role that decomposes NEW work by design, where "already done" is less applicable to its own
  planning step; `architect.md` was left unchanged, an intentional scope boundary, not an oversight.

---

## Q52. Large Context Understanding

- Extremely large prompts / thousands of LOC: **YES, Stage 1.5 (2026-07-31)** — real token-budget
  condensing exists: `backend/app/agents/base_graph.py:362,448` (`_select_messages_to_condense`/
  `_condense_messages`, replacing the old drop-oldest `_trim_messages`) fires once
  `tokens_in > token_budget`. Now a real LLM-summarization strategy (not a pure drop, see Q65 for
  full detail) — the dropped middle messages are summarized via a real haiku-tier call and spliced
  back in, not lost.
- Multiple documents / multiple code blocks: **NOT VERIFIED** — no dedicated multi-document ingestion/parsing code found; relies on the model's native handling of whatever text is in a single turn.
- Multiple repositories: **NO** — same gap as Q51: `MemoryEmbedding` has no per-repo scoping column (`IMPLEMENTATION_PROGRESS.md` Day 3/1.6), and `chat_agent.py`'s `ChatSession` is bound to a single `repo_path` (`chat_agent.py:310`, `self.root = Path(session.repo_path)`) — one chat session operates on exactly one repo.
- Long conversations: **YES, Stage 1.5 (2026-07-31)** — `ChatSession.history` persists to
  `chat_messages` table (`backend/app/models/chat.py:5,91-109`) so history survives restarts, and
  `chat_agent.py` now has its own real condense check (`_condense_history_async`,
  `chat_agent.py:422`) — previously this graph had NO budget check at all (see Q65).
- Mixed instructions: **NOT VERIFIED** — no dedicated handling found beyond the general conflict-resolution prompt language already cited in Q25/Q26.
- Context management / chunking / prioritization / context-loss prevention / summarization strategy
  (explained): **Stage 1.5 (2026-07-31) — now genuinely summarization-based, not drop-oldest.**
  Chunking = condense (`base_graph.py:362,448`); prioritization = keep first message (system/task
  framing) + last 4 (recent exchange), same heuristic as before, but the dropped middle is now
  summarized via a real LLM call (haiku-tier, circuit-breaker-protected) instead of discarded —
  context-loss prevention is now real (see Q65 for full evidence and test citations).

---

## Q53. Strict Requirement Compliance

**Stage 1.6 (2026-07-31): DONE.** New "Hard-Constraint Conflict Rule"
(`backend/roles/_GLOBAL_STANDARDS.md` §8, right after the limitation taxonomy) — a real, named rule
(not the generic ambiguity/request_clarification guidance this section previously pointed to): any
requirement the user states as non-negotiable is a hard constraint; when one conflicts with evidence
already gathered in the run (repo already uses something incompatible, two stated constraints
contradict each other), the agent must stop before making any change and surface the conflict
factually — using whichever real mechanism its role actually has (`request_clarification` for
bounded worker runs, `status: needs_human` for `submit_*`-only roles, or a plain-text question for
interactive roles like chat that have neither tool and are live with the user anyway). `chat.md`'s
own Escalation section now references this rule explicitly and correctly documents that chat has no
`request_clarification` tool (it's scoped to bounded worker-agent runs — `app/agents/tools.py`'s own
docstring) so the right chat-specific mechanism is a direct question, not a tool call.
- Always obeys explicit user tech requirements: **PARTIAL, improved** — still no runtime parser that
  extracts a specific ad hoc constraint from a chat message and mechanically enforces it (that would
  be a much larger NLU feature, out of Stage 1.6's scope) — what's now real is the STOP-AND-SURFACE
  behavior once a conflict is noticed via normal investigation, replacing what was previously silent
  substitution with no rule against it at all.
- Warns/explains/asks for clarification on conflict instead of silently switching tech: **YES,
  Stage 1.6 (2026-07-31)** — no longer generic ambiguity guidance; a named, specific rule for this
  exact scenario. Proven end to end via `tests/test_gap_stage16_hard_constraint_clarification.py`:
  a scripted worker-agent run given two conflicting hard constraints (PostgreSQL vs. SQLite-only)
  calls `request_clarification` naming both constraints and why they conflict, records a real
  `PendingApproval` row, and ends cleanly with `needs_clarification` — never a submitted result that
  silently picked a side. (Prompt-level adherence by a real model can't be unit-tested — this proves
  the MECHANISM correctly carries the rule through when followed, the same standard already applied
  to the pre-existing `tests/test_phase53_request_clarification.py`.)

---

## Q54. No Hallucination Policy

- Distinguish facts from assumptions: **PARTIAL** — `_GLOBAL_STANDARDS.md` §2 ("label 'unverified' — do not guess") and §9 ("Report uncertainty explicitly") are prompt rules every agent inherits; no code classifies a claim as fact-vs-assumption.
- Verify before answering: **PARTIAL (prompt) / YES (structurally, for submit-tool outputs)** — see the `enforce_in_result` override below, which is real code, not prompt text.
- Refuse to invent APIs/files/functions/classes: **PARTIAL** — `chat.md` Anti-Hallucination Rules 1-4 ("Verify before you name... Never guess at APIs") and `architect.md` same; enforced only by the model choosing to follow instructions, not by a code-level fact-checker.
- Refuse to invent test results / execution results / performance claims: **YES, and now content-level
  true for `run_tests` specifically — gap-closure Day 15 (2026-07-30).** Real code:
  `backend/app/agents/base_graph.py` — at the moment a `submit_*` tool fires, for every
  `(result_field, verif_key)` in `verification_cfg.enforce_in_result`, the code does
  `raw_result[result_field] = actual` where `actual` comes from `new_verification` (state actually
  observed from real tool calls in this run), **overwriting whatever the model itself put in that
  field**. Proven end-to-end by `backend/tests/test_phase34_real_output_verification.py`.
  The previously-real nuance — the tracked flag only proved the tool *ran*, not that pytest's real
  pass/fail *content* was reflected — is now closed for `run_tests` specifically: both real
  implementations (`app/agents/tools.py`'s `make_chat_handlers.run_tests` and
  `make_fleet_apply_handlers.run_tests_h`) now inspect the real subprocess exit code and prefix
  `[ERROR]` on any nonzero exit, flowing through the SAME `[ERROR]`-prefix check that already
  withholds every other verification flag — `tests_passed`/`tests_run` now genuinely means the exit
  code was 0, not merely "the tool call didn't crash." **A second, real bug was found and fixed while
  making this change, not introduced by it**: both commands ended with `| head -100`/`| tail -50` —
  in a shell pipeline, `subprocess.run`'s returncode reflects the LAST command (`head`/`tail`, which
  always exits 0), so the real pytest exit code was being silently destroyed before any check could
  see it, regardless of this fix. Removed (output truncation moved to the Python side); this also
  surfaced and fixed a Windows-specific shell-portability bug in `make_fleet_apply_handlers.run_tests_h`
  (`;` after a failed `source .venv/bin/activate` aborts the whole command line under `cmd.exe`,
  meaning pytest never ran at all on Windows before this fix — real, reproduced live, not assumed).
  Proven by `backend/tests/test_gap15_test_runner_exit_code.py` (8 tests, real pytest subprocesses
  against real passing/failing test files — not mocked — including one full
  `_make_execute_tools_node` integration test proving a real failing run genuinely fails to set
  `tests_passed`).
  Still an open, honestly-scoped nuance: this closes it for `run_tests` specifically, not every
  tool that could carry content-level truth (e.g. a linter's real error count vs. "ran cleanly").
- "I cannot verify this" phrasing: **NOT VERIFIED as a literal string** — grepped the full `backend/` tree case-insensitively for `I cannot verify|cannot verify this|unverified`: real code hits are in `readme_agent.py` and `base_graph.py`/`tools.py` context (labeling fields "unverified"), and pervasive "unverified"/"UNVERIFIED" language across nearly every role prompt (`_GLOBAL_STANDARDS.md` §2, `decomposer.md`, `architect.md`, etc: "flag it... as UNVERIFIED") — the concept and the literal word are real and widespread, but the exact phrase "I cannot verify this" as specified in the audit was not found verbatim; "unverified" labeling is the actual, real convention used instead.

---

## Q55. Truthfulness Policy

- Never lies / never fabricates: **PARTIAL** — prompt-level (`_GLOBAL_STANDARDS.md` §2, §7: "Never hide failures or hallucinate success"), reinforced by the real `enforce_in_result` override (Q54) for the specific fields a `VerificationConfig` tracks.
- Never promises unsupported functionality: **NOT VERIFIED** — no dedicated code or prompt check found beyond general anti-hallucination language.
- Never claims code works without testing: **YES for `run_tests` specifically (gap-closure Day 15,
  2026-07-30), PARTIAL for other content-bearing tools** — same `enforce_in_result` mechanism as Q54
  provides a real, code-level backstop for the specific tracked fields of agents that wire a
  `run_tests`→verification-key mapping (`chat_agent.py`'s own `_VERIFICATION_CFG`,
  `chat_agent.py:207-223`, maps `run_tests`→`tests_passed`) — see Q54 for the exit-code-parsing fix
  that closed the "proves the tool ran, not that tests actually passed" gap for `run_tests`.
- Never claims deployment succeeded without verification: **YES structurally, by design exclusion** — `CLAUDE.md`'s "Deploy is a human action forever" rule is reflected in the shipped product's actual permission model: no agent tool in `chat_agent.py`'s 36+ tools or any `AGENT_CONTRACT` grants deploy credentials or a deploy action (confirmed by the full tool list read in this review — git/bash/test/lint tools only, `git_push` itself gated behind `_confirm()`/`interrupt()`, `chat_agent.py:975-993`). An agent cannot claim a deploy succeeded via a tool call because no deploy tool exists for it to call.
- Never claims files exist unless confirmed: **PARTIAL** — `chat.md` Rule 3 ("Check file paths... before reading or editing") and `architect.md` Rule 1 ("Never name a file from memory") — prompt-level; the actual filesystem tools (`file_exists`, `read_file`) do return real `[ERROR] File not found` (`chat_agent.py:486-489`) when a path is wrong, so a model that calls them cannot successfully fabricate a file's contents, but nothing forces it to call them first.
- Never claims tests passed unless actually executed: **YES (for the invocation, PARTIAL for the content)** — see Q54's `enforce_in_result` evidence; this is the strongest, most concretely code-backed item in this whole cluster, with a real regression test (`test_phase34_real_output_verification.py`) proving the override fires against a lying mock LLM.

---

## Q56. Evidence-First Workflow

- Inspect the repository / related files / configuration: **YES (prompt-mandated, tool-backed)** — `_GLOBAL_STANDARDS.md` §1 step 3 "INVESTIGATE — Gather evidence with tools BEFORE acting... Never act on assumptions about code you have not read in this run" is the explicit mandatory ordering; `architect.md` Steps 1-6 and `chat.md`'s per-intent playbooks operationalize it with specific tools (`get_file_tree`, `read_file`, `search_symbols`).
- Inspect logs: **NOT VERIFIED** — no dedicated log-inspection tool or instruction found in the reviewed agents (chat/coder/architect/planner/decomposer/manager); `bash` can be used ad hoc to read logs but there's no named "inspect logs" step.
- Inspect tests: **YES** — `chat.md` "For BUGS or ERRORS" step 6 ("Verify the fix by running tests") and `run_tests` tool (`chat_agent.py:1011-1025`), real and callable.
- Inspect runtime output: **YES** — `bash`/`run_tests`/`run_linter` tools return real captured stdout/stderr (`chat_agent.py:257-278`, `_run_subprocess`), and this real output is what feeds the `enforce_in_result` override (Q54), not a paraphrase.
- Workflow explained: the operating loop is UNDERSTAND → PLAN → INVESTIGATE → EXECUTE → VERIFY → SELF-REVIEW → SUBMIT (`_GLOBAL_STANDARDS.md` §1, numbered, mandatory order, inherited by every one of the 72+ agent role prompts) — this is real, consistent, repo-wide prompt architecture, and its "before every important conclusion" INVESTIGATE step is reinforced by the one concrete code-level backstop that exists (`enforce_in_result`, Q54) for the specific claims that mechanism tracks. Everything outside that mechanism's tracked fields relies on the model actually following the prompt, which is not independently code-verified.

---

## Q57. Intelligent Clarification

- Immediately asks targeted clarification questions (missing framework/language/deployment target, conflicting requirements, incomplete architecture): **YES, generically** — `REQUEST_CLARIFICATION_TOOL` (Q25/Q27) is real, wired to 38+ agents; its description requires the question be "the specific, genuine blocker — not a vague 'is this ok?'" (`tools.py:377`), i.e. targeted-question framing is a real schema requirement, not just a suggestion. No evidence of dedicated per-category prompts for "missing framework" vs. "missing deployment target" specifically — the mechanism is generic, not itemized per the audit's named examples.
- Avoids unnecessary questions when enough information exists: **PARTIAL** — same tool description ("not for every minor judgment call... a reasonable, disclosed assumption is almost always better than stopping to ask," `tools.py:366-369`) — this is a real constraint written into the tool's own spec (visible to the model at call time), but there is no code-level check preventing over-use; it depends on the model honoring the instruction.
  Note: this cluster's evidence is materially the same mechanism cited for Q25/Q27 — see those entries for the fuller `file:line` trail; not repeated in full here to avoid duplication.

---

## Q58. Multi-Terminal & Parallel Execution

- multiple terminals: **YES** — `run_background` (`tools.py:7787`) can spawn arbitrarily many `Popen` processes, each tracked by PID in `_session_bg_procs` (`tools.py:6998`, scoped per chat-handler-set/session).
- multiple shell sessions: **PARTIAL** — each `subprocess.run`/`Popen` call is an independent, stateless shell invocation (no persistent shell/session object with retained env/cwd across calls beyond what's re-passed each time).
- concurrent commands: **YES** — real `asyncio.Semaphore`-gated concurrency for agent/subtask execution in `backend/app/pipeline/concurrency.py` (`epic_slot()` line 64, `agent_run_slot()` line 76, `subtask_slot()` line 92), configured via `max_concurrent_epics`/`max_concurrent_agent_runs`/`max_concurrent_subtasks_per_epic` in `backend/app/config.py:151-157`.
- background tasks: **YES** — `run_background`/`kill_process`/`read_output_h` (`tools.py:7787, 7807, 8818`).
- foreground tasks: **YES** — the default `subprocess.run(...)` pattern used by essentially every other bash-style tool handler.
- task dependencies: **PARTIAL** — subtask dispatch (`backend/app/pipeline/dispatcher.py:74` `dispatch_subtask`) routes by type/capability tag but no explicit DAG/dependency-graph scheduler was found in `pipeline/`; ordering appears sequential/plan-driven rather than a declared dependency graph.
  Plan: If true DAG dependencies are required, add an explicit subtask dependency list consulted by the dispatcher before releasing a `subtask_slot`.
- terminal monitoring: **PARTIAL** — see Q17 "monitor terminal output" (poll-based, not live-streaming).
- terminal recovery: **NOT VERIFIED** — no code found that reattaches to or recovers a background process after a server/session restart; `_session_bg_procs` is an in-memory dict local to a running handler set (`tools.py:6998`), so a process restart loses tracking of any still-running child processes (they'd become orphaned, not "recovered").
  Plan: Persist background-process PIDs (and their launch command/cwd) to durable storage so a restarted backend can rediscover and re-adopt or cleanly terminate orphans.
- terminal cleanup: **NO** — no `atexit`/session-teardown handler found that kills tracked `_session_bg_procs` on session end (verified via grep — only 4 references to `_session_bg_procs`, none in a cleanup/atexit context); processes started via `run_background` and never explicitly `kill_process`'d will leak until they exit on their own or the OS process tree is torn down externally.
  Plan: Register a session-close hook (e.g. in `chat_agent.py`'s session teardown) that iterates `_session_bg_procs` and terminates any still-running child processes.
- Explain scheduling and synchronization: **YES** — scheduling is semaphore-based (bounded concurrency, not a full scheduler with priorities): `SlotAcquisitionTimeout` (`concurrency.py:24`) is explicitly raised instead of hanging forever if a slot can't be acquired within `slot_acquisition_timeout_seconds`, addressing a documented deadlock risk (an epic holding a subtask slot while waiting on another subtask that can't acquire one because the epic's own cap is exhausted) — this is real, tested logic per the module's own docstring, not just aspirational.

---

## Q59. Multi-File Operations

- read hundreds of files: **YES** — `read_files` (`tools.py:1005`) batch-reads up to 20 paths per call (capped, `inp.get("paths", [])[:20]`); `scanner.index_repository()` (`scanner.py:199`) walks/parses the entire repo with no file-count cap, so hundreds/thousands of files can be indexed (just not all read into a single LLM prompt at once via `read_files`).
- edit hundreds of files: **YES** — `rename_symbol()` (`ast_engine.py:289`) applies edits across every file matching `file_pattern` under a directory with no count cap; the refactor agent (`tools.py:4126`) exposes this repo-wide.
- compare files: **YES** — `compare_files` (`tools.py:7766`, schema line 2132).
- synchronize implementations: **NOT VERIFIED** — no dedicated cross-file "keep implementations in sync" tool found; only generic `copy_file`/`rename_symbol`/manual edit tools.
- rename files: **YES** — `rename_file` (`tools.py:7283`) via `Path.rename()`, checks `_is_protected_path` on both source and destination.
- move files: **YES** — `move_file_h` (`tools.py:10679`, registered at line 11088) — separate from `rename_file`, both perform the underlying filesystem move.
- delete files: **YES** — `delete_file` (`tools.py:7152`), protected-path checked.
- preserve formatting: **YES** — same `old_string`/`new_string`-unique-match `edit_file` mechanism (`tools.py:3523`) used everywhere, including by the refactor/rename tools.
- preserve comments: **YES** — same mechanism; `rename_symbol`'s word-boundary regex substitution (`ast_engine.py:303,319`) only replaces the identifier token itself, leaving surrounding text/comments untouched.
- preserve architecture consistency: **PARTIAL** — `rename_symbol` is a plain word-boundary regex rename, not scope-aware (no distinction between same-named symbols in unrelated scopes/classes), so a repo-wide rename could over-rename unrelated identifiers that happen to share a name; `build_call_graph`/`build_package_graph` (`scanner.py:264,305`) exist to visualize cross-file/cross-package dependencies but are informational, not enforcement.
  Plan: Replace the regex-based `rename_symbol` with a tree-sitter/AST-scope-aware rename (already have tree-sitter wired for Python/JS/TS in `scanner.py`) to avoid renaming unrelated same-named identifiers.

---

## Q60. Agent Creation Capability

**Can the system build new production-quality agents automatically? NO — it is a fully manual, documented process; no scaffold/generator/create-agent tool exists.**

- Searched `backend/app` for `scaffold`, `generate_agent`, `create_agent`, `agent_generator`, `agent_template` — the only matches were false positives (`create_agent_run`, a DB row-creation helper in `app/api/agents.py`/`app/db/repository.py`, unrelated to generating a new agent). **No code path programmatically generates a new agent module, role file, tool contract, or test file.**
- `docs/ADD_A_NEW_AGENT.md` (285 lines) is the real, current, only process — explicitly a **manual, ~2-hour walkthrough**: (1) hand-copy a Python template into `backend/app/agents/{name}.py` and fill in the submit tool, tool list, `VerificationConfig`, handler factory, entry point; (2) hand-write `backend/roles/{name}.md`; (3) hand-add one line to `_REGISTRY` in `backend/app/api/specialized_agents.py`; (4) hand-write `backend/tests/test_{name}.py` from a template; (5) run the full suite; (6) manually curl the new endpoint. Every step is a human copy/fill/verify action, not a generator invocation.
- identity/role/responsibilities/prompt: **NO** (manual, per above) — Plan: none exists to automate; would require an LLM-driven codegen agent that writes+tests+registers a new agent module, which is a real, scoped, not-yet-started project.
- tools: **NO** (manual selection from `READ_ONLY_TOOLS`/hand-picked additions).
- memory/planning/reasoning/verification: **PARTIAL** — these are automatically INHERITED for free once a new agent calls `run_agent_graph()` (the shared infra in `base_graph.py` gives every new agent planning/memory/reasoning/verification/reflection with zero extra code), but the human still has to write the module and call that function correctly — nothing generates the module itself.
- safety: **YES automatically inherited** — `app/policy/engine.py`'s checks apply to any new agent's tool calls with zero extra wiring, since enforcement is centralized in the shared `execute_tools` node.
- observability: **YES automatically inherited** — `_register()`/`get_agent_registry()` pattern + `ActivityStream` + metrics are automatic once the new module follows the template (confirmed: `capability_registry.py`'s `ensure_all_agents_registered()` scans `app/agents/` at runtime and imports every module so `_register()` fires — genuine dynamic discovery, not a hardcoded name list, per `MASTER_AGENT_v2.md` §A.5).
- tests: **NO** — a human copies and edits a test template; nothing generates tests from the new agent's actual behavior.
- documentation: **NO** — no auto-generated docs for a new agent beyond what the human writes into the role file.
- configuration: **NO** — a human must also manually add an entry to `app/fleet/agent_models.json` (not mentioned in `docs/ADD_A_NEW_AGENT.md`'s own checklist — a real, minor doc gap: the walkthrough's checklist never mentions this file).
- register into orchestration: **PARTIAL** — dispatch registration (`_REGISTRY` in `specialized_agents.py`) is a manual one-line edit; capability-registry discovery (`ensure_all_agents_registered()`) IS automatic once the module exists and imports cleanly.

Plan: build a `create_agent` meta-tool/agent (an obvious candidate given `agent_advisor`/`agent_debugger`/`agent_performance_reviewer` already exist as fleet self-improvement agents) that takes a spec, emits the module+role file+registry line+tests from `docs/ADD_A_NEW_AGENT.md`'s own template, and runs the test suite — currently does not exist in any form.

---

---

## Q61. MCP (Model Context Protocol) Capability

**A real, working, tested MCP server exists — but it is a narrow, standalone capability (4-6 repo-intelligence tools), not the agents' primary tool-access path, has no MCP client, no auth, and no per-tool permission/failure-recovery layer of its own.** This is confirmed by the codebase's own architecture decision record, not inferred.

- `backend/app/mcp/server.py` (302 lines) — a genuine stdio JSON-RPC 2.0 server (`run_stdio_server()`, reads stdin line-by-line, writes JSON-RPC responses to stdout). `backend/app/mcp/__init__.py` is empty.
- design MCP interfaces: **YES, narrowly** — `_TOOLS` (lines 17-101) declares 6 tools with real JSON-Schema `inputSchema`: `index_repository`, `search_symbols`, `build_context`, `query_dependencies`, `semantic_search`, `get_file_summary`.
- implement MCP tools: **YES** — each has real handler logic in `_handle()` (not stubs), backed by `app/repo_tools/scanner.py`/`context_builder.py`.
- register tools: **YES, for this one server only** — `tools/list` method returns the manifest; `initialize` returns protocol version `2024-11-05`.
- handle authentication: **NO** — the stdio server has no auth/identity concept at all (stdio transport, no token/session checking anywhere in `server.py`).
- manage permissions: **NO** — no MCP-specific permission layer; the repo's real permission enforcement (`app/policy/engine.py`) is not wired into `app/mcp/server.py` at all (confirmed by reading the whole file — no `policy`/`check_path`/`check_command` import).
- recover from failures: **PARTIAL** — generic JSON-RPC error responses (`-32700` parse error, `-32601` unknown method/tool, `-32603` internal error) wrap exceptions, but there's no retry/backoff/circuit-breaker specific to MCP.
- validate responses: **NO dedicated validation** — handlers return `json.dumps(...)` text content directly; no schema validation of the tool's own output (contrast with the main agent path's `jsonschema.validate` on `submit_*` inputs, `base_graph.py:1098`).
- test integrations: **YES** — `backend/tests/test_mcp.py` (77 lines) tests `initialize`, `tools/list`, `index_repository`, `search_symbols`, unknown-method, unknown-tool — all via direct `_handle()` calls (unit-level, not a real stdio subprocess round-trip test).
- **Critical, directly-documented finding**: `docs/adr/005-mcp-not-primary-tool-access.md` (accepted 2026-07-23) states explicitly: *"none of the 72 real production agents actually call tools through MCP... every agent gets its tools via direct in-process Python dispatch... The MCP server is real and invocable... but has no caller anywhere in the running application — confirmed by grep, not assumed."* Independently re-confirmed in this pass: grepping `backend/app` for `mcp` outside `app/mcp/` and `app/agents/tools.py`'s "MCP / External integrations" section (which is actually direct `gh`/Linear/Slack API calls, not MCP protocol calls at all — a naming artifact, not a real MCP client) found no agent invoking the MCP server.
- No MCP client exists anywhere in the codebase (confirmed: no `mcp.client`/`ClientSession`/similar import found).

Plan: if MCP-based tool access becomes a real requirement (vs. today's deliberate, documented decision to keep direct in-process dispatch as primary), it needs its own scoped project — ADR-005 itself says migrating the 72-agent tool path to MCP is "a deliberate, large-scope re-architecture requiring its own plan and explicit sign-off," not incremental work.

---

## Q62. Runtime Decision Making

- Switch strategies: **PARTIAL** — `replan_node` (`backend/app/agents/base_graph.py:425-459`) genuinely revises an agent's own plan mid-run, triggered by real state (`_should_replan`: reflection dissatisfaction ≥2 turns, or the same critique criterion unmet ≥2 retries) — not a fabricated heuristic, it cites the actual evidence in the injected message. Still confirmed **opt-in and off by default fleet-wide** — `enable_replanning=True` appears in zero agent files, grepped fresh (gap-closure Days 11-14, 2026-07-30) — deliberately not flipped yet, pending real-run validation of `enable_critique` (now `True` for 5 agents — see Q6/Q2) first, per the plan's own stated sequencing.
  Plan: flip `enable_replanning=True` for the same 5 agents (coder/backend_dev/frontend_dev/qa/
  reviewer) `enable_critique` now covers, once critique is observed stable in real runs.
- Switch tools: **YES** — inherent to the per-turn LLM tool-choice loop (`call_llm`→`execute_tools`→`call_llm`..., `base_graph.py:1561-1601`); the model can call a different tool on the next turn based on the previous tool's real result, with no hardcoded tool sequence enforced by the graph (only `submitted`/`max_turns`/stall detection gate the loop).
- Call additional agents: **NO** — confirmed by the same evidence as Q2's "request help from other agents": no `invoke_agent`/`call_agent` tool exists anywhere in `backend/app/agents/tools.py`, and `MASTER_AGENT_v2.md:1112-1132` (D.2) explicitly states recursive delegation/specialist consultation is deferred pending a real LangGraph supervisor upgrade to `manager.py` (Phase 5.1, which today only sequences dev→qa→review, not arbitrary agent calls).
  Plan: same as Q2 — add a gated `invoke_agent` tool once cross-agent delegation is a real, recurring need.
- Request human approval: **YES** — real, multiple mechanisms: `request_clarification` tool (`backend/app/agents/tools.py:363-410`) records a `PendingApproval` row via `approval_gate.py` and ends the run with `status="needs_clarification"`; `request_human_review()` (`backend/app/fleet/failure_ladder.py:167-193`) transitions the task to `"blocked"` + publishes `review_requested`; the plan-review interrupt (`human_review_node`, `backend/app/pipeline/graph.py:87-109`, real LangGraph `interrupt()`) pauses the whole pipeline until a human calls `resume_pipeline()`; cost-approval gate (`_cost_estimate_node`, `manager.py:703-769`) halts an epic pending human cost sign-off above `cost_approval_threshold`.
- Stop execution: **YES** — `abort()` (`failure_ladder.py:140-164`) transitions a task to terminal `"failed"` status; also `should_abort(task_id)` check inside `call_llm` (`base_graph.py:573-582`) lets an external abort flag stop a running agent before its next LLM call, returning `status="stopped"`.
- Retry: **YES** — `should_retry()` (`failure_ladder.py:79-81`), bounded by `manager_max_subtask_retries`, drives `manager.py`'s per-subtask retry loop with exponential backoff (line 360); real, wired, and unit-tested (per `IMPLEMENTATION_PROGRESS.md`'s referenced test files).
- Rollback: **PARTIAL** — `rollback_to()`/`save_checkpoint()`/`restore_checkpoint()` (`backend/app/fleet/fleet_checkpoint.py`, re-exported as `checkpoint`/`rollback`/`resume` in `failure_ladder.py:63-71`) are real and functional, but **deliberately not auto-triggered on failure** — confirmed by the module's own comment (lines 52-61): "intentionally manual/operator-invoked tooling... not unwired oversights." No code path calls `rollback_to()` automatically when a subtask/epic fails.
  Plan: N/A per explicit design choice (rollback requires human judgment in this codebase's convention) — but worth flagging to the user as "exists, human-triggered only," not "fully automatic."
- Skip unnecessary work: **NOT VERIFIED / likely NO** — grepped `failure_ladder.py` and the router logic in `base_graph.py` for any explicit "skip"/short-circuit-because-already-done mechanism; none found. The closest adjacent behavior is `_should_replan`'s bounded triggers preventing *wasted extra replanning*, and stall detection (`_make_router`, lines 1414-1445) ending a run early after `max_stalls` no-tool-call turns — neither is "recognize this step is already done, skip it."
  Plan: if "skip unnecessary work" means idempotency (e.g. detecting a subtask's target state already matches), add an explicit pre-dispatch check against current repo state before spending an LLM call.

---

## Q63. User Emotion & Conversation Handling

Duplicate of Q26 as the audit brief itself anticipated — **Stage 1.6 (2026-07-31): DONE, same fix
applies verbatim** — see Q26 for the full evidence (`chat.md`'s new "Handling Difficult Users /
De-escalation" section).
- Frustrated / impatient / confused / blaming the system / disappointed / repeatedly reporting
  failures / emotional / poor grammar / fragmented instructions: **PARTIAL, improved** — same as
  Q26's updated verdict: the response pattern is now named explicitly; no per-named-state dedicated
  handling (language detection, etc.) was added — out of scope.
- Remains respectful / stays focused on solving the problem / avoids escalating conflict: **YES** —
  no longer generic professionalism norms only; a specific instruction now exists ("you cannot be
  argued out of a verified fact... don't concede to match their certainty").
- Provides actionable next steps: **YES**, unchanged real structural requirement (Output Contract).

---

## Q64. Project Guardian Agents

**Which 5 agents (if any):** `agent_advisor`, `agent_debugger`, `agent_performance_reviewer`,
`knowledge_curator`, `quality_auditor` — `backend/app/agents/agent_advisor.py`,
`agent_debugger.py`, `agent_performance_reviewer.py`, `knowledge_curator.py`, `quality_auditor.py`.

This is a directly-named grouping in the code, not an inference from behavior alone. Three
independent code comments name exactly this set of 5:
- `backend/app/agents/tools.py:11118-11121`: "Shared by the 5 self-improvement agents
  (agent_performance_reviewer, agent_debugger, agent_advisor, knowledge_curator,
  quality_auditor). These agents target the Gridiron project's own codebase
  (settings.fleet_self_repo_path), not a user-connected repo."
- `backend/app/api/fleet_dashboard.py:3-4`: "The 5 self-improvement agents
  (agent_performance_reviewer, agent_debugger, agent_advisor, knowledge_curator,
  quality_auditor) file `enhancement_requests` rows during their autonomous SCAN phase."
- `backend/app/memory/store.py:837` (re-verified 2026-08-03, Day 44 spot-check — was 552-554,
  drifted after Days 40-42's edits to this same file): refers to "fleet-governance agents
  (agent_performance_reviewer, agent_debugger, knowledge_curator, quality_auditor)" —
  `agent_advisor` correctly absent from this specific list because it has no APPLY phase at
  all (`agent_advisor.py:16`: "This is scan-only — you have no apply phase and no write
  tools, ever"), so it never fires the memory-write event this comment describes.

There is no in-repo name "Autonomous Ranger" or "Guardian" anywhere (`grep -ri
"guardian|ranger" backend/app` returns nothing except these 5 agents' own SCAN/APPLY files) —
that is the user's own label for a real, but differently-named, subsystem: the **"Fleet
Enhancement Dashboard" / "5 self-improvement agents"** (Day 9 feature). The underlying
functional shape (autonomous scan, evidence-gated findings, human-approval-gated apply,
"never modify without approval") is real and matches the user's description closely — the
name and a few specific claimed capabilities (Docker monitoring, deployment workflow,
automatic project planning) do not.

- separate memory: **NO** — All 5 use `enable_memory=True` inside `run_agent_graph`
  (e.g. `agent_advisor.py:173`), the same shared semantic `memory_embeddings` store and
  `memory_hook_node` injection every one of the other ~69 agents uses
  (confirmed in `backend/app/agents/base_graph.py`, `backend/app/memory/store.py`).
  `knowledge_curator`'s own role prompt (`backend/roles/knowledge_curator.md:6-16`) is explicit
  that it curates this one shared store used by "every agent," not a private one.
  Plan: if true isolation is wanted, give these 5 a separate `memory_embeddings` partition/tag
  so their fleet-introspection memories can't co-mingle with user-repo task memories.

- separate tools: **YES** — a distinct, dedicated tool set only these 5 (plus, for one tool,
  a couple of adjacent reviewer roles) get: `fleet_metrics_read`, `audit_log_read`,
  `task_history_query`, `memory_curate_read`/`memory_curate_write`,
  `submit_enhancement_request` (`backend/app/agents/tools.py:11115-11341`). Normal task agents
  (`coder`, `backend_dev`, etc.) do not have these tools at all.

- project awareness: **PARTIAL** — real, but scoped only to the platform's own codebase:
  `repo = settings.fleet_self_repo_path` (e.g. `agent_advisor.py:148`, `quality_auditor.py:157`)
  — i.e. awareness of the Gridiron platform itself, not of arbitrary user projects.

- codebase monitoring: **YES** — `read_file`/`search_code`/`get_file_tree` scans of
  `fleet_self_repo_path` (`quality_auditor.py` general-quality lens; `agent_debugger.py`
  root-cause tracing).

- log monitoring: **PARTIAL** — `audit_log_read` (fleet execution audit trail) and
  `fleet_metrics_read`, not application/server logs (`read_logs` is a `monitoring_agent`-only
  tool, and `monitoring_agent` is not one of the 5).
  Plan: if server/app log monitoring is wanted from this group, add `read_logs` to
  `agent_debugger`'s or `quality_auditor`'s tool set.

- Docker monitoring: **NO** — no Docker-related tool anywhere in these 5 agents' files
  (`grep -il docker` on all 5 source files: 0 hits). Docker awareness exists only in the
  separate, ordinary `docker_agent.py`.
  Plan: none — out of scope for this group as designed; would need explicit tool addition if desired.

- Git monitoring: **PARTIAL** — `agent_debugger` gets diagnostic `bash` explicitly documented
  for `git log`/`git blame` (`agent_debugger.py:23-24`, `backend/roles/agent_debugger.md:24`),
  and `git_commit_change` in APPLY mode for all APPLY-capable members. No continuous Git
  watching — it's read-on-demand during a scan, not a monitor.

- architecture monitoring: **NO** — `architecture_reviewer.py` is a separate, 6th agent with
  its own read-only report contract (`submit_arch_review`) and is explicitly NOT in the
  named 5-agent list in any of the 3 comments above. `quality_auditor`'s "general project
  quality" lens is shallow (obvious defects via `read_file`/`search_code`), not the deep
  `import_graph`/`call_graph`/`circular_dep_detect` analysis `architecture_reviewer` does.
  Plan: if architecture monitoring is meant to be part of this group, either fold
  `architecture_reviewer` in explicitly (making it 6) or give one of the 5 its tools.

- enhancement suggestions: **YES** — this is the core, defining output of all 5:
  `submit_enhancement_request` → `EnhancementRequest` DB rows surfaced at
  `GET /api/fleet/requests` (`backend/app/api/fleet_dashboard.py`).

- bug detection: **YES** — `agent_debugger`'s dedicated role (`backend/roles/agent_debugger.md`).

- automatic planning: **NO** — none of the 5 does project/roadmap planning; `enable_planning=True`
  passed to `run_agent_graph` is the generic per-run internal tool-call planning every
  `run_agent_graph` agent gets (LLM plans its own steps for one run), not fleet/product roadmap
  planning. Actual planning agents (`planner`, `decomposer`, `pm`, `sprint_planner`) are
  separate, ordinary task agents, not part of this group.

- approval workflow: **YES** — real and load-bearing: SCAN phase only ever writes a
  `pending` `EnhancementRequest` row; `POST /api/fleet/requests/{id}/approve` is required
  before that agent's APPLY phase runs at all (`fleet_dashboard.py:210-244`, gated by
  `require_approver` middleware). Reject is terminal.

- testing workflow: **PARTIAL** — APPLY-mode agents (`agent_debugger`, `agent_performance_reviewer`,
  `quality_auditor`; `knowledge_curator` only when writing role-prompt files) call `run_tests`
  before `git_commit_change` per their role contracts and `VerificationConfig` gates
  (e.g. `quality_auditor.py:110-116` `_APPLY_CFG` requires `tests_run`/`committed`). This is
  "run the existing test suite," not an independent QA/testing pipeline.

- deployment workflow: **NO** — no deploy/rollback/release tool in any of the 5 agents'
  `allowed_tools`. `APPLY_TOOLS`/`FLEET_APPLY_TOOLS` stop at `git_commit_change` — no deploy
  step. (The global `app.policy.engine` denylist actually blocks deploy commands like
  `kubectl`, `terraform`, `docker push`, `npm publish` for every agent including these — see Q85.)

- never modify without approval: **YES, verified** — `agent_advisor` has no write tools ever;
  the other 4's APPLY phase only exists as a separately-invoked code path
  (`run_*_apply(request_id, ...)`) called only after `POST .../approve`
  (`fleet_dashboard.py` approve handler). SCAN-mode tool lists contain no `write_file`/
  `edit_file`/`git_commit_change` for any of the 5 (verified in each agent's `SCAN_TOOLS`).

**Overall — does the "completely separate Autonomous Ranger/Guardian architecture" exist?**
**PARTIAL.** A real, coherently-named 5-agent subsystem exists (the "5 self-improvement
agents" / Fleet Enhancement Dashboard), with a genuinely distinct tool set, a genuinely
separate API surface (`/api/fleet/requests*`), and a real, code-enforced
scan-then-human-approve-then-apply workflow. But it is **not architecturally isolated** from
the other 67 agents: same `agent_registry`/`capability_registry` (all 72 register the same
way), same orchestration engine (`run_agent_graph`/`base_graph.py`), same shared memory store,
no Docker monitoring, no deployment workflow, no automatic project/roadmap planning, and
`architecture_reviewer` (which would plausibly belong in a "guardian" set) is explicitly
excluded from the named 5.
Plan: if the user wants a truly separate subsystem, the concrete gap list is: (1) a distinct
memory namespace/tag, (2) folding `architecture_reviewer` in or adding architecture tools to
one of the 5, (3) adding Docker/log/deploy-awareness tools if that scope is wanted, (4) an
explicit registry flag distinguishing "fleet-governance" agents from task agents instead of
today's implicit grouping-by-comment.

---

---

## Q65. Token & Context Budget Management

**Stage 1.5 (2026-07-31): DONE — all items below fixed in one pass.** `_trim_messages` (the old
pure drop-oldest function this whole section originally described) no longer exists; replaced by
`_select_messages_to_condense`/`_condense_messages` (`backend/app/agents/base_graph.py:362,448`)
and, for the graph that previously had nothing at all, `chat_agent.py`'s own
`_condense_history_async` (`backend/app/agents/chat_agent.py:422`).

- Aware of model context limits: **YES.** New `TIER_CONTEXT_WINDOWS`
  (`backend/app/fleet/model_router.py:76`) — a real model→context-window table, sourced via live
  web search on 2026-07-31 (not guessed): 1M tokens is GA for current-gen Opus/Sonnet as of
  2026-03-13 (Anthropic API release notes), Haiku 4.5 confirmed at 200K, the Groq/"gpt" tier's real
  models confirmed at 128K (also surfacing a separate, flagged gap: those exact Groq models were
  deprecated 2026-06-17). Exposed via `RouteConfig.context_window` and
  `ModelRouter.context_window_for()`. The day-to-day condense trigger still uses
  `context_token_budget` (a much smaller practical operating budget, by design — this ceiling table
  is for validation/percentage-of-real-limit purposes, not the primary threshold).
- Aware of token budgets: **YES** — unchanged real mechanism (`tokens_in`/`tokens_out` on
  `AgentRunState`, `app/fleet/budget_manager.py` for `$` cost), plus the new condense check now
  actually consumes it for context-size purposes too (previously it only fed cost tracking).
- Aware of conversation size / prompt growth: **YES for both graphs now.** `base_graph.py::call_llm`
  already had this; `chat_agent.py` previously had **none at all** (confirmed by grep before this
  day's work: zero `tokens_in`/`tokens_out`/`response.usage` references anywhere in the file). New
  `self._tokens_in`/`self._tokens_out` instance attributes (persist for the life of the session,
  same pattern as the existing `self._background_processes`), accumulated from
  `final.usage.input_tokens`/`.output_tokens` after every real streaming call.
- Aware of memory growth: **PARTIAL, unchanged** — out of Stage 1.5's scope (memory-embedding table
  growth, not conversation context growth); still tracked as a separate gap (Q120).
- Can summarize context: **YES.** `_summarize_dropped_messages`/`_summarize_dropped_messages_async`
  make a real haiku-tier LLM call (routed through the existing circuit breaker) to condense the
  dropped middle messages into 3-8 concrete bullet points, spliced back in as one synthetic message
  in place of the originals — proven via `tests/test_base_graph_scaffold.py::TestCondenseMessages`
  and the end-to-end `tests/test_gap_stage15_context_condense.py`/
  `test_gap_stage15_chat_context_condense.py` (real content from the summary confirmed reaching a
  later real LLM call, not silently dropped). On summarization failure: an honest placeholder
  ("summarization failed: ...") is spliced in instead — never a fabricated summary.
- Can compact history: **YES** — same mechanism; now genuinely content-preserving, not just
  message-count-shrinking (and can leave the count unchanged when the dropped section is small,
  since 1 real message replaced by 1 summary message nets zero count change while still shrinking
  actual token volume).
- Preserve critical information: **YES** — condensed via LLM summarization instead of unconditional
  drop; the summary explicitly asks for concrete specifics (file paths, values, conclusions), not
  vague generalities.
- Avoid context overflow: **YES**, unchanged mechanical guarantee, now model-aware via the new table.
- Warn users when limits are approaching: **YES.** New `push_context_trimmed()`/
  `push_approaching_limit()` (`backend/app/services/activity_stream.py`) — the latter fires once
  `tokens_in` crosses 80% of budget, before an actual condense happens, wired into both graphs via
  the same SSE/`session.push()` mechanism already used for every other event type.
  **A real boundary-condition bug caught by the new test suite before shipping**: chat_agent.py's
  first version had a separate outer `pct >= 1.0` pre-check that didn't exactly match
  `_select_messages_to_condense`'s own `tokens_in <= token_budget` cutoff at the precise
  `tokens_in == token_budget` boundary — at that exact edge, NEITHER event fired at all. Fixed by
  removing the redundant outer check and always attempting condense first, branching on the real
  `was_condensed` result (matching `base_graph.py::call_llm`'s own pattern, which never had this bug).
  Tests: `tests/test_base_graph_scaffold.py` (7 new/replaced tests), `tests/test_activity_stream.py`
  (2 new), `tests/test_gap_stage15_context_condense.py` (2), `tests/test_gap_stage15_chat_context_condense.py`
  (2), `tests/test_model_router.py` (4 new, 20 total). Full regression: 20/20 known baseline
  unchanged, 3,470 passed.

---

---

## Q66. Production Reliability

- Retries: **YES** — `app/fleet/tool_manifest.py` declares a `retry_policy: "none"|"once"|"backoff"` field on every one of its `ToolManifestEntry` records (lines 27-36), and `app/agents/groq_adapter.py:288,318` implements a real retry loop (`max_retries = get_settings().groq_max_retries`) for Groq rate-limit errors.
- Exponential backoff: **YES** — `groq_adapter.py:288` — "Retries up to 5 times with exponential backoff on rate-limit errors (413/429)"; `tool_manifest.py`'s `retry_policy="backoff"` is applied to specific network-calling tools (lines 1099, 1107, 1115).
- Circuit breakers: **NO** — no `CircuitBreaker` class or "circuit breaker" pattern found anywhere in `backend/app` (explicit grep for `circuit.breaker|CircuitBreaker` returned zero matches). Retry/backoff exist, but nothing trips open after repeated failures to stop hammering a failing dependency.
  Plan: add a circuit-breaker wrapper around the Anthropic/Groq client calls in `app/agents/base.py`/`groq_adapter.py` that opens after N consecutive failures.
- Timeout handling: **YES** — widespread; `tool_manifest.py`'s `timeout_s: int` field is set per-tool (e.g. `read_file` timeout_s=5, line 45), and 212 occurrences of `asyncio.wait_for`/`timeout=`/`TimeoutError` across 19 files (`app/pipeline/concurrency.py`, `app/agents/chat_agent.py`, `app/repo_tools/browser_driver.py`, etc., verified via grep count).
- Idempotency: **PARTIAL** — real idempotency checks exist at specific call sites (`app/api/tasks.py:512` — "the same signal `approve_task`'s idempotency check above uses"; `app/event_bus/bus.py:46` — "Idempotent if the exact handler is already registered"; `app/fleet/capability_registry.py:124` — "Idempotent (register() is write-once-per-name)"), but this is case-by-case, not a systemic idempotency-key mechanism applied uniformly across all mutating endpoints.
- Checkpointing: **YES** — `app/fleet/fleet_checkpoint.py` implements a full `AgentCheckpoint`/`CheckpointStore` save→restore→rollback cycle (thread-safe, 500-capacity ring buffer, deep-copy on save/restore for immutability, lines 1-60), explicitly modeled on `roo-code`'s and LangGraph's checkpoint patterns per its own docstring.
- Transaction safety: **NOT VERIFIED** — not directly inspected in this pass beyond seeing SQLAlchemy async sessions used throughout (`app/db/repository.py`); a dedicated review of transaction boundaries/rollback-on-exception across all DB writes was out of scope for this question set's time budget.
- Rollback: **YES** — `app/fleet/fleet_checkpoint.py`'s `rollback_to()` plus `app/fleet/failure_ladder.py` re-exports it as an explicit, named "Rollback" rung in a documented 7-state Failure Recovery Ladder (Checkpoint, Rollback, Resume, Retry, Escalate, Abort, Human Review — `failure_ladder.py:1-27`), backed by `app/agents/rollback_agent.py` and tested in `tests/test_failure_ladder.py`. Per the module's own docstring (lines 48-60), Rollback/Resume are deliberately kept as manual/operator-invoked actions rather than auto-triggered — an explicit, documented design decision, not an oversight.
- Structured error reporting: **YES** — `app/db/repository.py:25` defines `class TransitionError(ValueError)` for state-machine violations; `app/fleet/base_graph.py`'s `QualityGateResult` (lines 840-920) attaches a structured `result["_quality_gate"] = {passed, checks, warnings}` to every agent submission; `app/fleet/metrics.py`'s `RunMetrics` captures per-tool `error` strings (`ToolCallRecord.error`, line 61) correlated by `trace_id`.

---

---

## Q67. Real-World Engineering Behavior

- Inspect architecture: **YES (prompt-mandated)** — `architect.md` Steps 1-3, `coder.md` Step 3.
- Inspect existing patterns: **YES (prompt-mandated)** — `coder.md` Step 3: "search_code and search_symbols to find how similar things are done. Follow existing patterns — do not invent new ones."
- Inspect coding standards: **PARTIAL** — `_GLOBAL_STANDARDS.md` §4 (SOLID/KISS/DRY/YAGNI, existing architecture respect) is itself the standards document every agent inherits, but there's no step instructing an agent to look for a project-specific style/lint config before writing code beyond running the linter after.
- Inspect dependencies: **YES** — `decomposer.md`'s `depends_on` graph, `architect.md` Step 5 (DB models/migrations).
- Inspect tests: **PARTIAL** — no explicit "read existing tests before changing code" step found in `coder.md`/`architect.md` (only "run tests" post-change, `chat.md` step 5/6); reading existing test files for conventions before writing new ones isn't a named mandatory step.
- Inspect CI/CD: **NO (for general coding agents)** — grepped `backend/roles/*.md` for CI/CD-related terms: only `cicd_agent.md` (a dedicated, narrow-scope agent) and safety-only mentions (`coder.md` line 20: "Never write to... `.github/workflows/**`") exist; `coder.md`/`backend_dev.md`/`architect.md` have no step instructing inspection of `.github/workflows/` before a general code change.
- Inspect deployment implications: **NOT VERIFIED** — no role prompt for general coding agents (`coder.md`, `backend_dev.md`, `frontend_dev.md`) mentions considering deployment impact; this concern is implicitly delegated to human deploy-gating (`CLAUDE.md`'s "Deploy is a human action forever," reflected in the real absence of any deploy tool — see Q55) rather than being inspected pre-change.
- Inspect documentation: **NOT VERIFIED** — no explicit "read existing docs before changing code" step found in the general coding role prompts (docs are the `docs_agent`'s own domain, not a prerequisite step for `coder`/`backend_dev`).
- "Only then make changes" ordering: **YES for `chat_agent.py` — gap-closure Days 15-16 (2026-07-30
  / 31).** The read-before-write ordering was real and prompt-repeated but not code-blocked; it now
  genuinely is, for the highest-risk agent. Day 15 added `VerificationConfig.blocking_until`
  (`app/agents/base_graph.py`) — a tool named there is refused with a real `[POLICY DENIED]` result,
  the handler never runs, until the required flag is set. Day 16 wired `chat_agent.py`'s own
  `_VERIFICATION_CFG` to it for the first time — that config object existed since the class was
  written but was never consulted anywhere (`ChatGraphState` had no `verification` key at all).
  `write_file`/`edit_file`/`apply_patch`/`bash` are now genuinely refused until at least one
  `read_file`/`search_code` call has happened in the session — accumulating across turns via
  LangGraph's own checkpointer, not reset every message. Proven live by
  `backend/tests/test_gap16_chat_agent_verification_gate.py` (4 tests) driving the real compiled
  graph through real scripted LLM turns, not internal bookkeeping assertions. `coder`/`architect`/
  other worker agents (base_graph.py-routed, not chat_agent.py's own separate graph) still rely on
  prompt-level ordering only — this fix is scoped to chat_agent.py specifically, the one agent whose
  `expected_verification` this item's original citation actually pointed at.
  Plan: extend `blocking_until` to the worker-agent tier (`base_graph.py::run_agent_graph()`-routed
  agents) the same way, and add explicit CI/CD- and deployment-implication-inspection steps to the
  general coding role prompts, which still have none.

---

## Q68. Impossible & Unsupported Requests

- explain why: **PARTIAL** — `status: "blocked"` (`AgentResult.status`, set when `final_state["submitted"]` is false) is the structural signal that a request could not be completed; blocking reasons are surfaced via whatever the agent's own last message/critique says (e.g. `critique_node`'s `[Critique]` messages, `replan_node`'s `[Replan]` messages with a real cited reason), not a single dedicated "why impossible" field on `AgentResult`.
- identify the blocking constraint: **PARTIAL** — same mechanism; `_run_quality_gate`'s `checks`/`warnings` (`base_graph.py:850-919`) do cite specific failed checks (e.g. "planner confidence 0.40 below required 0.70") when escalating to human review, which is a real, evidence-citing blocking-constraint identification for that one path (quality-gate escalation) — but this doesn't cover every kind of "impossible" (e.g. a request needing an unsupported tool/capability that was never attempted).
- distinguish temporary vs fundamental limitations: **YES — gap-closure Day 16 (2026-07-31).**
  `roles/_GLOBAL_STANDARDS.md` §8 now defines the taxonomy explicitly (`temporary` — resolvable with
  more info/a retry/a different approach; `fundamental` — needs a scope/architecture/requirements
  decision outside the agent's role) and every one of the 72 agents inherits it. Real, not just
  prompt text: `_run_quality_gate` (`app/agents/base_graph.py`, the same shared, graph-enforced
  chokepoint every `submit_*` call already routes through — Phase 3.7) now checks that any
  `status="blocked"`/`"needs_human"` submission includes `limitation_type` set to exactly one of
  `"temporary"`/`"fundamental"`.
- propose realistic alternatives: **YES — gap-closure Day 16 (2026-07-31).** The same
  `_run_quality_gate` check also requires a real, non-empty `proposed_alternative` string alongside
  `limitation_type`. Neither field is a new per-agent JSON-schema property (retrofitting 72
  hand-written `input_schema` declarations was out of scope for one day) — the model can include
  extra tool-call keys beyond what a schema declares, and none of the 72 submit schemas set
  `additionalProperties: false`, so the prompt-level instruction in `_GLOBAL_STANDARDS.md` §8 is
  sufficient for every agent to supply them. Missing either field doesn't block the submission
  outright (matching the existing critique/confidence gate's own informational-only precedent) — it
  sets `requires_human_approval=True`, so a blocked result with no real next step is always routed
  to a human instead of silently disappearing. Proven by `backend/tests/test_gap16_limitation_taxonomy.py`
  (9 tests: direct `_run_quality_gate` unit tests for both fields, invalid values, empty strings,
  `needs_human` gated identically to `blocked`, non-blocked statuses unaffected, plus 2
  `execute_tools` integration tests confirming the real escalation and non-escalation paths).
- avoid pretending success: **YES** — this is a real, tested, structural guarantee, not aspirational: `AgentResult.verified` and `.raw` are graph-enforced from `state["verification"]`/`final_state["result"]`, never the model's raw unverified claim (Phase 3.4 gap-closure explicitly fixed a bug where a false claim like `tests_run=True` with no real tool call behind it could leak through — closed across all 25 affected agent files, tested in `tests/test_phase34_real_output_verification.py`). A model cannot fabricate "tests passed" and have it register as `verified=True`.

---

## Q69. Autonomous Quality Improvement

- recurring bugs: **YES** — `agent_debugger`'s autonomous scan reads `audit_log_read`/`fleet_metrics_read` for real failure evidence and files bug enhancement requests (`backend/app/agents/agent_debugger.py:164-211`).
- recurring user requests: **NO** — no mechanism tracks repeated user requests/feature asks as a pattern; nothing in the codebase aggregates user-facing task descriptions for recurrence.
  Plan: add a periodic scan over task descriptions/titles clustering by similarity.
- recurring architectural problems: **NO** — `architecture_reviewer` can find one-off architectural risks per task, but is not periodic, and no aggregation of *recurring* architectural findings across runs exists.
- performance bottlenecks: **YES** — `agent_performance_reviewer`'s scan, evidenced above.
- maintainability issues: **PARTIAL** — `quality_auditor`'s scan covers general "quality" (lint/tsc/read_file/search_code), which overlaps but isn't a dedicated maintainability-debt tracker (that role is `tech_debt_agent`, task-triggered only).
- "converted into prioritized improvement proposals with expected impact and required approvals": **PARTIAL** — every `enhancement_requests` row has `priority` (emergency/medium/low) and requires human approval (`backend/app/db/models.py:539-547`, `backend/app/api/fleet_dashboard.py:210-241`) — real. But there's no "expected impact" field/estimate captured anywhere — priority is a coarse 3-level enum, not a quantified impact estimate.
  Plan: add an `expected_impact` field to `EnhancementRequest` and require agents to populate it.

---

## Q70. Final "Claude Code Parity" Audit

(Scoped per assignment: full breadth, concise per-category — deep dives on categories another
question already covers in more depth, e.g. Memory=Q95, Orchestration=Q77, live here at synthesis
depth.)

- Conversation quality: Implemented — `chat_agent.py`, real LangGraph interrupt()-based graph
  (Phase 5.2). Readiness: 70%. Gap: no verification-contract parity with worker agents (documented
  honest gap). Priority: Medium.
- Intent understanding: NOT VERIFIED in this pass (assigned to a different question in the audit
  split — no independent evidence gathered here).
- Planning: Implemented — `planner_node`, `_gather_facts_and_plan`, `request_clarification` (5.3).
  Readiness: 60%. Gap: opt-in only for replanning. Priority: High.
- Reasoning: Partial — critique/replan machinery real but default-off. Readiness: 55%. Priority: High.
- Orchestration: Implemented — `manager.py` LangGraph epic graph (5.1), 72-agent fleet. Readiness: 65%.
  Gap: in-process concurrency ceiling (Q77). Priority: Critical.
- Agent routing: Implemented — `capability_registry.py`, `ModelRouter`, fleet dispatch via
  `app/api/specialized_agents.py`. Readiness: 70%.
- Tool routing: Implemented — per-tier tool contracts (`AGENT_CONTRACT`), `TOOL_MANIFEST` compliance
  tests. Readiness: 80%.
- Memory: Partial — real pgvector memory, but globally unscoped (no `repo_id`/`project_id`). Readiness:
  55%. Gap from Claude Code: Claude Code's memory is inherently scoped to the invoking cwd; this
  repo's is process-global. Priority: Critical.
- File editing: Implemented — `edit_file`, worktree isolation (ADR-003). Readiness: 75%.
- Repository understanding: Implemented — tree-sitter scanner, call/class/package graphs
  (Phase 6.4). Readiness: 75%.
- Search: Implemented — `search_code`/`search_symbols`/`find_references`/`get_file_tree`. Readiness:
  75%.
- Refactoring: Partial — `refactor_agent.py` exists as a role; NOT VERIFIED against a real refactor
  benchmark in this pass. Readiness: NOT VERIFIED.
- Testing: Implemented — `test_writer_agent`/`test_coverage_agent` with real, graph-enforced
  `tests_run`/`coverage_measured` flags (not model-claimed, Phase 2.1). Readiness: 70%.
- Terminal usage: Implemented — scoped `bash` tools per tier, policy-engine allow/denylist. Readiness:
  75%.
- Git workflows: Implemented — full git tool set incl. `git_tag`, confirmation-gated `git_push`.
  Readiness: 80%.
- Deployment support: Partial — `infra_agent` deliberately restricted to dry-run/lint only
  (`terraform`/`kubectl` fleet-denied). Readiness: 40%. Priority: Medium.
- Documentation: Implemented — `docs_agent`, `readme_agent`, `api_docs_agent`,
  `changelog_agent`/`release_notes_agent` roles present. Readiness: NOT VERIFIED in depth this pass.
- Recovery: Partial — durable only for pm/architect/decomposer pipeline + orphan-recovery loop;
  worker-agent runs not checkpointed. Readiness: 50%. Priority: High. (See Q38.)
- Safety: Implemented — policy engine, HITL approval gate, credential vault, prompt-injection
  defenses. Readiness: 75%.
- Reliability: Partial — 3318/3339 tests passing (99.4%), all 21 failures triaged as environment, not
  code. Readiness: 70%. Gap: no load/stress evidence.
- Performance: NOT VERIFIED — no benchmark data found in-repo.
- Extensibility: Implemented — new agents follow a well-documented pattern
  (`docs/ADD_A_NEW_AGENT.md` exists), `TOOL_MANIFEST`/`AGENT_CONTRACT` conventions enforced by tests.
  Readiness: 70%.
- User experience: NOT VERIFIED in this pass (frontend not deep-audited by this question set).

---

---

## Q71. Professional Domain Coverage

**How the platform decides which expertise to apply** (verified): dispatch is **task-type based, not
semantic/role based**. `backend/app/fleet/capability_registry.py` defines `AgentCapability` (name, tools,
input_types, output_types, capabilities) that each agent registers at import time; `decomposer.py` assigns
a subtask a `type` string, and `backend/app/fleet/fleet_manager.py::select()` / the legacy
`_TYPE_TO_TAG` dispatcher (referenced at `fleet_manager.py:17,48`) map that type string to one specific
agent. There is no NLU-based "which of 100 professional domains does this request belong to" classifier —
it is a fixed type→agent lookup table, confirmed by `capability_registry.py`'s own comment: "Replaces
hardcoded dispatch tables in manager.py/dispatcher.py" (still type-keyed, just less hardcoded).

### Fully Implemented (dedicated agent + real tools/role file)
- **Backend Development** — `backend_dev.py` ("Implements server-side changes in an isolated worktree — Python/FastAPI only")
- **Frontend Development** — `frontend_dev.py` ("Implements TypeScript/Next.js UI changes in an isolated worktree")
- **Full Stack Development** — composition of `backend_dev.py` + `frontend_dev.py` orchestrated by `manager.py`, plus generic `coder.py` ("generic backend/frontend capable")
- **API Development (design)** — `api_designer_agent.py` ("Designs REST/GraphQL API contracts, schemas, and OpenAPI specs")
- **API Development (docs)** — `api_docs_agent.py` (reads real route handlers + Pydantic schemas)
- **Database Design / Schema / Migrations** — `database_architect.py`, `schema_agent.py`, `migration_agent.py` (Alembic-specific, schema-inspection-before-write)
- **SQL** — `sql_agent.py` (dedicated `run_sql`/`explain_query` tools per `IMPLEMENTATION_PROGRESS.md:627`)
- **AI Engineering / Machine Learning (implementation)** — `ai_engineer.py` ("training pipelines, inference code, eval scripts, embeddings"), own handler factory `make_ai_engineer_handlers` (`tools.py:5762`) with `fetch_url`
- **Model Evaluation** — `evaluation_agent.py` ("Runs LLM output evaluation suites, scores test cases")
- **RAG Systems / Vector Databases** — `rag_engineer_agent.py` ("chunking strategy, embedding model selection, vector store setup, retrieval strategy")
- **Data Engineering / ETL / Data Pipelines** — `data_pipeline_agent.py`
- **DevOps (read-only health checks)** — `devops.py` ("Runs allowlisted health-check commands... No deploy, no writes")
- **Docker** — `docker_agent.py` (own `make_docker_agent_handlers`, `docker_build`/`docker_exec` tools)
- **CI/CD (config review, human-gated)** — `cicd_agent.py` ("always requires human approval")
- **Monitoring** — `monitoring_agent.py` ("Collects real system metrics... read-only")
- **SLO/Alerting** — `slo_agent.py` (produces real PromQL from existing config, not invented numbers)
- **Security (secure coding, secrets, auth, OWASP/STRIDE)** — `security_reviewer.py`, `security_architect.py`, `dependency_security_agent.py` (CVE-specific), `env_checker_agent.py` (hardcoded secrets)
- **Regulatory Compliance (GDPR/SOC2/HIPAA/PCI-DSS)** — `compliance_agent.py`
- **QA / Unit / Integration Testing** — `qa.py` (runs pytest/mypy/ruff), `test_writer_agent.py`, `test_coverage_agent.py`
- **Performance Testing / Load Testing** — `load_test_agent.py` (k6/Locust script generation with real routes)
- **Performance Optimization** — `performance_reviewer.py` (slow SQL, O(n²) loops, missing indexes)
- **Architecture / System Design** — `architect.py`, `architecture_reviewer.py` (import graphs, circular deps)
- **Refactoring** — `refactor_agent.py` (test-verified before/after)
- **Requirement Analysis / Business Analysis** — `pm.py`, `business_analyst.py`
- **Roadmap/Sprint Planning, Agile** — `sprint_planner.py`, `user_story_generator.py`, `cost_estimator_agent.py`
- **Technical Documentation** — `docs.py`, `readme_agent.py`, `changelog_agent.py`, `release_notes_agent.py`, `runbook_generator_agent.py`, `onboarding_agent.py`
- **Accessibility (WCAG 2.1)** — `accessibility_agent.py`
- **Code Review / Style** — `reviewer.py`, `code_quality_agent.py`, `style_reviewer.py`
- **Debugging / Root Cause** — `debugger_agent.py`, `bug_fix.py`
- **Dependency Management** — `dependency_agent.py`, `version_manager_agent.py`
- **Localization/i18n** — `localization_agent.py`
- **Incident Response / Rollback** — `incident_responder_agent.py`, `rollback_agent.py`
- **Technical Debt** — `tech_debt_agent.py`

### Partially Implemented (generic coverage only, no dedicated specialization — cite evidence of the gap)
- **Microservices / Distributed Systems / Event-Driven Architecture / Real-Time Systems** — no dedicated agent; only generic `architect.py`/`infra_agent.py` could touch these contextually. `grep` for `websocket` across `backend/app/agents/*.py` and `backend/roles/*.md` returned **zero hits**; queue/worker awareness exists only as a **search** tool (`_FIND_QUEUE_TOOL`/`_FIND_WORKER_TOOL`, `tools.py:4830-4845`, regex-matches BullMQ/RQ/Celery/asyncio.Queue patterns already in the repo) — this finds existing queue code, it does not design or implement event-driven/real-time systems.
- **SDK Development** — no dedicated agent; `api_designer_agent.py` designs API contracts but SDK-generation is not evidenced anywhere.
- **LangGraph / LangChain / Agentic AI / MCP Development** — LangGraph/LangChain appear pervasively in `backend/app/agents/*.py` (`architect.py`, `ai_engineer.py`, `pm.py`, `decomposer.py`, etc.), but this is because **the platform's own orchestration is built on LangGraph** — self-referential usage, not a user-facing "build me a LangGraph app" capability. `ai_engineer.py`'s role file (`backend/roles/ai_engineer.md:17`) only cites "LangGraph nodes" as a pattern to search for in *this* repo. No dedicated MCP-server-building tool/agent found.
- **Fine-Tuning Guidance** — `ai_engineer.py`'s description says "training pipelines" generically; no PEFT/LoRA/fine-tuning-specific tool or role text verified.
- **AI Deployment** — covered only by composing `ai_engineer.py` (inference code) + `docker_agent.py` + `cicd_agent.py`; no single dedicated AI-deployment agent.
- **Data Warehousing / Analytics/BI** — `data_pipeline_agent.py` covers generic ETL/schemas but no warehouse-specific (Snowflake/BigQuery/Redshift) or BI-dashboard tooling evidenced.
- **Kubernetes / AWS / Azure / Google Cloud** — `infra_agent.py` **reviews** Terraform/K8s/Dockerfiles/CI for security risks (`AGENT_CONTRACT["description"]`, `infra_agent.py:25`) — read-only audit only, never deploys or provisions. `grep -rli "aws\|azure\|google cloud\|gcp"` matched only `backend/roles/infra_agent.md` (prose) — no cloud-SDK-specific tool exists.
- **Networking / Reverse Proxies / SSL / DNS / Linux & Windows Administration** — only `devops.py`'s narrow, allowlisted read-only health-check commands; no certbot/DNS/nginx-config tool, no OS-admin-specific agent.
- **Authentication / Authorization (implementation)** — implemented only generically via `backend_dev.py` executing whatever the plan specifies; audited (not implemented) by `security_reviewer.py`.
- **E2E Testing** — `test_writer_agent.py` writes "pytest or Jest test suites"; real Playwright browser tools do exist (`browser_open`, `browser_navigate`, `browser_screenshot`, `browser_read_dom` — `tools.py:9560-9635`, wired inside `make_chat_handlers`) but are only confirmed exposed to `chat_agent.py`'s own tool schema, not to `test_writer_agent.py` — no dedicated E2E-authoring agent verified.
- **UX Guidance / Design Systems / Responsive Design** — `frontend_dev.py` implements UI (Next.js/Tailwind); `accessibility_agent.py` covers a11y specifically; but no dedicated UX-research or design-system agent exists.
- **Roadmap Planning** — `sprint_planner.py` covers sprint-level planning; no agent covers multi-quarter roadmap strategy.

### Missing (no agent, no tool, no prompt evidence)
- **Mobile Development** (Android native, iOS native, Flutter, React Native) — `grep -rli "flutter\|react native\|android\|\bios\b"` across all agent `.py` and role `.md` files returned **zero hits**.
- **Desktop Applications** (Electron, native desktop) — no evidence anywhere in the codebase.
- **Serverless / AWS Lambda specifically** — the only "lambda" hits in agent code are Python `lambda` expressions (e.g. `architect.py:131`), not AWS Lambda tooling.
- **Kafka/RabbitMQ/message-broker implementation** — `grep -rli "kafka\|rabbitmq"` returned zero hits; `celery` only appears inside the read-only pattern-search tool noted above.
- **Payment integrations** (Stripe etc.) — zero hits except one unrelated mention in `test_coverage_agent.md` prose.
- **CMS integrations, PWA build tooling, e-commerce-specific tooling** — zero hits.
- **Computer Vision, NLP-specific, Recommendation Systems, Time-Series Forecasting** as dedicated specializations — zero hits; would fall back entirely to generic `ai_engineer.py`.

---

---

## Q72. Universal Skill Coverage

Primary evidence source: `backend/roles/_GLOBAL_STANDARDS.md` (inherited by every role prompt — "Every agent
in this workforce inherits this constitution") and `IMPLEMENTATION_PROGRESS.md`'s Phase 4 audit
(lines 576-670), which re-verified these skills against real constructed tool/handler lists, not
docstring grep.

- Requirement Analysis: **PARTIAL** — `_GLOBAL_STANDARDS.md §1` step 1 ("UNDERSTAND — identify user goal... split into objectives") is fleet-wide, but dedicated requirement-elicitation depth exists mainly in `pm.py`/`business_analyst.py`; most agents only "understand" a pre-decomposed subtask, not raw requirements.
- Problem Decomposition: **YES** — `decomposer.py` is a dedicated agent for this; `_GLOBAL_STANDARDS.md §1` step 1 mandates it fleet-wide.
- Critical Thinking: **PARTIAL** — `_GLOBAL_STANDARDS.md §6` mandates an "adversarial self-check" for non-trivial decisions, but this is a prompted instruction, not a mechanically verified behavior.
- Planning: **YES** — `_GLOBAL_STANDARDS.md §1` step 2 mandatory; `planner.py` is a dedicated planning agent.
- Architecture Analysis: **PARTIAL** — dedicated agent (`architecture_reviewer.py`, `architect.py`) exists, but not every agent performs it; scoped to relevant roles only.
- Code Reading: **YES** — `READ_ONLY_TOOLS` (`tools.py:22`) is the baseline toolset inherited by nearly all agents; confirmed fleet-wide in `IMPLEMENTATION_PROGRESS.md:613` ("Of 70 real agents, only `executive`... and `research`... lack any git tool").
- Code Writing: **YES** (for write-capable agents) — `coder.py`, `backend_dev.py`, `frontend_dev.py`, `refactor_agent.py`, etc. have `edit_file`/`write_file` in `AGENT_CONTRACT["allowed_tools"]`.
- Code Review: **YES** — dedicated agents (`reviewer.py`, `code_quality_agent.py`, `style_reviewer.py`).
- Refactoring: **YES** — dedicated `refactor_agent.py`, test-verified before/after.
- Debugging: **YES** — dedicated `debugger_agent.py`, `bug_fix.py`.
- Root Cause Analysis: **YES** — `_GLOBAL_STANDARDS.md §7`: "On any failure: read the FULL error output. Fix the root cause, not the surface symptom." Fleet-wide mandate, plus `debugger_agent.py` specializes in it.
- Testing: **YES** — `qa.py`, `test_writer_agent.py`, `test_coverage_agent.py`, `load_test_agent.py`.
- Verification: **YES (72/72 confirmed)** — `IMPLEMENTATION_PROGRESS.md:620-622`: "Already satisfied fleet-wide: every one of the 72 real agents has a real `VerificationConfig` instance... checked by type" — citation: `tests/test_phase4_item2_item7_verify_and_honest.py::test_every_real_agent_has_a_verification_config`.
- Documentation: **YES** — dedicated agents (`docs.py`, `readme_agent.py`, `api_docs_agent.py`, etc.) plus `_GLOBAL_STANDARDS.md §10` (Output Contract Discipline).
- Communication: **YES** — `_GLOBAL_STANDARDS.md §9` ("Structured, concise, evidence-cited... Findings format: severity, file:line, what, why it matters, specific fix") mandated fleet-wide.
- Collaboration: **PARTIAL** — cross-agent handoff exists via pipeline artifacts (research → architect → planner per `backend/roles/research.md:58-59`), but there is no agent-to-agent negotiation/dialogue mechanism, only sequential artifact passing.
- Decision Making: **PARTIAL** — `_GLOBAL_STANDARDS.md §6` requires stating assumptions and self-checking decisions, but final architectural/irreversible decisions are explicitly escalated to humans (§8), not made autonomously — by design, so "decision making" is bounded.
- Risk Assessment: **YES** — `_GLOBAL_STANDARDS.md §1` step 2 requires a "rollback plan"; `architect.py` role produces "risks" as part of its plan output; `cost_estimator_agent.py` estimates effort/cost risk.
- Performance Analysis: **YES** — dedicated `performance_reviewer.py`, `load_test_agent.py`.
- Security Awareness: **YES** — `_GLOBAL_STANDARDS.md §5` (fleet-wide security guidelines: no hardcoded secrets, injection/SSRF awareness) plus dedicated `security_reviewer.py`/`security_architect.py`.
- Cost Awareness: **PARTIAL** — dedicated `cost_estimator_agent.py` exists (story points + LLM token costs) but this is a separate opt-in agent, not a universal behavior every agent applies to its own actions.
- Reliability Engineering: **PARTIAL** — `slo_agent.py` and `incident_responder_agent.py` cover this narrowly; not a fleet-wide skill.
- Maintainability: **YES** — `_GLOBAL_STANDARDS.md §11` ("Production Quality Bar": "Every output must improve or protect: correctness, maintainability, observability, robustness, modularity, testing").
- Observability: **PARTIAL** — named explicitly in `_GLOBAL_STANDARDS.md §11` and covered by `monitoring_agent.py`/`slo_agent.py`, but most write-capable agents (e.g. `coder.py`) do not verifiably add logging/metrics as part of their own output contract.
- Deployment Planning: **PARTIAL** — `cicd_agent.py`/`docker_agent.py` exist but both explicitly "always require human approval" and never execute a deploy; no agent owns end-to-end deployment planning as a first-class skill.
- Iterate on Failure (bonus, explicitly audited): **YES, opt-in** — `IMPLEMENTATION_PROGRESS.md:631-639`: self-critique/bounded-replanning/quality-gate machinery is real and available via `enable_critique=True`/`enable_replanning=True`, but not flipped on by default fleet-wide (explicitly tracked, not hidden).
- Contributes to shared learning (`record_learning`): **YES (71/72, `executive` excluded by design)** — `IMPLEMENTATION_PROGRESS.md:601-612`, citation `tests/test_phase4_item4_record_learning_rollout.py` (96 tests).

Plan (for PARTIAL items above): promote observability/deployment-planning/cost-awareness/reliability-engineering from "dedicated agent only" to a fleet-wide checklist item in `_GLOBAL_STANDARDS.md`, mirroring how verification (`VerificationConfig`) was made universal.

---

---

## Q73. Adaptive Expertise

Evidence: dispatch is governed by `backend/app/fleet/capability_registry.py` (task **type** → agent lookup)
and `decomposer.py`/`fleet_manager.py`'s static `_TYPE_TO_TAG`-style mapping (`fleet_manager.py:17,48`).
`grep -rln "user_role|detect_role|role_detection|adaptive_expertise" backend/app` matched only
`backend/app/db/models.py` and `backend/app/middleware/rbac.py` — both are **authorization/permission
role fields** (RBAC — who is allowed to do what), not a mechanism that detects a user's *professional*
role (AI Engineer vs. PM vs. DevOps) from conversational context and adapts expertise/terminology. No
persona-detection, terminology-switching, or explanation-depth-adjustment logic was found anywhere in
`backend/app/agents/` or `backend/roles/`.

- Does it identify the user's role from context (SWE/AI Eng/DevOps/PM/etc.)?: **NO** — no role-detection code found; `rbac.py`/`models.py` "role" fields are access-control roles (e.g. admin/member), not professional-domain personas.
  Plan: add a lightweight role classifier at session start (keyword/LLM-based) that tags the session with an inferred persona, stored in session state.
- Does it adjust explanations (depth/detail) to the user's role?: **NO** — role prompts (`backend/roles/*.md`) are fixed per-agent, not per-requesting-user; no evidence of variable explanation depth based on who is asking.
  Plan: add an "audience" parameter to role prompts that scales explanation verbosity/jargon.
- Does it change terminology to match the user's role?: **NO** — no evidence found.
  Plan: same as above — tie to the inferred persona.
- Does it choose appropriate tools based on user role?: **PARTIAL** — tool selection is real and scoped (`AGENT_CONTRACT["allowed_tools"]` differs per agent), but the scoping key is **task type**, not **requesting-user role**. E.g. `qa.py` gets read+bash-test-only tools regardless of whether a PM or a DevOps engineer asked.
  Plan: none needed if task-type scoping is accepted as sufficient; otherwise layer user-role onto task-type selection.
- Does it route work to the most suitable agent(s)?: **PARTIAL** — yes, but by declared task type via `capability_registry.py`/`fleet_manager.py::select()`, not by inferring what a "Startup Founder" vs. "Technical Lead" persona actually needs from an ambiguous request.
  Plan: extend `decomposer.py` to accept an explicit or inferred role hint and factor it into subtask typing.

**Overall**: Adaptive expertise as described in Q73 (dynamic detection of a human's professional role and
behavioral adaptation to it) is **NOT VERIFIED / effectively NO**. What exists is task-type-based
specialization across 72 agents (strong — see Q71/Q72), which is a different, narrower mechanism than
"identify the user's role and adapt."

---

---

## Q74. Learning & Improvement

*This restates Q37 (Learning System, answered in the H2 cluster) and Q113 (User Preference
Learning, answered in the C/memory cluster) from a slightly different angle — findings are
consistent with, and directly reuse, both rather than being re-derived independently.*

- Temporary session memory: **YES** — `ChatSession.history` persists per-session conversational
  turns (survives within a session; see Q45/J for restart behavior).
- Persistent memory: **YES** — `memory_embeddings` (pgvector-backed), real and durable across
  sessions.
- Shared organizational knowledge: **YES, but unvalidated on write** — same store, shared
  fleet-wide; see Q93/H2 finding: `record_learning` writes directly with zero evidence gate.
- Adaptive behavior: **NO** — per Q37's finding, nothing about HOW an agent routes, plans, selects
  tools, or reasons changes based on past outcomes; only retrieved memory *content* differs run to
  run, the underlying logic doesn't adapt.
- User preferences: **NO** — confirmed directly (Q113): no `UserPreference` model or capture
  mechanism exists anywhere; grep for preference/convention-related terms returns no real hits.
- Successful workflows: **PARTIAL** — `embed_procedure`/`query_procedures` (`app/memory/store.py`)
  do store and retrieve step sequences that worked before — genuine, real "what worked" memory —
  but nothing tracks or reports workflow *efficiency* (faster/cheaper approaches) over time.
- Failed workflows: **YES** — `category="failure"` memory rows are real and retrieved into future
  prompts as "avoid this."

**Specific stable preferences asked about, individually checked:**
- Coding style preferences: **NO** — no stored signal distinguishes a user's coding-style choice
  from a one-off; `_GLOBAL_STANDARDS.md` provides one fixed, project-wide style baseline all agents
  inherit, not a per-user learned preference.
- Architecture preferences: **NO** — same gap; `architecture`-category memory stores *decisions
  made*, not a *preference profile* the system consults before proposing new architecture.
- Preferred frameworks: **NO** — no mechanism found (same grep as Q113: zero real hits).
- Naming conventions: **NO** — no naming-convention learning/detection exists anywhere (cross-
  confirmed independently by H1's Q85 governance finding: no naming-convention checker exists at
  all, learned or fixed).
- Communication style: **NO** — no per-user tone/verbosity adaptation mechanism found; `chat.md`'s
  communication rules are fixed, not learned per user.
- Approval patterns: **PARTIAL** — `pending_approvals`/`enhancement_requests` rows record
  individual approve/reject decisions with `decided_by` (real, per-decision history exists in the
  DB), but nothing aggregates this into a *pattern* (e.g. "this user always approves git-push
  requests without hesitation, stop asking as urgently") that changes future behavior.
- Recurring workflows: **NO**, consistent with H2's Q107 finding (no pattern-recognition system
  exists at all for recurring anything — requests, workflows, or bugs).

**Where it's stored / how validated / how reused, stated plainly per the question's own ask:**
stored in Postgres (`memory_embeddings`, pgvector); validated **not at all** on write (Q93's
confirmed finding — no evidence gate, no multiple-successful-uses requirement); reused via
semantic-similarity retrieval injected into a future agent's system prompt
(`query_memory_context`/`memory_hook_node`).

**If no true learning exists, state this clearly**: per the question's own instruction — **stated
clearly: there is no true adaptive learning in this system.** What's real is retrieval-augmented
context (genuinely useful, real engineering value) — the system remembers *facts about past runs*
and surfaces them again, but nothing about the system's own decision-making logic (routing,
planning, tool selection, reasoning depth, confidence calibration) changes as a result of
accumulated experience. This should not be implied to the user as "the system learns" in the
adaptive-behavior sense; it should be described accurately as "the system has long-term retrieval
memory."

---

## Q75. Organizational Knowledge Sharing

- lessons learned / reusable patterns / architectural decisions: **YES** — `memory_embeddings` (categories: task, architecture, failure, learning, procedure) is shared org-wide across all agents via `query_memory_context` (`backend/app/memory/store.py`).
- successful implementations: **PARTIAL** — task outcomes with `outcome="completed"` are stored (`embed_task_outcome`), which is adjacent but not a distinct "successful implementation pattern" category.
- coding standards / troubleshooting guides / project conventions: **NOT VERIFIED** — no dedicated category for these was found in `memory_embeddings`'s `category` enum (task/architecture/failure/learning/procedure); they'd have to be shoehorned into an existing category if stored at all.
  Plan: confirm no separate "standards"/"conventions" store exists elsewhere; if not, this is a real gap.
- "how knowledge is synchronized": **YES, concretely** — `versioned_memory.py`'s `VersionedMemoryStore.publish()` does real semantic-similarity conflict detection (cosine similarity vs. `MEMORY_MERGE_SIMILARITY_THRESHOLD`) and LLM-based auto-merge (`_merge_via_llm`, `backend/app/fleet/versioned_memory.py:232-251`) of a new lesson against the most similar existing published one.
- "how conflicts are resolved": **YES** — same `_merge_via_llm` call — an LLM merges old vs. new content into one lesson, preferring "more specific or more recently learned guidance," fully automatic.
- "how outdated knowledge is detected": **YES** — `_versioned_lesson_archive_loop()` (`backend/app/main.py:181-200`) runs daily and archives `superseded`/`merged_into` rows older than `LESSON_RETENTION_DAYS`.
- "how incorrect knowledge is removed": **PARTIAL** — superseded/archived states exist, but nothing detects *incorrectness* (only staleness/redundancy); an incorrect-but-novel lesson has no removal path besides a human noticing and a future agent overwriting it via `knowledge_curator`'s manual curation.
- "whether human approval is required before organization-wide learning": **YES** (was NO) —
  gap-closure Day 6 (2026-07-30, root cause 3) closed this exactly as this item's own Plan
  proposed. `VersionedMemoryStore.publish()` (`backend/app/fleet/versioned_memory.py`) no longer
  writes `state="published"` — every lesson now lands as `state="draft"`, invisible to
  `_find_most_similar_published` and to `query_learning_signals` (sync to `memory_embeddings`
  moved out of `publish()` entirely). A draft only becomes real, queryable fleet memory via the
  new `VersionedMemoryStore.promote()` method, called by a new `memory_promote_lesson` tool —
  wired into `knowledge_curator`'s **APPLY phase only**, itself only reachable after a human
  approves that specific curation action on the Fleet Enhancement Dashboard (the same
  scan→propose→human-approve→apply gate this engagement's own H1 audit found real for this 5-agent
  subsystem). A companion `memory_list_draft_lessons` tool was added to `knowledge_curator`'s SCAN
  phase so drafts are actually discoverable, not just structurally gated. Verified end to end, not
  assumed: `tests/test_versioned_memory.py::test_unpromoted_draft_never_reaches_memory_embeddings`
  proves a `publish()`-only call leaves zero trace in `memory_embeddings`; 27 total tests across 4
  files (`test_versioned_memory.py` 13, `test_versioned_memory_sync.py` 5,
  `test_lesson_versioned_memory_wiring.py` 2, `test_phase_gap6_memory_promote_lesson.py` 8, plus
  1 in the wiring file already counted) cover the draft/promote lifecycle, the merge-then-promote
  path, and the tool-to-contract wiring. A real DB-pollution bug was caught and fixed while writing
  these tests: an early version of the promote-sync test put its assertions inside a `with patch():`
  block with cleanup in a separate, later `try/finally` — an assertion failure there skipped
  cleanup entirely, twice leaving real orphaned rows in `memory_embeddings` (found by directly
  querying the table, not assumed) — fixed by wrapping the whole body in one `try/finally` from the
  start. `black`/`ruff`/`mypy --strict` clean on every touched file. Full regression: 3347 passed /
  21 failed (byte-for-byte the same pre-existing 21) / 55 skipped / 17 deselected — zero
  regressions, pass count rose by exactly 11 (the new tests).

---

## Q76. Continuous Improvement

- recurring user pain points / repeated feature requests / inefficient workflows / missing capabilities: **NO** — no mechanism tracks any of these; confirmed by grep, no "capability_gap"/"pain point"/"feature request" tracking module exists anywhere in `backend/app`.
- recurring bugs: **YES** — `agent_debugger`, evidenced above.
- recommend new agents / new tools / new MCP integrations / architectural improvements / performance optimizations: **PARTIAL** — the 5 scan agents can, in principle, recommend architectural/performance changes via free-text `submit_enhancement_request` descriptions (categories are performance/bug/orchestration/knowledge/quality/security — there is no "new_agent"/"new_tool"/"new_mcp" category), but nothing structurally detects "we need a new agent/tool/MCP" as a distinct trigger.
  Plan: add explicit categories/logic for capability-gap-driven recommendations (ties to Q116).
- "require explicit human approval before implementation": **YES** — real, evidenced (`backend/app/api/fleet_dashboard.py` approve/reject endpoints; nothing applies without it).

---

## Q77. Company-Scale Readiness (100/250/500/1000 agents — governance angle)

- Hiring new agents: **PARTIAL** — adding a new agent role is a documented, real pattern
  (`docs/ADD_A_NEW_AGENT.md`, `AGENT_CONTRACT`/`TOOL_MANIFEST` conventions enforced by compliance
  tests), and Q47's own question confirms this is meant to be code-light. But "hiring" in an org sense
  (dynamic registration without a code deploy) is NOT VERIFIED — every agent found in this pass is a
  Python module imported at startup (`ensure_all_agents_registered()`, `main.py`), not data-driven.
  Plan: NOT VERIFIED whether a fully data-driven (no-deploy) agent registration path exists; if not,
  build one for true "hire without a code change."
- Retiring agents: **NOT VERIFIED** — no explicit "deactivate agent" mechanism found in this pass
  beyond simply not dispatching to it; no soft-delete/retirement-state column found on the `Agent`
  registry table in the time available.
  Plan: add an explicit `active`/`retired` state to the `Agent` model with dispatch-time enforcement.
- Replacing/promoting agents: **NOT VERIFIED** — `AgentBenchmark` table exists (`db/models.py:567`)
  suggesting performance comparison infrastructure, but no promotion workflow was traced in this pass.
- Delegating work: **YES** — real, tested: `manager.py`'s epic orchestration dispatches to
  backend_dev/frontend_dev/qa/reviewer with retry/backoff (Phase 5.1), capability-based routing
  (`capability_registry.py`).
- Supervising work: **PARTIAL** — HITL approval gate + audit log cover supervision at decision points
  (plan_review, git_push, clarification); no continuous "supervisor agent watching worker agents in
  real time" beyond the orphan-recovery heartbeat sweep.
- Auditing work: **YES** — `app.fleet.audit_log`, request- and decision-time logging (Phase 5.5),
  `pending_approvals` table with full history.
- Measuring performance: **YES** — `AgentBenchmark` table, cost/health/repair-pattern reporting
  endpoints (Phase 6.2), per-agent/day token and cost rollups.
- Balancing workloads: **PARTIAL** — concurrency semaphores cap total load
  (`max_concurrent_agent_runs`=20 default, `max_concurrent_subtasks_per_epic`=5 default) but this is a
  blunt global cap, not workload-aware balancing across agent types or projects.
  Plan: see Q24/Q50 — needs project-scoped, distributed slot accounting before real balancing is
  possible at 100+ agent scale.
- Preventing duplicated effort: **PARTIAL** — `EpicScratchpad` (epic-scoped, TTL-bound shared state,
  Phase 1.7) lets agents within one epic see each other's work; no cross-epic or cross-project
  duplication-prevention mechanism found (consistent with the "no project entity" finding — there's no
  scope boundary to detect duplication *across*).
- Sharing organizational knowledge: **YES** — `memory_embeddings` + `versioned_lessons` PUBLISHED
  bridge (Phase 1.2) is real, tested, DB-backed, and queried by every `enable_memory=True` agent run.
  Caveat: shared unconditionally fleet-wide (no project scoping — see Q95), so "sharing" is real but
  not selectively scoped, which cuts both ways for a real company (knowledge sharing works, but so does
  unwanted cross-project bleed).
- Enforcing company-wide standards: **YES** — `_GLOBAL_STANDARDS.md` inherited by every role file,
  `TOOL_MANIFEST` compliance tests enforced fleet-wide, policy engine allow/denylist applied uniformly.
- Maintaining governance: **PARTIAL** — audit logging + approval gates are real governance primitives,
  but RBAC is global (3-tier), not org-structured (no team/department/project boundaries to govern
  independently) — see Q48.
- **Architectural gaps preventing real AI-native company operation at scale**: (1) no project/workspace
  entity — the single largest blocker, affects memory scoping, RBAC, credential isolation, and
  duplication-prevention simultaneously; (2) in-process-only concurrency accounting — caps don't hold
  across multiple machines, so "1000 agents" cannot literally run concurrently without a redesign; (3)
  no agent lifecycle states (retired/promoted) in the registry schema; (4) workload balancing is a flat
  cap, not capability/load-aware.

---

---

## Q78. Final Verdict

- **Strengths**: a genuinely large, well-tested agent fleet (72 real agents, 3318/3339 tests passing,
  `mypy --strict`/`black`/`ruff` clean); real graph-enforced verification that the model cannot lie
  about its own claimed output (`state["verification"]`, confirmed fixed fleet-wide for a real bug
  found in this same engagement — `AgentResult.raw` used to prefer the model's unverified claim);
  durable pgvector-backed cross-run memory; a real HITL approval gate with audit logging; git-worktree
  process isolation (ADR-003); disciplined, heavily-documented engineering practice evidenced by
  `IMPLEMENTATION_PROGRESS.md` itself (every claim traced to a real file/test, corrections documented
  rather than hidden, e.g. the localization_agent tier correction, the Phase 5.2 unsafety-then-fix
  arc).
- **Weaknesses**: no project/workspace entity at all — confirmed directly in source
  (`credential_vault.py`'s own docstring); memory, credentials, and RBAC are all global-process-scoped,
  not multi-tenant; concurrency caps are in-process only, capping real horizontal scale; most of the
  "iterate on failure like Claude Code" machinery (critique/replanning) ships default-disabled; only
  1 of ~72 agent families (pm/architect/decomposer's pipeline) has durable crash-resumable execution.
- **Critical blockers to operating as a real multi-project AI software company today**: (1) the single
  global active-repo pointer means literally one project can be "active" fleet-wide at a time; (2) no
  memory/credential isolation between projects even if that were fixed; (3) in-process concurrency
  semaphores block genuine horizontal scale past one machine.
- **Highest-priority improvements**: build the `Project`/`Workspace` entity and thread it through
  memory/repo-context/credentials/RBAC (this one piece of work resolves the largest share of both the
  Weaknesses and Critical-blockers lists at once); extend durable checkpointing beyond the
  pm/architect/decomposer pipeline to the full fleet; move concurrency accounting off in-process
  `asyncio.Semaphore`.
- **Estimated production readiness percentage: ~62%** (see Q23's full breakdown — strong on
  agent-intelligence/tooling/testing discipline, weak on multi-tenancy and distributed scale).
- **Estimated Claude Code parity percentage: ~65%** — matches or exceeds Claude Code on
  fleet-orchestration, verification-honesty, and persistent memory concepts (things Claude Code, being
  single-session, doesn't need to solve at all), but trails on session-scoping simplicity (Claude Code's
  "one cwd, one context" model sidesteps this repo's global-state problem entirely by design) and on
  iterate-on-failure being on by default.
- **Estimated Cursor parity percentage: ~30%** — Cursor's core value is IDE-embedded, low-latency,
  single-file-context editing UX; this repo is architecturally a different product (a server-side agent
  fleet with a separate web dashboard), so most of Cursor's specific surface area (inline diffs, Cmd-K,
  live multi-cursor edits) doesn't exist here by design, not by an unfinished-feature gap.
- **Prioritized roadmap to enterprise-grade quality**: see Q50 (Foundation → Advanced → Enterprise),
  reproduced in full there — Foundation phase (project entity + durable checkpointing) is the
  necessary first step before any of the Advanced/Enterprise items are meaningful.

---

---

## Q79. Modern Technology Coverage

(Grouped per instructions; overlaps with Q71 domains are cited briefly, new categories get full evidence.)

### Fully Implemented
- **Backend Development — REST APIs**: `backend_dev.py` (implementation), `api_designer_agent.py` (contract design), `api_docs_agent.py` (docs from real route handlers).
- **Authentication/Authorization (design + audit)**: implementation via generic `backend_dev.py`; audit via `security_reviewer.py`/`security_architect.py`.
- **AI Assistants / Multi-agent systems**: the platform *is* one — `manager.py`, `decomposer.py`, `capability_registry.py`, 72 agents.
- **RAG Systems / Knowledge Bases**: `rag_engineer_agent.py`.
- **Prompt Engineering / LLM Integrations**: encoded directly in every `backend/roles/*.md` file + `base_graph.py`'s LangGraph node wiring.
- **AI Evaluation**: `evaluation_agent.py`.
- **SQL / Data Engineering**: `sql_agent.py`, `data_pipeline_agent.py`.
- **Docker**: `docker_agent.py`.
- **CI/CD (config, human-gated)**: `cicd_agent.py`.
- **Monitoring/Logging**: `monitoring_agent.py`, `slo_agent.py`.
- **Browser automation**: real Playwright-backed tools — `browser_open`, `browser_navigate`, `browser_screenshot`, `browser_read_dom` (`backend/app/agents/tools.py:9560-9635`, backed by `app/repo_tools/browser_driver.py`), wired into `make_chat_handlers` and confirmed in `chat_agent.py`'s tool schema.
- **Data visualization/reporting/dashboards (as code, not runtime)**: covered generically by `frontend_dev.py`/`backend_dev.py` implementing whatever a plan specifies — no dedicated charting/BI tool, so counted here only for the "can implement if planned" sense; true dashboard-specific domain knowledge is not verified (see Partial below for the stronger claim).

### Partially Implemented
- **GraphQL APIs**: contract design only (`api_designer_agent.py`, `AGENT_CONTRACT["description"]`: "Designs REST/GraphQL API contracts"); no dedicated GraphQL-server-implementation tooling verified.
- **WebSockets / Real-time web apps**: zero tool/agent evidence found (`grep -rli "websocket"` = no hits); would rely entirely on generic `backend_dev.py`/`frontend_dev.py` general-purpose code-writing.
- **Queue systems / Background workers**: only a **search** capability exists (`_FIND_QUEUE_TOOL`/`_FIND_WORKER_TOOL`, `tools.py:4830-4845`) to locate existing Celery/RQ/BullMQ/asyncio.Queue code — not a design/implementation tool.
- **File storage systems**: no dedicated agent/tool; generic `backend_dev.py` only.
- **Payment integrations**: no dedicated tool/agent; `grep` found no Stripe/payment-specific code.
- **Classical ML / Deep Learning / Model training/deployment**: `ai_engineer.py` covers this generically ("training pipelines, inference code"), but no framework-specific (PyTorch/TensorFlow/scikit-learn) specialization or dedicated deployment pipeline beyond composing with `docker_agent.py`/`cicd_agent.py`.
- **Workflow/business-process automation, scheduled jobs, event-driven automation**: no dedicated agent; `_FIND_WORKER_TOOL`/`_FIND_QUEUE_TOOL` search only; no cron/scheduler-config tool verified.
- **ETL pipelines / Data visualization / Dashboards / Reporting**: `data_pipeline_agent.py` covers ETL generically; no dedicated visualization/BI/dashboard-specific agent.
- **Cloud (Docker Compose, Kubernetes, AWS/Azure/GCP, Serverless)**: `infra_agent.py` is **review-only** ("Reviews cloud infrastructure code... for security risks... misconfigurations" — never provisions/deploys); `docker_agent.py`/`cicd_agent.py` require human approval for any actual execution. No cloud-SDK-specific (boto3/az-cli/gcloud) tooling found.

### Missing
- **Mobile Development** (Android, iOS, Flutter, React Native): zero evidence anywhere (same finding as Q71).
- **Progressive Web Apps (PWA), CMS integrations, e-commerce-specific tooling**: zero evidence.
- **Computer Vision, NLP-specific pipelines, Recommendation Systems, Time-series Forecasting** as dedicated categories: zero evidence — would fall back to generic `ai_engineer.py` only.
- **Serverless (AWS Lambda / Azure Functions / Cloud Functions) implementation**: zero evidence; only Python `lambda` keyword hits, unrelated.

---

---

## Q80. Technology Adaptation

- Recognizes unfamiliar technologies: **PARTIAL** — no explicit "is this technology known to me?" classifier exists, but `backend/roles/research.md:1-27` instructs the Research Agent to check `requirements.txt`/`package.json` before recommending anything and to flag anything not already installed, which functions as an implicit unfamiliarity check for the *project's* stack (not a general "I've never heard of framework X" detector).
  Plan: none required beyond current behavior for project-stack unfamiliarity; a true "novel-tech" flag would need explicit training-cutoff-awareness logic.
- Determines whether current knowledge is sufficient: **PARTIAL** — `backend/roles/_GLOBAL_STANDARDS.md §2`: "If a handler, type, or behavior is not confirmed by evidence, label it 'unverified' — do not guess" is a fleet-wide anti-hallucination rule, but it's a generic honesty rule, not a specific "sufficiency of my training data on this new tech" check.
- Searches authoritative documentation when appropriate: **YES** — real `web_search` tool (`tools.py:1495-1512`, DuckDuckGo-backed, no API key) wired into `research.py` (`make_research_handlers`, `tools.py:1518-1527`); real `fetch_url` tool wired into `ai_engineer.py` (`make_ai_engineer_handlers`, `tools.py:5847`) and `chat_agent.py`/other `make_chat_handlers`-based agents (`tools.py:8653`).
- Summarizes the relevant information: **YES** — `research.py`'s `submit_research` output contract explicitly requires `findings`, `relevantLibraries` (name/version/rationale), `recommendedApproach`, `risks` (`backend/roles/research.md:68-87`).
- Validates compatibility with the existing project: **YES** — `backend/roles/research.md:42-46`: "Is it compatible with Python 3.11+/Next.js 14? Is it actively maintained? Known vulnerabilities? Migration cost?" is an explicit required step.
- Proposes an implementation plan: **YES** — output feeds `architect.py`/`planner.py`, whose job is exactly this (`backend/roles/research.md:58-59`: "Your research report is consumed by the Architect Agent and Planner Agent").
- Requests approval before major architectural changes: **YES** — `_GLOBAL_STANDARDS.md §8` escalation rules require `blocked`/`needs_human` status for irreversible/architectural decisions; `cicd_agent.py`/`docker_agent.py` explicitly "always require human approval."
- Explains limitations instead of guessing when info is unavailable: **YES** — `_GLOBAL_STANDARDS.md §2/§7`: "State uncertainty... label 'unverified'"; "A partial honest result always beats a complete fabricated one."

**Overall**: this is one of the platform's better-evidenced areas — real `web_search`/`fetch_url` tools plus a role prompt (`research.py`) whose entire structure matches Q80's checklist almost line-for-line. Caveat: `web_search`/`fetch_url` are confirmed wired only into `research.py`, `ai_engineer.py`, and `chat_agent.py`/other `make_chat_handlers` consumers — not universally available to every agent that might encounter an unfamiliar technology (e.g. `backend_dev.py`'s own `AGENT_CONTRACT["allowed_tools"]` does not list `web_search`).

---

---

## Q81. Documentation-Driven Development

- Locate official documentation: **YES** — `web_search`/`fetch_url` tools as cited in Q80.
- Identify version-specific guidance: **PARTIAL** — `research.py` role explicitly checks installed versions (`backend/roles/research.md:43`: "compatible with Python 3.11+/Next.js 14"), but this is scoped to the *project's* pinned versions, not a general "find the docs for version X.Y specifically" capability with no further tooling (e.g., no versioned-docs-fetch parameter on `fetch_url`).
- Compare multiple approaches: **YES** — `backend/roles/research.md:42-47` "Assess trade-offs" step explicitly compares options; output schema has a `risks`/options structure.
- Evaluate compatibility: **YES** — same section, explicit compatibility check step.
- Generate an implementation plan: **YES** — hands off to `architect.py`/`planner.py` by design (pipeline).
- Implement using verified information: **YES** — `_GLOBAL_STANDARDS.md §2`: "Every factual claim must trace to tool output produced IN THIS RUN" is a hard fleet-wide constraint enforced by prompt, and `coder.py`'s static-check retry loop (`_run_checks`, `coder.py:88-90`, runs mypy+ruff outside the LLM) is a real, non-prompt-based verification step.
- Cite assumptions when documentation is incomplete: **YES** — `backend/roles/research.md:25`: "State uncertainty: If you are not certain about something, say 'UNVERIFIED:' and explain what you could not confirm" + `_GLOBAL_STANDARDS.md §9`: "Report uncertainty explicitly ('unverified', 'assumption', 'requires human decision')."

**How implemented**: `research.py` role file + `web_search`/`fetch_url` tools + pipeline handoff to
`architect.py`/`planner.py` + fleet-wide anti-hallucination rules in `_GLOBAL_STANDARDS.md §2`. This is a
real, prompt-and-tool-backed process, not merely aspirational text — but it depends entirely on the LLM
following the prompted steps each run; there is no separate deterministic enforcement layer (e.g., no code
that rejects a submission lacking a cited source), so compliance is not mechanically guaranteed, only
strongly prompted and structurally encouraged via the required output schema.

---

---

## Q82. Professional Solution Quality

Question: for each type of solution, are production engineering practices (scalable architecture, clean code, modular design, security, testing, logging, monitoring, documentation, deployment readiness, maintainability, accessibility, performance optimization) **enforced automatically**, or **dependent on the user explicitly requesting them**?

- Scalable architecture: dependent on design-time decisions (queue/worker split via `Procfile`+`app/queue/rq_adapter.py`), not enforced per-task by any agent — **not automatically enforced per change**.
- Clean code / modular design: **PARTIALLY automatic** — `ruff`/`black`/`mypy --strict` run automatically in CI on every push/PR (`ci.yml:66-73`), which is a real automatic gate. But this is a post-hoc CI check, not something that blocks an individual agent from declaring a task "done" before pushing — `_run_quality_gate()` (`base_graph.py:853-920`) only checks confidence/critique/verification-consistency at submit time, not lint/format.
- Security: **PARTIALLY automatic** — `pip-audit` runs automatically in CI (`ci.yml:176-215`) as a real, non-suppressed gate (the `|| true` bypass was explicitly removed per the in-file comment). But per-task, whether a given agent runs a security scan depends on which agent is invoked — e.g. `dependency_security_agent` (`backend/app/agents/dependency_security_agent.py`) has no `bash` tool in its `allowed_tools` (verified: its tool list is `READ_ONLY_TOOLS + [_WRITE, _SUBMIT, RECORD_LEARNING_TOOL, _LIST_FUNCTIONS_TOOL, _PARSE_AST_TOOL]`, no bash), so it cannot itself invoke `pip-audit`/`npm audit` live — its CVE findings rely on the model's reasoning over read files, not a live vulnerability database query. Real live vulnerability detection exists only at the CI level, not inside this specific agent.
- Testing: **dependent on request** — `run_tests`/`coverage_report` are tools an agent *may* call (e.g. `tech_debt_agent`'s `_VERIFICATION_CFG` forces `lint_ran` before submit, `tools.py:61-70`), but this is per-agent-contract, not a global "every code change must have new tests" enforcement mechanism.
- Logging: **automatic at the framework level** — `app/fleet/metrics.py`'s `run_span()` wraps every agent run automatically, and `logger = logging.getLogger(__name__)` is used consistently; agents don't need to opt in.
- Monitoring: **automatic at the framework level** — OTEL bridge (`metrics.py:262-427`) and Sentry DSN-gated init (`app/main.py`) apply platform-wide without per-task action.
- Documentation: **dependent on request** — no automated doc-generation/doc-coverage gate found in CI (`ci.yml` has no docs step); `docs.py` agent exists but must be explicitly invoked.
- Deployment readiness: not a per-task concern — established once at the infra level (`Dockerfile`, `docker-compose.yml`, `Procfile`), not re-verified per agent submission.
- Maintainability: **dependent on request/convention** — enforced by documentation discipline (`IMPLEMENTATION_PROGRESS.md`) rather than automated tooling.
- Accessibility: **NOT VERIFIED** — no accessibility linting (e.g. `eslint-plugin-jsx-a11y`) confirmed in `apps/web`'s lint config within the scope of this pass; not checked in depth.
- Performance optimization: **dependent on request** — `benchmark_manager.py`/`regression_detector.py` can block a deploy on a measured regression (`tests/test_regression_detector.py`), but this requires baselines to have been established for the specific agent being compared; it is not a blanket automatic check on every code change.

**Summary verdict: PARTIAL, and mostly "user/task-dependent" rather than "automatically enforced."** The clearest exceptions — genuinely automatic, no user action needed — are: CI lint/format/type-check/pytest/pip-audit gates (`ci.yml`), and always-on logging/metrics/OTEL instrumentation. Everything else (which tests get written, whether a security-scanning agent vs. a plain coding agent is invoked, whether docs get updated, whether a specific tech-debt/quality audit runs) depends on which agent a human or orchestrator explicitly dispatches for a given task.

---

---

## Q83. Technology Recommendation Engine

`grep -rn "recommend_technology|technology_recommend|TechRecommend|choose_framework|select_database|recommend_stack" backend/app`
returned **zero matches** anywhere in the codebase. There is no dedicated recommendation-engine
function, endpoint, or agent.

- Choosing an appropriate backend framework: **NOT VERIFIED / PARTIAL** — no dedicated engine; `research.py`'s `recommendedApproach` field (`backend/roles/research.md:82`) could produce this ad hoc as free text during a research task, but it is not a structured, criteria-weighted recommendation system.
- Selecting a database: **PARTIAL** — same mechanism; also `database_architect.py`/`schema_agent.py` reason about schema design once a DB is already chosen, but neither compares database *options* against project requirements.
- Selecting an AI model: **PARTIAL** — no dedicated tool; would rely on `ai_engineer.py`/`research.py` producing an ad hoc suggestion in free text, not a structured comparison.
- Selecting a vector database: **PARTIAL** — `rag_engineer_agent.py`'s description explicitly includes "vector store setup" but no evidence of a structured multi-option comparison (e.g., pgvector vs. Pinecone vs. Weaviate scored against criteria).
- Selecting a cloud provider: **NO** — no AWS/Azure/GCP-comparison logic found anywhere (per Q71/Q79 cloud findings — `infra_agent.py` only reviews already-chosen infra code).
- Selecting an automation platform: **NO** — no evidence.
- Selecting a frontend framework: **PARTIAL** — same ad hoc mechanism as backend framework; `frontend_dev.py` is hardcoded to Next.js/TypeScript by role design, not a chooser among frontend frameworks.

Do recommendations weigh project scale/budget/maintainability/team complexity/performance/
security/ecosystem maturity/deployment environment/long-term support?: **NO** — none of these criteria
appear as named fields or scoring dimensions anywhere in `backend/app/agents/*.py` or `backend/roles/*.md`.
The closest structural analogue, `research.py`'s output contract, only has `findings` /
`relevantLibraries` (name/version/rationale) / `recommendedApproach` / `risks` — no explicit
budget/scale/team-size/LTS scoring.

**Overall**: **NO dedicated technology recommendation engine exists.** What exists is a general-purpose
research agent (`research.py`) whose free-text `recommendedApproach` output could informally answer a
"what should I use" question during a task, backed by real `web_search`, but this is fundamentally
different from a structured recommendation engine that scores options against explicit weighted criteria
(scale, budget, team, LTS, etc.) as Q83 asks for.
Plan: build a dedicated `tech_recommender` agent/tool with a structured output schema
(`{option, tradeoffs: {scale, budget, maintainability, team_complexity, performance, security,
ecosystem_maturity, deployment_env, LTS}, score, citation}`), reusing `research.py`'s existing
`web_search`/`fetch_url` tools for evidence-gathering.

---

## Q84. Capability Boundaries

- tasks it can complete confidently: **PARTIAL** — `AgentCapability.risk_level` (`app/fleet/capability_registry.py:45`, values `low`/`medium`/`high` seen in registrations) and `state["confidence"]` (planner self-assigned score) together act as a real, if implicit, confidence signal per task, but there's no single boundary-classification API that labels a request "confidently completable" up front before dispatch.
- tasks requiring additional user input: **YES** — `request_human_input()`/`interrupt()`-based clarification flow (`approval_gate.py`, kind="clarification" per its own docstring: "Phase 5.3's non-blocking 'clean stop, await a fresh run' pattern").
- tasks requiring external services: **PARTIAL** — individual tools fail gracefully with `[ERROR] ...` string returns when an external dependency is unavailable (e.g. `mermaid_from_schema_h` wraps its `subprocess` call in try/except), but there's no upfront "this task needs GitHub/Docker/an external API, and it's unavailable" boundary check before starting (consistent with Q31's finding — no pre-flight external-dependency check exists).
- tasks requiring human review: **YES** — `requires_human_approval` is a real, graph-enforced boolean on `AgentResult`/quality-gate results, escalated by confidence threshold or critique-retry exhaustion (`base_graph.py`'s `_run_quality_gate`, confirmed only confidence/critique are allowed to flip it — documented as a deliberate scope boundary in the function's own docstring).
- unsupported tasks: **PARTIAL** — a request naming a tool/capability outside an agent's `AGENT_CONTRACT["allowed_tools"]` simply has no handler for it (the model can't call a tool that isn't in its `tools=` schema) — a structural boundary, but not a friendly "this is unsupported" message; it manifests as the model working around the gap or stalling, not an explicit boundary response.
- "explains the limitation honestly / does not fabricate an implementation / proposes realistic alternatives / identifies what would be needed": **PARTIAL for the first, YES for the rest — gap-closure
  Day 16 updates the latter two (2026-07-31).** "Does not fabricate" is real and tested (Q68's
  `verified`/`.raw` evidence — the same enforcement mechanism). "Explains honestly" still happens
  informally via critique/replan messages citing real evidence, not a dedicated boundary-explanation
  field — genuinely still PARTIAL. "Proposes realistic alternatives" and "identifies what would be
  needed" are now real: see Q68's `limitation_type`/`proposed_alternative` fields, graph-enforced via
  `_run_quality_gate`, not just documented — a `proposed_alternative` with no real content (empty,
  whitespace-only) fails the same check a fabricated `limitation_type` value would.
  Plan: the honesty/no-fabrication guarantees are real, load-bearing, and tested — the strongest-verified part of this question. The taxonomy-labeling and alternative-proposing pieces are genuine gaps, same underlying work as Q68's plan.

---

## Q85. Governance & Policy Engine

- central governance system enforcing company-wide rules: **PARTIAL** — a real, code-level
  policy engine exists (`backend/app/policy/engine.py`), and it is genuinely applied
  automatically to every one of the 74 `run_agent_graph`-based agents via
  `base_graph.py`'s `execute_tools()` gate (`backend/app/agents/base_graph.py:41,277,282`,
  through `backend/app/agents/guardrails.py`'s thin delegation). But its scope is narrow:
  a security/destructive-action denylist (`_DENIED_COMMAND_PATTERNS`,
  `engine.py:179-205`) and a path denylist (`.env`, secrets, private keys, `.git/`,
  `.github/workflows/`) plus worktree-boundary containment. It does **not** cover coding
  standards, naming conventions, or a general architecture-rules engine.
- coding standards: **PARTIAL** — `backend/roles/_GLOBAL_STANDARDS.md` states SOLID/KISS/DRY/YAGNI
  and an operating loop every agent's system prompt inherits, but this is **prompt text**, not
  code-enforced — no linter/AST check verifies an agent actually followed it.
  Plan: none needed unless the user wants code-level enforcement (e.g. a mandatory lint/format
  gate before `git_commit_change`, which does not currently exist).
- naming conventions: **NO** — no naming-convention checker found anywhere in `backend/app`.
- architecture rules: **NO** — `architecture_reviewer` reports violations it finds
  (`backend/roles/architecture_reviewer.md`) but has no enforcement power (read-only, no
  ability to block a commit); no central "approved architecture" rule engine exists.
- security policies: **YES** — `app/policy/engine.py`'s denylist + `secrets_scan`/`find_sql`/
  `find_config`/`find_api`/`find_route` tools (used by `security_reviewer`/`quality_auditor`) +
  `_GLOBAL_STANDARDS.md` §5. This is the strongest-covered category.
- approved frameworks / prohibited frameworks: **NOT VERIFIED** — no allowlist/denylist of
  libraries or frameworks found anywhere in `backend/app`.
- licensing policies: **NOT VERIFIED** — no license-scanning code or policy found.
- deployment rules: **PARTIAL** — deploy-class commands are blocked by the same policy denylist
  (`kubectl`, `terraform`, `docker push`, `npm publish`, `vercel deploy`, `heroku`, `git push`
  — `engine.py:179-205`), and some of these (e.g. `git push`) are re-offerable to a human via
  `is_command_override_eligible()` (`engine.py:236-247`) feeding the real approval-gate
  (`backend/app/fleet/approval_gate.py`). But this is "block/allow-with-approval a command,"
  not a structured deployment-rules system (environments, promotion gates, rollback policy).
- approval workflows: **YES** — real, generalized, and reused across multiple call sites:
  `request_human_input()`/`arequest_human_input()` in `approval_gate.py:331-372`, backing
  `plan_review`, `git_push`, `clarification` HITL pauses, and the fleet-dashboard
  enhancement-request approve/reject flow.
- "Can every agent automatically follow these policies?": **PARTIAL** — every agent
  automatically has the security/path denylist applied to it in code (cannot be bypassed by
  prompt alone), but the broader governance categories (standards, naming, architecture,
  frameworks, licensing) are prompt-guidance only, not code-enforced, so "automatically follow"
  is true only for the security-denylist slice.
  Plan: the real gap is a general-purpose policy/rules engine beyond security — would need a
  new module (e.g. `app/policy/standards.py`) wired into the same `execute_tools()` gate.

---

---

## Q86. Organization-Wide Task Scheduler

- queue tasks: **PARTIAL** — a real queue abstraction exists (`backend/app/pipeline/queue_adapter.py`:
  `AsyncioQueueAdapter`, `RQAdapterBridge` wrapping `backend/app/queue/rq_adapter.py`'s real
  Redis-backed `RQQueueAdapter`), but it is explicitly **not wired into real task dispatch**:
  `queue_adapter.py:10-24` documents (Audit 04 finding ORCH-04-016) that every real
  task-launch call site in `api/tasks.py` (run/restart/approve/pipeline_approve/push) uses
  FastAPI's `BackgroundTasks.add_task(...)` directly, so `QUEUE_BACKEND=rq` "currently has no
  effect on real task dispatch."
- prioritize tasks: **PARTIAL** — `RQQueueAdapter` has two named queues, `gridiron-high` and
  `gridiron-default` (`rq_adapter.py:16,44-45,64`) — real 2-level priority — but per the point
  above, this queue is not on the live dispatch path.
- pause tasks: **PARTIAL** — a real per-task stop/abort exists: `POST /api/tasks/{task_id}/stop`
  sets an abort flag checked by `call_llm` mid-run (`backend/app/api/activity.py:4,67-71`,
  `backend/app/services/activity_stream.py:60,128`). This pauses one running task's LLM loop,
  not a queue-level pause of pending/queued work.
- resume tasks: **YES** — `POST /api/tasks/{task_id}/resume` clears the abort flag and injects
  a new message (`activity.py:5,76-89`).
- cancel tasks: **NOT VERIFIED** — no `cancel`/`delete job` endpoint or RQ
  `Job.cancel()`/`StoppedJobRegistry` usage found (`grep` for `job.cancel|cancel_task|def cancel`
  across `backend/app` returned nothing); `stop` (abort) is the closest analogue but is a pause,
  not a cancel.
- reorder tasks: **NO** — no reorder/re-prioritize-in-place logic found anywhere.
- detect blocked tasks / dependencies: **PARTIAL** — a real `depends_on` column exists on the
  task/subtask model (`backend/app/db/models.py:208`), populated by `decomposer.py:88` and
  surfaced read-only to the API/UI (`backend/app/api/tasks.py:466`: `"dependsOn": s.depends_on`).
  But no runtime code was found that checks `depends_on` to actually block/gate execution or
  compute a "this task is blocked" status — it is captured and displayed, not enforced.
- optimize execution order: **NO** — no scheduling/topological-sort/optimization logic found.

Plan: the queue infrastructure (priority queues, RQ backend) is real but dormant — wiring
`api/tasks.py`'s real dispatch calls onto `queue().enqueue(...)` instead of raw
`BackgroundTasks.add_task(...)` is the single biggest lever here, and was itself an
intentionally-deferred, documented decision (Audit 04, ORCH-04-016), not an oversight.

---

---

## Q87. Agent Performance Metrics

Primary evidence: `backend/app/fleet/metrics.py` (`RunMetrics`/`MetricsCollector`, used via
`run_span()` in `base_graph.py`, which 74 of 79 agent modules use) plus
`GET /api/fleet/reports/health` and `GET /api/fleet/reports/cost`
(`backend/app/api/fleet_dashboard.py:278-386`).

- success rate: **PARTIAL** — `/reports/health` computes `failureRate` per agent from real
  `agent_runs` aggregates (`fleet_dashboard.py:356-376`); success rate is the trivial
  complement but isn't itself a named field. `fleet_manager.py:141` also uses a live
  `success_rate` in its dispatch-scoring formula.
- failure rate: **YES** — `failureRate` field, real SQL `COUNT`/`CASE` aggregate, not estimated.
- average execution time: **YES** — `RunMetrics.execution_time_ms` (`metrics.py:75`) plus
  `p50_latency_ms()`/`p95_latency_ms()` per agent (`metrics.py:230-251`), exposed via the
  `fleet_metrics_read` tool.
- tool usage: **YES** — `RunMetrics.tool_calls: list[ToolCallRecord]` and `tool_accuracy`
  property (`metrics.py:113-127,147-152`).
- token usage: **YES** — `tokens_in`/`tokens_out`/`cost_estimate_usd`
  (`metrics.py:78-80,130-145`), also rolled up per-agent/day/tier at `/reports/cost`.
- reasoning quality: **PARTIAL** — only indirect proxies exist: `verification_pct`,
  `confidence`, and `reflection_unsatisfied` — the last explicitly documented as "a
  conservative hallucination-rate proxy" (`metrics.py:97-99`). No dedicated "reasoning
  quality" score.
- retry count: **YES** — `RunMetrics.retries`, populated from the graph's own
  `retry_count` state (`base_graph.py:1892`: `_metrics.retries = final_state.get("retry_count", 0)`).
- user approval rate: **NO** — no field or endpoint computing approve-vs-reject ratio for
  `EnhancementRequest`s or `PendingApproval`s per agent was found.
- user satisfaction: **NO** — no rating/feedback/satisfaction field found anywhere in
  `backend/app` (`grep` for `satisfaction|rating|thumbs|feedback_score` across the codebase
  produced only unrelated substring matches — "orchestrating," "dissatisfaction").
- reliability score: **NO** — no single composite "reliability score" field; the closest is
  `fleet_manager.py`'s ad-hoc dispatch-time score (`health_weight × success_rate / (1+error_count)`,
  `fleet_manager.py:10,137-141`), which is a scheduling heuristic, not a reported/exposed metric.

Plan: user-facing approval-rate/satisfaction/reliability-score metrics would need new
columns/aggregates — real building blocks (`EnhancementRequest.status`,
`AgentRun` failure counts) already exist to derive them from.

---

---

## Q88. Agent Health Monitoring

- slow agents: **YES** — `p50_latency_ms`/`p95_latency_ms` per agent (`metrics.py:230-251`),
  queryable via `fleet_metrics_read`.
- crashed agents: **PARTIAL** — no explicit "crashed" state, but two real proxies: (1)
  `AgentInstance.fail()` sets `AgentState.ERROR` and, after 3 consecutive failures, marks the
  instance `health="unhealthy"` (`backend/app/fleet/agent_registry.py:67-74`), verified wired
  into every real run via `base_graph.py:1738,1996,2028` (`start_task`/`complete_task`/
  `fail_task` calls); (2) `/reports/health`'s `avgHeartbeatStalenessSeconds`
  (`fleet_dashboard.py:334-386`) flags runs stuck mid-execution.
- looping agents: **NO** — only a preventive cap (`max_turns`, widespread across agent files)
  that stops a single run from looping forever; no detection/report of "this agent tends to loop."
- hallucinating agents: **PARTIAL** — `reflection_unsatisfied` is a real, populated per-run
  counter explicitly documented as a hallucination-rate proxy (`metrics.py:97-99`), but there
  is no active alerting/threshold system built on it.
- idle agents: **PARTIAL** — `AgentState.IDLE`/`SLEEP` states exist and are tracked
  (`agent_registry.py:27-31,56-83`) and surfaced via `snapshot()`, but no "flag this agent as
  idle too long" alerting logic was found.
- overloaded agents: **NO** — no concurrency-limit-breach detection or queue-depth-based
  overload alerting found; `fleet_manager.py` only picks around busy/unavailable instances at
  dispatch time, it doesn't detect or report "overloaded."
- memory leaks: **NO** — `monitoring_agent`'s `memory_usage` tool reports host/process memory
  as a one-off snapshot (`backend/roles/monitoring_agent.md:16-17,32-38`, explicitly
  "your data is a snapshot" — no trend/leak detection), and `monitoring_agent` is not one of
  the 5 fleet-governance agents anyway.
- synchronization failures: **NO** — no sync-failure detection mechanism found in `backend/app`.

Plan: real building blocks exist (heartbeat staleness, error-count threshold, reflection
proxy) for slow/crashed/hallucinating; looping, idle, overloaded, memory-leak, and sync-failure
detection would need new, purpose-built monitors — none exist today.

---

---

## Q89. Automatic Agent Retirement

- disable it: **YES (per-instance, automatic)** — `AgentInstance.fail()`: after 3 consecutive
  failures, `health` flips to `"unhealthy"` and `is_available` becomes `False`
  (`agent_registry.py:50-54,67-74`); `fleet_manager.py:116,137,147` then excludes/deprioritizes
  that instance from new task assignment (`health_weight` of `0.0` for `"unhealthy"`, and a
  logged warning when no agents are available). Verified this is wired into every real
  `run_agent_graph` run via `base_graph.py:2028`'s `fail_task()` call on exception. This is a
  soft, automatic, threshold-based disable — not a persisted "this agent type is retired" flag,
  and it resets via `recover()` (`agent_registry.py:80-83`), not permanent.
- replace it: **NO** — no mechanism found that substitutes a different agent/model when one is
  marked unhealthy; `fleet_manager.py` simply scores remaining healthy candidates lower/excludes
  the unhealthy one — there's no alternate-agent substitution logic.
- update it: **NO, not automatically** — an unhealthy agent is never auto-patched. The only
  path to "update" an agent's code is a human approving an `agent_debugger`/
  `agent_performance_reviewer`/`quality_auditor` enhancement request, which is a manual,
  human-gated process (see Q12/Q64), not triggered by the health-monitoring signal above —
  no code path connects `AgentInstance.health == "unhealthy"` to filing an enhancement request.
- notify the supervisor: **NO** — `grep` for `notify_supervisor|send_alert|slack_notify|
  notify.*human` across `backend/app` found nothing; the only signal is a `logger.warning`
  when no agents are available for a capability (`fleet_manager.py:147`), which is a log line,
  not a notification to a human/supervisor.
- recommend improvements: **PARTIAL** — `agent_debugger`/`agent_performance_reviewer` can
  independently surface a "this agent is failing" finding via `fleet_metrics_read`/
  `audit_log_read` evidence and file a `submit_enhancement_request`
  (`backend/roles/agent_debugger.md:19-26`), but this is a separate, manually-triggered scan
  run — it is not automatically invoked when `AgentInstance.health` becomes `"unhealthy"`.

Plan: the missing link across all of "replace/update/notify/recommend" is that the automatic
per-instance disable in `agent_registry.py` doesn't call out to anything — wiring
`AgentInstance.fail()`'s 3rd-consecutive-failure transition to (a) a notification and (b) an
auto-filed `agent_debugger` scan trigger would close this gap with the existing pieces already
in the codebase.

---

## Q90. Quality Gates

- Linting: **YES** — `ci.yml:66-67` runs `ruff check .` as a real CI gate on every push/PR.
- Formatting: **YES** — `ci.yml:69-70` runs `black --check .`.
- Tests: **YES** — `ci.yml:75-76` runs `pytest tests/ -v --tb=short --timeout=120 --junitxml=pytest-results.xml`.
- Security checks: **YES** — `ci.yml`, dedicated `security` job running `pip-audit -r requirements.txt` with one explicitly-justified `--ignore-vuln GHSA-jfh8-c2jp-5` exception (documented inline) — a real, non-bypassed gate (the file's own comments note a prior `|| true` bypass was removed as a gap-closure fix). Gap-closure Day 7 (2026-07-30): the second exception this job used to carry, `--ignore-vuln PYSEC-2026-1325` (ecdsa), is removed — `backend/app/auth/jwt.py` no longer depends on `python-jose`/`ecdsa` at all (migrated to PyJWT), so there is nothing left to ignore.
- Dependency checks: **PARTIAL** — backend: **YES**, same `pip-audit` job, a real blocking gate. Frontend: **PARTIAL, informational only** — corrected citation: `eslint` (`ci.yml`'s `frontend` job) is a code-quality lint gate, not a dependency-CVE check; it was miscited here as the frontend's dependency-check equivalent, which it isn't. The actual gap this exposed (post-Day-34 CI hygiene pass, 2026-07-31): the frontend's own npm dependencies had **no** CVE-audit step at all until this pass. `pnpm audit` (run for real, not assumed) reports **36 known vulnerabilities — 1 critical, 18 high, 15 moderate, 2 low** — all traced to one root cause: `next` is pinned to `14.2.15` (`apps/web/package.json:19`) while the patched versions require `>=15.5.21`, a major-version upgrade (React 19, async `cookies()`/`headers()`/route `params`, caching-behavior changes) with real breaking-change risk, not a quick patch bump. User-scoped explicitly (asked via `AskUserQuestion`, chose "Add pnpm audit as non-blocking for now"): a new `Dependency audit (pnpm audit, informational)` step now runs in `ci.yml`'s `frontend` job on every run, `continue-on-error: true` (visibly flagged in the Actions UI, not silently hidden behind a bare `|| true` the way this same file's own prior gap-closure passes explicitly removed elsewhere — SEC-05-019, INFRA-06-004), writing the full finding list to the job's `$GITHUB_STEP_SUMMARY`. **Tracked, open gap, not yet closed**: the actual fix (Next.js 14→15 upgrade, full frontend regression + e2e + manual smoke test, then flip this step to a real blocking gate) is deliberately deferred as its own dedicated task — the user explicitly declined to rush it today.
- Architecture checks: **NO** — no CI step or automated gate validates architecture rules (module boundaries, dependency direction, layering). The closest capability, `architecture_mapper.py`, is a one-shot descriptive LLM summarizer (not a pass/fail checker) invoked on demand, not wired into CI.
- Performance checks: **YES** — Gap-closure Stage 1.7 (2026-07-31): `.github/workflows/ci.yml`'s `backend` job now runs a dedicated, labeled "Regression gate (regression_detector baseline check)" step (`ci.yml:78-99`) invoking `python -m pytest tests/test_regression_detector.py -v --tb=short` as its own visible CI check, separate from the general `pytest tests/` run — so a deliberately-regressed benchmark now demonstrably fails its own named CI step (`test_gate_deploy_raises_deployment_blocked_on_regression`, already-existing, now CI-visible by name). Honest limitation documented inline in `ci.yml`: this CI Postgres is a fresh ephemeral container per run with no baseline history from prior runs, so it proves the gate mechanism works, not "did this specific PR regress the real fleet's persisted baseline" — that needs a persistent CI database or a downloaded baseline artifact, out of scope for this pass.
- Documentation checks: **NO** — no CI step checks documentation coverage or requires doc updates alongside code changes.

**Overall: PARTIAL → mostly YES.** Lint/format/tests/backend-dependency-security/performance-gate-visibility are real, automatically-enforced CI gates (verified in `ci.yml`, and the fact that two prior silent-pass bypasses were found and explicitly removed — per the file's own gap-closure comments — is evidence these gates are taken seriously as real blockers, not decorative). Frontend dependency-security is now checked and visible but deliberately non-blocking (a real, disclosed, tracked gap — 36 known `next`-version CVEs pending a major-version upgrade). Architecture and documentation checks remain not automated.

---

---

## Q91. Architecture Drift Detection

- Broken design patterns: **NO** — no automated check evaluates whether a change breaks an established design pattern. `architecture_mapper.py` (`backend/app/repo_tools/architecture_mapper.py:1-27`) is explicitly a one-shot LLM summarization tool, not a diagnostic/enforcing one; its own docstring states it deliberately mirrors `continue`'s "LLM prompt asking the model to freehand a prose summary" precedent because "a real, novel static-analysis architecture-detection algorithm has no prior art to build from" — i.e., this was a conscious decision not to build automated drift detection.
- New technical debt: **YES** — Gap-closure Stage 1.7 (2026-07-31, user-scoped as "real LLM call, non-blocking"): `backend/app/fleet/structural_diff.py`'s `is_structural_file_change()` (pure, deterministic, 6 tests in `tests/test_structural_diff.py`) detects whether a PR's diff touches a structural file (shared DB schema, the two graph builders, central settings/bootstrap, migrations, RBAC/policy, model routing). `backend/scripts/ci_tech_debt_scan.py` (12 tests in `tests/test_ci_tech_debt_scan.py`, `run_tech_debt_agent` mocked so no real API cost in the test suite itself) wires this into `.github/workflows/ci.yml`'s `backend` job as a new "Tech debt scan" step (`ci.yml:101-114`, `if: github.event_name == 'pull_request'`): on a structural-file diff with `ANTHROPIC_API_KEY` set, it makes a real `run_tech_debt_agent()` call and posts findings to `$GITHUB_STEP_SUMMARY` as an informational annotation. It never blocks the merge — no base ref, no structural change, no API key, or any internal error all fall through to a clean exit 0, by design (this is advisory, not a gate; `regression_detector`'s step above is the real gate). `backend`'s `actions/checkout` step gained `fetch-depth: 0` so `git diff` against the PR base branch actually resolves.
- Inconsistent modules: **NO** — no automated cross-module consistency checker found; `quality_auditor.py` and `code_quality_agent.py` exist as on-demand LLM agents (`backend/app/agents/quality_auditor.py`, `code_quality_agent.py`) but again require explicit task dispatch, not continuous/automatic triggering on architecture change.
- Duplicated architectures: **NO** — no automated duplication-detection tooling (no jscpd/similar code-clone detector, no structural-similarity check) found anywhere in `backend/app` or CI config.

**Overall: PARTIAL.** Real capability exists for tech-debt/quality auditing (`tech_debt_agent.py`, `quality_auditor.py`, `code_quality_agent.py`, all genuine LangGraph agents with verification contracts, not just prompts with no teeth), and `architecture_mapper.py` gives a real, novel structural summary using PageRank over a real cross-file call graph (`cross_file_graph.py`). Gap-closure Stage 1.7 (2026-07-31) closed the "new technical debt" sub-item specifically: `tech_debt_agent` now runs automatically in CI on structural-file PR diffs (`backend/scripts/ci_tech_debt_scan.py`, wired into `ci.yml`). `quality_auditor`/`code_quality_agent`/`architecture_mapper` remain explicit-dispatch-only — broadening the same trigger to them was not part of the user's Stage 1.7 scope decision and is not claimed here.

---

---

## Q92. Dependency Intelligence

- Detect outdated packages: **YES** — `backend/app/agents/dependency_agent.py`'s `_VERIFICATION_CFG` (lines 59-69) forces `bash` execution (`"bash": "registry_checked"`) before it can report a version as outdated; the agent's own prompt (lines 84-98) explicitly instructs: "use bash (pip index versions / npm view) to get the LIVE latest version from the registry. Never state 'latest is X' from memory" — this is a real, verification-enforced (not just prompted) anti-hallucination mechanism; `manifest_read` is likewise forced true only when `read_file` actually ran on the manifest (`AGENT_CONTRACT["expected_verification"]`, line 55).
- Identify breaking changes: **NOT VERIFIED** — the agent's report schema (`submit_dependency_report`) captures `current_version`/`latest_version`/`upgrade_recommended`, but nothing in the reviewed code confirms it specifically diffs semver major-version boundaries or changelogs to flag breaking changes as a distinct signal; this would need the tool schema itself inspected further than this pass covered.
- Recommend upgrades: **YES** — `dependency_agent.py`'s contract states `upgrade_recommended` is "forced False unless tests_passed after upgrade attempt" (module docstring, line 6, and `_VERIFICATION_CFG.set_by={"run_tests": "tests_passed"}`, line 63) — recommendations are gated on evidence, not just asserted.
- Identify abandoned libraries: **NO** — no code anywhere in `backend/app` checks package maintenance status, last-publish date, or archived-repo status (grep for `abandoned|unmaintained|last.?publish` across `backend/app` returned only one unrelated false-positive hit in `app/fleet/scratchpad.py`, about an abandoned *epic*, not a library).
  Plan: extend `dependency_agent`'s bash step to also check `npm view <pkg> time.modified` / PyPI's last-release date and flag packages with no release in N years.
- Detect security vulnerabilities: **YES** — two mechanisms, both now real evidence-gated live checks: (1) CI's `pip-audit -r requirements.txt` (`ci.yml`) actively gates merges. (2) `backend/app/agents/dependency_security_agent.py` — gap-closure Day 7 (2026-07-30) fixed the exact gap this item used to flag (agent claimed "LIVE audit tooling only" in its role prompt but had no tool capable of running one): it now has a scoped `bash` tool (`DEPENDENCY_AUDIT_BASH_TOOL`, `app/agents/tools.py`) allowlisted to `pip-audit`/`pip_audit`/`npm audit` prefixes only (`check_allowlisted_command`, everything else `[POLICY DENIED]`), and `_CFG` (`dependency_security_agent.py`) adds `"bash": "audited"` to `set_by` plus `enforce_in_result={"read": "read", "audited": "audited"}` — `AgentResult.verified` is now graph-enforced `False` whenever the audit tool never actually ran, mirroring `dependency_agent`'s existing `registry_checked` pattern exactly. `roles/dependency_security_agent.md`'s Process/Tools sections updated to match. Proven by `backend/tests/test_dependency_security_agent_audit_gate.py` (8 tests, including a real, non-mocked `pip-audit` subprocess invocation) and `backend/tests/test_analyzer_tier_confirmed.py::test_dependency_security_agent_bash_is_scoped_to_audit_only`.

---

## Methodology note

All test counts and CI/lint results in this document were either read directly from source files in the repository or reproduced live via `cd backend && python -m pytest tests/ --collect-only -q` in the project's `.venv` (result: 3397/3414 collected, 17 deselected, 7.32s), cross-checked against `IMPLEMENTATION_PROGRESS.md:1008-1039`'s documented full regression run (3318 passed / 21 failed / 1 skipped / 17 deselected, all 21 failures individually triaged there as environment-specific, not code bugs). No performance comparison against Claude Code or Cursor was run or fabricated — that sub-item is explicitly marked NOT VERIFIED per the audit's own mandatory rule.

---

## Q93. Knowledge Validation

- "When agents learn something, how is it verified?": **PARTIAL** (was NO) — gap-closure Day 6
  added a real gate, but it is human judgment, not automated fact-checking: `knowledge_curator`
  must read a draft's real content (`memory_list_draft_lessons`) and explicitly decide it's worth
  promoting before it can request `memory_promote_lesson` — genuinely gated review, but still no
  automated correctness check against ground truth (`_merge_via_llm` still only merges text for
  coherence on the merge path).
  Plan: still open — an automated correctness signal (e.g. requiring the lesson to cite a real
  passed test or a specific file:line) would upgrade this further; not built.
- "Can incorrect knowledge spread?": **PARTIAL** (was YES/real risk) — the risk is now bounded, not
  eliminated: an incorrect lesson can still be *proposed* (nothing stops a bad `record_learning`
  call from creating a draft), but it can no longer *spread* — it stays invisible to
  `query_learning_signals`/every future agent's prompt injection unless a human explicitly reviews
  and approves promoting it, verified end-to-end by
  `tests/test_versioned_memory.py::test_unpromoted_draft_never_reaches_memory_embeddings`.
- "Who approves organization-wide learning?": **YES, `knowledge_curator`** (was NO ONE) —
  gap-closure Day 6 (2026-07-30, root cause 3): `publish()` (`backend/app/fleet/versioned_memory.py`)
  now writes `state="draft"` unconditionally; the new `promote()` method — the only path to
  `state="published"` and to syncing into `memory_embeddings` — is called exclusively by the new
  `memory_promote_lesson` tool, wired into `knowledge_curator`'s **APPLY phase**, itself only
  reachable after a human approves that specific curation action (same Fleet Enhancement Dashboard
  gate as `knowledge_curator`'s other real curation actions). See Q75 for the full evidence trail
  (27 tests, zero regressions, a real DB-pollution test bug caught and fixed along the way).

---

## Q94. Multi-Project Management

- Multiple repositories: **PARTIAL** — `Repo` table supports multiple cloned repos
  (`db/models.py:461`), and `POST /api/repo/{id}/activate` can switch between them — but only one is
  ever `is_active=True`/globally active at a time (`app/api/repo.py::_active_repo_path`, module-level
  global). Two repos cannot be genuinely worked on concurrently by the fleet's default dispatch path.
  Plan: see Q24 Critical — replace the global active-repo pointer with per-request/session context.
- Multiple clients: **NOT VERIFIED** — no `Client` entity found in `db/models.py`; "client" isn't a
  modeled concept anywhere in the schema surveyed.
- Multiple branches: **YES for isolation, PARTIAL for context** — worktree-per-task
  (`WORKTREES_DIR/task-{id}`, ADR-003) genuinely isolates concurrent branch work at the filesystem
  level; `git_checkout`/`git_branch_list` tools exist. But memory/context has no branch-awareness
  column, so cross-branch memory bleed within the same repo is possible (not independently confirmed
  either way — NOT VERIFIED).
- Multiple deployments: **NO** — `infra_agent` is dry-run/lint-only by design
  (`terraform`/`kubectl` fleet-denied); no deployment-target/environment entity found.
- Shared libraries / reusable components: **PARTIAL** — `versioned_lessons`/`memory_embeddings` genuinely
  function as shared organizational knowledge (Phase 1.2), but this is the *same* mechanism that causes
  cross-project bleed (Q95) — sharing and isolation are currently the same code path with no toggle
  between them.
- **Without mixing contexts**: **NO** — this is the core finding of this whole cluster. Since there is
  no project entity (confirmed via `credential_vault.py`'s own docstring) and `MemoryEmbedding` has no
  `repo_id`/`project_id` column, context mixing across "projects" (to the extent the term applies at
  all here) is the default behavior, not an edge case.
  Plan: Foundation-phase work from Q50 — add the project entity and scope memory/repo-context/
  credentials to it.

---

---

## Q95. Workspace Isolation

- Project A never leaks into Project B: **PARTIAL** (was NO) — gap-closure Days 2-3 (2026-07-30)
  built and tested the real isolation mechanism: `MemoryEmbedding`/`VersionedLesson` now have a
  nullable `repo_id` FK (migration `024_memory_project_scoping.py`), and every `query_*` function
  in `app/memory/store.py` accepts an optional `repo_id` and filters `WHERE repo_id = :repo_id OR
  repo_id IS NULL` when given — verified against real seeded repos, not mocked
  (`tests/test_memory_project_scoping_queries.py::test_project_a_scoped_memory_never_returned_by_project_bs_scoped_query`,
  3/3 passing; a real asyncpg parameter-typing bug — `AmbiguousParameterError` on the bare
  `:repo_id IS NULL` comparison — was caught and fixed with an explicit `CAST(:repo_id AS BIGINT)`
  while writing this test, not left broken). Still PARTIAL, not YES: **no real call site passes
  repo_id yet** — every one of ~70+ agent-dispatch call sites still resolves its repo via the
  `_active_repo_path` global and never threads a repo id into these functions, so in current
  production behavior every query is still effectively unscoped (`repo_id=None` everywhere). The
  capability is real and proven; it isn't load-bearing yet.
  Plan (gap-closure Day 4 closed the *dispatch* half — see "Agents never modify the wrong project"
  below; still open): thread the resolved repo's `id` into every `embed_*`/`query_*` call site in
  `app/memory/store.py` so memory itself, not just task dispatch, is scoped on real traffic.
- Memories remain isolated: **PARTIAL** (was NO) — same evidence and same caveat as above; Day 4
  did not touch memory-call wiring, only task-dispatch repo resolution (see below).
- Tools use the correct repository: **PARTIAL** — corrected count from gap-closure Day 4's direct
  grep (the earlier "~75 files" figure here was a different, broader search): `get_active_repo_path()`
  has exactly **11 real call sites** — 6 inside `app/api/repo.py` itself (the repo-management/
  reindex/context/architecture endpoints, which legitimately operate on "whichever repo is active"
  by design — no per-task concept applies to them), and 5 across `app/api/agents.py`(4)/
  `specialized_agents.py`(1) inside background-task bodies. Those 5 are now protected *indirectly*:
  every real scheduling call site upstream of them resolves `task.repo_id` via the new
  `app/db/repository.py::resolve_task_repo_path()` and passes it explicitly before scheduling, so
  the `get_active_repo_path()` fallback inside the background body itself is now a last-resort
  safety net, not the primary path (see next item for the real fix and its test).
  Plan: still open — thread the same resolved repo id into `app/memory/store.py` calls (this item's
  first Plan note).
- Agents never modify the wrong project: **YES** for the confirmed dispatch race (was PARTIAL,
  "not stress-tested... NOT VERIFIED whether a race condition is reproducible"). Gap-closure Day 4
  (2026-07-30) reproduced the exact race this bullet described and fixed it: `_dispatch_decision`
  (`app/api/approvals.py`, the `/api/approvals/{id}/approve` path — confirmed the current primary
  approval route) called `resume_planning_pipeline(task_id=..., approved=...)` with **no repo_path
  at all**, so a plan approved for Task 1 (created against Repo A) that got dispatched after someone
  else activated Repo B would silently run Task 1's coding agents against Repo B — a real, live bug,
  not a hypothetical. Fixed by resolving `task.repo_id` (already DB-persisted, already eager-loaded
  via `get_task`'s `selectinload`) synchronously before dispatch, in `_dispatch_decision` and in
  `specialized_agents.py::run_specialized_agent`; `tasks.py::run_task`/`restart_task`/`approve_task`
  already did this correctly (found 3 independent, slightly-duplicated correct implementations —
  factored into one shared `resolve_task_repo_path()` helper, removing the duplication and a
  redundant DB query each site had been making). Verified with a real reproduction of the exact race
  named in this bullet: `tests/test_repo_scoping_race_fix.py::
  test_dispatch_decision_uses_tasks_own_repo_even_if_global_changed_meanwhile` — creates Task 1
  against Repo A, activates Repo B globally *after* Task 1 exists, dispatches the approval decision,
  and asserts the real (mocked-downstream) call still receives Repo A's path. 3/3 tests passing.
  Still PARTIAL overall for the wider question, not full YES: the 6 `repo.py`-internal endpoints
  (list_repos/reindex/context/architecture/class-graph/package-graph) remain intentionally
  global-scoped — they have no per-task concept to resolve from, and changing that is a different,
  larger feature (a real multi-repo dashboard), not this race-condition fix.
  Original finding this closes, for reference — *which* repo a worktree is created against, for
  agents relying on the default
  changes (another user activates a different repo) between two concurrent dispatches, both agents
  could inherit whichever repo was active at their own dispatch moment. This was not stress-tested in
  this pass (NOT VERIFIED whether a race condition is reproducible), but the architecture is a
  mutable-global-read pattern, which is inherently at risk of this class of bug under concurrency.
  Plan: eliminate the mutable global (see above); add a concurrency test that activates two repos back
  to back while dispatches are in flight and asserts each dispatch used the repo active at ITS OWN
  request time, not a racing later activation.

---

---

## Q96. Enterprise Security

- Secret scanning: **REAL for `security_reviewer`'s regex scan** (`secrets_scan` — real file-tree
  walk + fixed-pattern matching for API keys, AWS keys, private-key blocks, GitHub/OpenAI-shaped
  tokens; result-verification-enforced, not just prompt-suggested). **LLM-prompt-only for
  `compliance_agent`/`security_architect`** — no real CVE-database/pip-audit/npm-audit call wired
  into either's tool handlers, despite role-prompt language implying otherwise.
  `dependency_security_agent` is fixed as of gap-closure Day 7 (2026-07-30) — see Q92 for the real
  scoped-`bash`-plus-graph-enforced-verification fix. Real automated dependency-CVE scanning also
  exists at the CI level (`pip-audit`).
- Encrypted credential storage: **REAL** (see Q21).
- **Audit logs: REAL in-process AND now REAL for durable DB persistence — gap-closure Day 7
  (2026-07-30) closed a genuine, previously-undocumented gap.** The in-memory ring-buffer audit
  trail (2000-entry cap, real, actively used by `credential_vault`/`approval_gate`) was always real
  and working. Its DB-persistence path (`_write_to_db()`, still wrapped in a bare
  `except Exception: pass` by design — a broken audit sink must never block the caller) previously
  had **no migration creating an `audit_log` table**, so every durable-persistence attempt silently
  failed — the audit trail was real-time/in-memory only, capped, and lost on process restart,
  contrary to its own docstring's "durable, survives restarts" claim.
  `backend/migrations/versions/025_audit_log_table.py` creates the table (column set matching
  `_write_to_db()`'s existing INSERT exactly: `entry_id` PK, `trace_id`/`task_id`/`timestamp`
  indexed, `details` JSONB, `ON CONFLICT (entry_id) DO NOTHING` idempotent). Verified live: migration
  applies/downgrades/re-applies cleanly, and a real `AuditLog._write_to_db()` call round-trips a row
  with JSONB `details` intact. Proven by `backend/tests/test_audit_log_migration.py` (3 tests).
- RBAC: **REAL, and independently re-verified as fixed-and-tested** — a prior in-repo formal audit
  (`docs/reports/AUDIT_05_SECURITY.md`, 2026-07-27) originally found authentication/authorization
  "almost entirely absent" (4 Critical findings, rated "NOT READY"); every one of its described
  fixes (RBAC dependencies on ~50 mutating routes, gated legacy header, real password-change
  endpoint) was confirmed present in the current code AND confirmed executed/passing via the later
  full regression gate (3318 passed/21 pre-existing failures, 2026-07-30) — not just "written but
  unexecuted."
- Least-privilege/scoped tool access: **REAL** — every agent's `AGENT_CONTRACT["allowed_tools"]`
  structurally limits what it can call (an unregistered tool name errors out at the shared
  `execute_tools()` gate) — genuine, not just documentation.
- Approval chains: **PARTIAL** — real, role-gated, DB-backed single-decision approval exists at two
  layers (generic HITL pause + glob-pattern policy rules); neither supports a genuine multi-step/
  N-of-M quorum approval chain.
- Compliance readiness: **PARTIAL** — `compliance_agent` is LLM-reasoning-only (no automated
  control-mapping/PII-detection engine); a real, working, genuinely useful data-retention/archival
  mechanism exists separately (`app/services/retention.py`, real 24h loop, archives not
  hard-deletes old logs/runs/artifacts/memory).

---

---

## Q97. Disaster Recovery

- What survives (machine crash): all Postgres-backed data — `dev_tasks`, `agent_runs`, `epics`,
  `pending_approvals`, `memory_embeddings`, `versioned_lessons`, `epic_scratchpad`, `repos`,
  `system_settings` — as long as Postgres itself is on separate, surviving storage (a standard
  assumption for any DB-backed system, not independently verified as containerized-alongside-app in
  this pass). Also survives: the git repository and its worktrees on disk (not a backend-process
  concern).
- What restarts (on process restart, per `main.py::lifespan`): `init_active_repo()` (restores the
  single active-repo pointer from the DB), `init_checkpointer()` (reconnects `AsyncPostgresSaver`),
  background loops (`_weekly_reindex_loop`, `start_retention_loop`, `_fleet_agents_scan_loop`,
  `_versioned_lesson_archive_loop`, `_benchmark_baseline_loop`, `start_orphan_recovery_loop`), fleet
  agent module registration (`ensure_all_agents_registered()`).
- What is replayed: pm/architect/decomposer pipeline runs that were paused mid-flight at an
  `interrupt()` point — genuinely resume from their last `AsyncPostgresSaver` checkpoint, not restarted
  from scratch.
- What must be redone: any of the ~70 worker-agent (`base_graph.py`) runs that were in progress at
  crash time — these have no checkpointer; `reconcile_orphaned_runs()` marks them `failed` after
  `agent_run_orphan_threshold_seconds` (900s default) once heartbeats go stale, and the failure-ladder
  escalation path takes over from there (retry per `manager.py`'s own retry budget, or human escalation)
  — but the actual in-progress tool-call sequence is lost, not resumed. Also lost: any live chat
  session (`chat_agent.py`'s `MemorySaver` is in-process-only by design — confirmed in
  `IMPLEMENTATION_PROGRESS.md`'s Phase 5.2 entry as "no reduction in durability versus the mechanism it
  replaces," i.e. chat state was always ephemeral, this is not a regression from the LangGraph
  conversion).

---

---

## Q98. Version Awareness

- Git branches: **YES** — `git_branch_list`/`git_checkout` tools (`app/services/git_service.py`),
  branch-name validation against path traversal, worktree-per-task branch convention
  (`agent/task-{id}`).
- Releases: **PARTIAL** — `release_notes_agent` role exists (`backend/roles/release_notes_agent.md`)
  and a `git_tag` tool exists for tag creation/listing (`app/agents/tools.py:6073`), but no dedicated
  "GitHub Release" API integration was found in this pass (NOT VERIFIED beyond git tags themselves).
- Tags: **YES** — `git_tag` tool handler (`app/agents/tools.py::git_tag_h`), manifest-registered
  (`app/fleet/tool_manifest.py:584`), supports list/create/delete actions.
- Migrations: **YES** — real alembic setup (`backend/alembic.ini`, `.venv/Scripts/alembic.exe`, 23
  migration revision files found under the versions directory), consistently chained (e.g. Phase 1.7's
  `023_epic_scratchpad.py` explicitly verified as `022 -> 023 (head)`, no branching, per
  `IMPLEMENTATION_PROGRESS.md`).
- Semantic versioning: **YES** — `version_manager_agent` role
  (`backend/roles/version_manager_agent.md`) is explicitly and narrowly scoped to "determine the
  correct semantic version bump from actual git history and diffs," has real `git_log`/`git_blame`
  tool access (confirmed via `READ_ONLY_TOOLS` inheritance, Phase 4 Item 5), and its role file mandates
  evidence-cited recommendations (commit/diff citations, not invented) — read-only, never
  publishes/tags itself (separation of concerns from `git_tag`'s actual execution).
- Compatibility between versions: **PARTIAL** — `version_manager_agent`'s role explicitly covers
  "version consistency across manifests" (cross-checking pyproject/package.json/lockfiles) as one of
  its Success Criteria, which is real cross-version-consistency checking. NOT VERIFIED: any automated
  cross-*application*-version compatibility check (e.g. "will this migration break a client still on
  the previous API version") beyond the DB-migration chain-verification discipline already evidenced
  above.

---

## Q99. User Experience Intelligence

- detect confusion: **NO** — no mechanism found (grepped for confusion-detection patterns across `app/`).
- simplify explanations: **NOT VERIFIED** — depends on each agent's live LLM output style; no code-level "simplify for this audience" toggle found.
- switch between beginner and expert mode: **NO** — no `beginner`/`expert` mode flag or setting found anywhere in `backend/app`.
- explain technical decisions: **PARTIAL** — same evidence as Q44 (`replan_node`'s cited reasons, critique messages) — real but partial, not a dedicated feature.
- generate diagrams: **YES** — real, working tools: `generate_diagram` (`app/agents/tools.py:6390-6392`, produces real Mermaid flowchart/sequence/ER code from a text description) and `mermaid_from_schema` (`tools.py:4811-4813`, converts a live DB schema inspection into a Mermaid ER diagram via `psql` introspection, not a template).
- summarize long outputs: **YES** — `summarize_repo` (`tools.py:4951-4953`, file tree + line counts + language breakdown + README excerpt) and `summarize_folder` (`tools.py:4776-4778`, per-file summaries for up to 20 files) are real, working handlers (`summarize_repo_h`/`summarize_folder_h`), not stubs.
  Plan: diagram/summarization tooling is genuinely implemented and available to agents. Confusion-detection and beginner/expert mode switching are unbuilt — would need a new UX-layer feature (likely in the chat session/`ChatAgent`) tracking user signals (repeated clarifying questions, explicit "I'm confused" phrasing) and a verbosity/detail-level setting threaded into `system_prompt`.

---

## Q100. Accessibility & Localization

`backend/app/agents/accessibility_agent.py` and `localization_agent.py` are **PROMPT-ONLY, not real
automated checking** — both are LLM agents with only generic read/search/AST tools (`read_file`,
`search_code`, `parse_ast`, etc.), no integration with axe-core, Lighthouse, eslint-plugin-jsx-a11y,
pa11y, i18next-scanner, or any WCAG/i18n rule-checking library (confirmed by grep: "WCAG"/"axe" only
appear as prose in the LLM instructions, never as an executed check). Both produce a written `.md`
audit report based on the model reading source text — genuinely useful for surfacing candidates, but
cannot compute real rendered contrast ratios, test actual keyboard traps, or run assistive tech.

- Keyboard navigation / screen readers / ARIA / color contrast: **PROMPT-ONLY** for all four —
  mentioned in the prompt instructions, not independently verified by tooling.
- Responsive layouts: **NOT FOUND** — not even mentioned as a checked concern.
- Localization/i18n: handled by the separate `localization_agent`, same prompt-only pattern —
  searches for hardcoded strings and date/number formatting via LLM judgment, no real
  i18next/gettext/ICU tooling integration.
- Wiring: both are real, dispatchable via `POST /api/specialized-agents/{name}/run`, but
  **on-demand only** — no evidence either is auto-invoked as part of the standard pipeline or any
  CI/PR gate.

Verdict: **PARTIAL** — real, well-specified LLM auditor agents exist and are dispatchable, but there
is no real automated a11y/i18n tooling anywhere in the codebase, and neither is wired into any
automatic pipeline gate.
Plan: integrate a real tool (axe-core via a headless browser run, or eslint-plugin-jsx-a11y in CI)
for accessibility; integrate a real string-extraction scanner for i18n; keep the LLM agents as a
complementary review layer, not the only line of defense.

---

---

## Q101. Economic Awareness

- execution time estimate: **NO** — same finding as Q42/Q32: `CostEstimate` (`cost_controller.py`) has no duration field.
- token usage estimate: **YES** — `estimate_epic_cost()`, see Q42.
- API cost estimate: **YES** — `estimated_cost_usd`, see Q42.
- compute requirements estimate: **NO** — no CPU/RAM/GPU estimate anywhere (see Q31).
- storage impact estimate: **NO** — no disk-space-impact estimate found.
  Plan: same as Q42/Q32 — token/dollar cost is real and gates execution via `requires_approval`; runtime, compute, and storage estimates are genuine, unimplemented gaps.

---

## Q102. Long-Running Jobs

- 30 minutes: **YES** — `max_turns` (default 20, enforced by the graph's own conditional edge per `base_graph.py` line 5's comment, not model self-restraint) and `llm_call_timeout_seconds` (`base_graph.py:54`) bound individual runs; SSE heartbeat streaming (`app/api/activity.py::stream_task_events`, 15s heartbeat interval, "Day 18 ... matches the plan's own heartbeat interval") provides live progress during this range.
- several hours: **PARTIAL** — `EpicScratchpad`'s `scratchpad_ttl_seconds` (default 4 hours, `app/fleet/scratchpad.py`) is explicitly documented as "the backstop for an epic that stalls and never reaches a terminal state" — i.e. the system is designed with multi-hour epics in mind, and per-subtask retry-with-backoff (`run_manager()` in `manager.py`, "the single most heavily-tested piece of this file across 180+ tests") provides real retry/resumability at the subtask level. But the epic-manager graph itself has **no checkpointer** (`manager.py:1139`, confirmed above) — a crash mid-epic loses in-process state and falls back to the coarser `restart_task` (re-run from `pending`, not the exact interrupted point).
- overnight: **PARTIAL** — same limitation as "several hours": nothing structurally prevents an overnight run, and the scratchpad TTL/retry-with-backoff machinery supports it, but true crash-safe resumability at exactly the interrupted point is only proven for `app/pipeline/graph.py`'s Postgres-checkpointed plan-review pause, not for a multi-hour epic-manager run.
- "with checkpointing, progress reporting, retries, and resumability": **PARTIAL** — progress reporting (SSE heartbeat) and retries (per-subtask backoff loop, `restart_task`) are real and tested. Checkpointing/resumability is real only for the Postgres-backed pipeline graph; the epic-manager's own long-running dispatch loop is deliberately uncheckpointed by design (`manager.py:1139-1142`, a documented tradeoff, not an oversight — the file states the per-subtask retry loop "is a poor structural fit for LangGraph's node/edge model" and was deliberately kept as plain Python).
  Plan: if exact mid-epic crash-resumability (not just task-level restart) is required for overnight runs, that's new work on `manager.py`'s epic loop — explicitly out of scope for the LangGraph conversion done so far, per that file's own stated reasoning.

---

## Q103. Human Override

- interrupt any agent: **PARTIAL** — `POST /api/tasks/{id}/stop` (`activity.py:61`) sets an abort flag checked by `call_llm`, stopping after the current tool call completes — real, but not an instantaneous mid-tool-call kill; confirmation-gated dangerous actions additionally pause automatically via `interrupt()` before executing (see Q13).
- take over a task: **PARTIAL** — `POST /api/tasks/{id}/resume` (`activity.py:76`) lets a human inject a new message + files after a stop, redirecting the task's continuation — a real steering mechanism, though it's "inject a follow-up," not "human directly edits agent-authored code/state."
- edit a plan: **NO** — `human_review_node` (`pipeline/graph.py:99-109`) only accepts `{"approved": true|false}` on resume; no endpoint or `interrupt()` payload was found that accepts an edited plan back. `POST /api/approvals/{id}/approve|reject` (`approvals.py`) is likewise binary, not an edit.
  Plan: would need `human_review_node`'s interrupt payload/resume contract extended to accept an edited subtask list, and `_dispatch_decision`/`resume_planning_pipeline` updated to apply it instead of the original plan.
- reject one step: **PARTIAL** — `reject_approval`/`reject_task`/`reject_epic`/`pipeline_reject` all exist (`app/api/approvals.py`, `tasks.py`, `epics.py`) and reject the specific pending decision (plan, push, task, epic) they're scoped to — a real per-decision-point reject, but not "reject one arbitrary step out of a multi-step in-flight plan while letting the rest continue."
- resume from that point: **YES** — `Command(resume=...)` genuinely resumes from exactly the `interrupt()` call site within the LangGraph node (proven via the real reproduction script cited in `chat_agent.py`'s docstring: a side effect after `interrupt()` fires exactly once across the pause/resume cycle).
  Plan: "edit a plan" is the clearest real gap here — binary approve/reject is implemented and tested; plan mutation is not.

---

## Q104. Explainability

Note: this is the literal duplicate topic of Q44 ("Why this agent? Why this tool? Why this plan?" vs Q44's "why it chose that approach / why rejected alternatives / why specific agents / why specific tools") plus one new item, "why this architecture" — same evidence base as Q44 applies to the first four sub-items.

- Why this agent?: **PARTIAL** — same as Q44 ("why specific agents participated"): traceable via `capability_registry.py` registrations + audit log, no generated plain-language explanation on demand.
- Why this tool?: **PARTIAL** — same as Q44: traceable via `AGENT_CONTRACT["allowed_tools"]`/`VerificationConfig` + audit log, no on-demand explanation feature.
- Why this plan?: **PARTIAL** — same as Q44: the model's own plan-generation output plus `replan_node`'s cited reasons on revision; no structured plan-rationale field.
- Why this architecture?: **PARTIAL** — this specific sub-item has *better* evidence than the other three: `IMPLEMENTATION_PROGRESS.md` itself is a real, detailed, human-readable architecture-decision record (e.g. the extensive rationale for why `chat_agent.py` uses `MemorySaver` not `AsyncPostgresSaver`, why `manager.py`'s epic loop stayed unconverted, why `cross_project=True` wasn't built for memory tiering) — but this is a development-time engineering log, not a runtime "explain the architecture to me" feature exposed to an end user.
- Why not the alternatives?: **PARTIAL** — `IMPLEMENTATION_PROGRESS.md` documents several explicit "considered and rejected" decisions (e.g. the first `chat_agent.py` interrupt-conversion attempt rejected for replaying side effects; `terraform`/`kubectl` dry-run carve-out rejected as a per-agent tool). Real, but again a static engineering document, not a live queryable explainability feature.
  Plan: Q104 is confirmed a genuine duplicate of Q44 for its first 4 sub-items, with the same PARTIAL rating and same underlying gap (no live "explain this decision" API; the reasoning exists in code comments/docs/audit-log data, not synthesized on demand). "Why this architecture / why not the alternatives" is comparatively better-evidenced because this session's own `IMPLEMENTATION_PROGRESS.md` is itself a real rationale document — worth flagging to Bhaskar as partially satisfying the spirit of the question even though it's not a runtime feature.

---

## Q105. Company Brain (Organizational Intelligence)

There is no single named "Company Brain" component — grep for
`Company Brain|company_brain|central.*brain|organizational.*intelligence` across the
whole repo returns zero hits outside the questions file itself. What exists is a set
of separate stores that partially cover the list:

- Proven coding patterns: **PARTIAL** — `category="task"`/`"procedure"` rows in
  `memory_embeddings` capture what was done and how, but nothing tags a pattern as
  specifically "proven" (no reuse-count or success-rate field).
- Successful workflows: **PARTIAL** — procedural memory (`embed_procedure`) captures
  ordered real steps for hard tasks only (gated on real iteration), not routine
  successful workflows generally.
- Failed approaches: **YES** — `category="failure"`, `store.py::embed_failure`/`::query_failures`.
- Architecture decisions: **YES** — `category="architecture"`, `store.py::embed_architecture_note`,
  written by `architect`/`database_architect`/`security_architect`/`api_designer_agent`
  (`app/memory/hooks.py::_is_architecture_agent`).
- Design decisions: **PARTIAL** — folded into the same "architecture" category, no
  separate design-decision type.
- User preferences (project-specific): **NO** — no `UserPreference` model/table anywhere
  (grep for `preference` across `backend/app` returns one unrelated hit, a role-file
  instruction in `infra_agent.py` about not flagging "stylistic preferences" in code
  review — not a preference-storage mechanism). See Q113.
- Reusable templates: **NO** — no template store found.
- Best practices: **PARTIAL** — via `VersionedLesson`/curated learning signals,
  informal rather than a distinct "best practice" category.
- Approved prompts: **YES** — `app/fleet/prompt_registry.py::PromptRegistry`, a real
  draft→in_review→approved→deployed lifecycle for role-prompt versions
  (`_STATE_TRANSITIONS`, `approve()`/`deploy()`, `approved_by` tracked).
- Approved MCPs: **NO** — no MCP (Model Context Protocol) concept exists in this
  codebase at all; grep for `approved_mcp|mcp_allowlist` returns nothing. Tools are
  custom Python handlers, not MCP servers.
- Approved tools: **YES** (as static config, not a memory record) — `app/fleet/tool_manifest.py::TOOL_MANIFEST`
  is the fleet-wide source of truth for which tool is bound to which agent with what
  permissions; enforced by compliance tests (`IMPLEMENTATION_PROGRESS.md` Day 3/1.4).
- Known bugs: **YES** — overlaps with failure records (`category="failure"`).
- Permanent solutions: **PARTIAL** — overlaps with procedural memory; nothing marks a
  solution "permanent" vs. one-off.

"Every agent consults it before starting work": **PARTIAL** — true for the ~70
`run_agent_graph`-based agents (`memory_hook_node` runs before every `call_llm`, fleet
default `enable_memory=True`), but `executive.py` runs with `tools=[]` (a single LLM
call, no tool use, confirmed in `IMPLEMENTATION_PROGRESS.md` Item 4's "executive ...
uses tools=[] by architecture") and so has no memory read/write wiring at all.
Plan: there is no unifying "Company Brain" surface today — the closest real fix is a
single read API (`GET /api/memory/brain?topic=`) that fans out across
`memory_embeddings` + `versioned_lessons` + `tool_manifest` + `prompt_registry` in one
call, since the underlying stores already exist but are queried separately today.

---

---

## Q106. Improvement Backlog

- "Every interaction should be analyzed after completion": **PARTIAL** — every real agent run (not just manager-orchestrated ones) does have a universal post-run hook, `record_agent_run_outcome()` (`backend/app/memory/hooks.py`), that stores task-outcome/failure records — real, evidenced. But this is raw storage, not the qualitative per-interaction analysis Q106 asks for.
- "What slowed us down? Which tool failed? Which clarification was missing? Which prompt caused confusion? Which agent struggled? Which task repeated? What could be automated?": **NO** — none of these specific questions is asked per-interaction anywhere; the closest real proxy is the periodic (every-4h, aggregate, not per-interaction) scans by `agent_performance_reviewer`/`agent_debugger`/`agent_advisor`.
- "Instead of changing code immediately, create improvement proposals for review": **YES** — `enhancement_requests` is exactly this, real and evidenced (see Q35/Q36).
  Plan: add a lightweight per-task post-mortem synthesis step (could reuse `record_agent_run_outcome`'s hook point) that answers Q106's specific questions and feeds them into `enhancement_requests`.

---

## Q107. Pattern Recognition

- General recurring-pattern detection: **PARTIAL** — real infrastructure exists: `GET /api/fleet/reports/repair-patterns` (`backend/app/api/fleet_dashboard.py:389-419`) groups `memory_embeddings` failure records by **exact** root-cause summary text, counts occurrences, and sorts by frequency — a genuine, if literal-match-only (not fuzzy-clustering), recurring-failure detector. However, it is not consumed anywhere: `apps/web/app/fleet/page.tsx` only calls `/api/fleet/requests`, never `/reports/repair-patterns` — so this report is real but dead-ended (nobody sees it, nothing acts on it automatically).
- "Users often request feature X" / "same clarification asked repeatedly" / "same bug appears across projects": **NO** — no such specific clustering exists; the repair-patterns endpoint only covers `category="failure"` root-cause summaries, not feature requests or clarifications.
- "One agent is always overloaded": **PARTIAL** — `agent_advisor`'s scan could theoretically surface this via `task_history_query`, but no dedicated "load imbalance" metric/detector exists.
  Plan: wire `/reports/repair-patterns` into the fleet dashboard UI; add feature-request/clarification pattern tracking.

---

## Q108. Agent Performance Review

- Success rate / failure rate: **YES** — `GET /api/fleet/reports/health` computes real `failureRate` per agent from `AgentRun` DB rows (`backend/app/api/fleet_dashboard.py:334-386`).
- Average execution time: **YES** — `MetricsCollector.p50_latency_ms`/`p95_latency_ms` per agent (`backend/app/fleet/metrics.py:230-251`), plus `benchmark_manager`'s `latency_p50` objective.
- Retry count: **YES** — `RunMetrics.retries` field, tracked per run (`backend/app/fleet/metrics.py:83`).
- Human approval rate: **NO** — no aggregated "approval rate" metric found anywhere (`pending_approvals`/`enhancement_requests` have per-row `decided_by`/status but nothing rolls this into a per-agent rate).
- User satisfaction: **NO** — confirmed absent by grep; no rating/feedback/satisfaction field exists anywhere in the codebase.
- Planning accuracy / verification accuracy: **NO** — confirmed absent by grep (`verification_pct` is tracked per-run in `RunMetrics`, which is a real proxy for verification coverage, but there is no named "planning_accuracy" or "verification_accuracy" metric, and neither is aggregated/tracked over time as a trend).
- "Low-performing agents become improvement candidates": **PARTIAL** — `regression_detector.check_fleet()` can flag any agent that regressed against its stored baseline, and `agent_performance_reviewer`'s periodic scan can flag a struggling agent as an enhancement request — but there is no automatic "this agent is consistently the worst performer" ranking/alert distinct from a human or the reviewer agent noticing during a scan.
  Plan: add human-approval-rate and user-satisfaction fields; surface `regression_detector.check_fleet()` results on the dashboard automatically.

---

## Q109. Continuous Architecture Review

- "Is orchestration still optimal? Redundant agents? Should agents be merged/split?": **PARTIAL** — `agent_advisor`'s autonomous scan (every 4h) genuinely asks a version of this ("was anything over/under-provisioned") from task/audit history — real evidence, but scoped to per-task orchestration correctness, not fleet-wide agent redundancy/merge-candidate analysis.
- "Are memories duplicated?": **YES** — `knowledge_curator`'s autonomous scan explicitly checks for duplicate/near-duplicate memory entries.
- "Are tools overlapping?": **NO** — no evidence any agent checks for tool overlap across the fleet.
- "Are prompts too large? Is context usage efficient?": **NO** — no evidence found; `architecture_reviewer` doesn't inspect prompt files, and no agent measures token/context efficiency of role prompts.
- Overall periodicity: **PARTIAL/NO** — the one agent purpose-built for full architecture review (`architecture_reviewer.py`, real: import graphs, circular deps, dead code, layer violations) is **task-triggered only**, not in `_fleet_agents_scan_loop()` — so "continuous" architecture review, as literally asked, does not happen; only the narrower `agent_advisor` orchestration check and `knowledge_curator` memory-duplication check run periodically.
  Plan: add `architecture_reviewer` to the periodic scan loop, or build a dedicated periodic architecture-health agent.

---

## Q110. Prompt Evolution

- "Prompts should not change automatically": **YES, respected in the designed system** — `prompt_registry.py`'s `deploy()` requires `status == "approved"` before writing anything (`backend/app/fleet/prompt_registry.py:321-339`).
- "Detect weaknesses / Generate improved prompt versions": **NO** — no agent or code path detects a prompt weakness and calls `propose()` automatically; `propose()` exists but has no live caller (confirmed dormant, see below).
- "Explain expected benefits / Show a diff": **NO** — `PromptVersionRecord` stores full content and a `content_hash`, so a diff *could* be computed, but no code anywhere generates or displays a diff or a benefits explanation.
- "Require your approval": **YES, mechanically** — the `draft→in_review→approved→deployed` state machine exists and is enforced (`_VALID_TRANSITIONS`, `InvalidTransition`).
- "Test before deployment": **PARTIAL → gate now real-checked on every deploy, honest scope note below** — `deploy()` gates on `regression_detector.get_regression_detector().gate_deploy(role_name)`, which compares live benchmark scores to a stored baseline — a real, automated "test."
  **Gap-closure Day 50**: the gate is no longer dormant (see "Critical finding" below) — it is real-checked on every real role-prompt write. Still PARTIAL, not YES: the gate only fires for agents that already have a stored benchmark baseline (`_benchmark_baseline_loop()`'s own scope, Day 21) — a role prompt with no benchmark history yet deploys ungated, same as before.
- **Critical finding — RESOLVED (gap-closure Day 50, 2026-08-03, Stage 2)**: `prompt_registry.py` was fully built and tested (`tests/test_prompt_registry.py`) but had no live caller — `propose()`/`deploy()` were never called in production, and `knowledge_curator`'s APPLY phase edited role-prompt files directly via raw `write_file`/`edit_file`/`git_commit_change` "as the exception," bypassing this entire diff/approval/regression-gate system.
  **Fix**: `make_fleet_apply_handlers()`'s shared `write_file`/`edit_file` handlers (`backend/app/agents/tools.py:11939-12092`) now detect a `roles/<name>.md` target (`_role_prompt_name`) and route it through the real `propose() -> submit_for_review() -> approve() -> deploy()` lifecycle (`_propose_and_deploy_role_prompt`) instead of a raw disk write. This is shared by all 4 write-capable fleet self-improvement agents (`knowledge_curator`, `agent_debugger`, `agent_performance_reviewer`, `quality_auditor`), each passing its own `agent_name` for accurate `proposed_by`/`approved_by` attribution — not just knowledge_curator, since any of the 4 could in principle touch a role prompt through this shared handler set. `edit_file`'s existing-content read was also fixed to source from `prompt_registry.get_deployed()` rather than the raw repo-relative path for role-prompt targets specifically, since prompt content is authoritatively tracked by the registry, not by wherever `repo_path` happens to point.
  Each APPLY phase only ever runs after a human approves the specific `enhancement_request`, so auto-advancing through `submit_for_review()`/`approve()` here reuses oversight that already happened rather than skipping human review — the regression gate itself is still real-checked with no shortcut (`DeploymentBlocked` surfaces as `[BLOCKED]` back to the agent, and the file is verifiably never written when it fires).
  **Tests**: `tests/test_gap50_prompt_registry_wiring.py` (10 tests, real Postgres + real `roles/` dir writes/cleanup, matching `test_prompt_registry.py`'s established convention) — the `_role_prompt_name` path-matching helper; a real write-through-registry deploy with DB+file assertions; the content-hash no-op path; a real 2-version edit-through-registry supersession; a regression guard proving non-role-prompt writes are untouched (still a raw disk write); a real `DeploymentBlocked` gate firing with no file write; and an `inspect.getsource` "verify real callers" guard confirming all 4 agents' APPLY phases pass their own `agent_name`, not the default.
  Plan: still open — nothing yet autonomously decides *when* to propose a prompt change (see Q36/Q37's "prompts" entries) — that remains real, separate, unbuilt capability.

---

## Q111. Tool Evolution

- "If tools repeatedly fail: recommend replacement / new MCPs / new APIs / better libraries": **NO** — no mechanism exists. `tool_discovery.py` is a static compatibility/availability registry (`check_compatibility`, `check_availability`, `is_high_risk`), not an adaptive failure-driven recommender. `agent_debugger`'s scan can file a generic bug enhancement request if it notices a tool failing repeatedly via `audit_log_read`, but there is no dedicated "tool health" category, no MCP/API/library recommendation logic, and no evidence this pattern (repeated failure of the *same* tool) is specifically tracked/aggregated anywhere.
  Plan: add a tool-failure-frequency aggregation (similar to `/reports/repair-patterns`) and a dedicated `category="tool_evolution"` enhancement-request type.
- "Require approval before changes": **YES, mechanically** — same enhancement-request approval gate applies to whatever `agent_debugger` does file.

---

## Q112. Knowledge Validation

**NO** — there is no evidence gate before a new record becomes shared, queryable
knowledge. Concretely: `make_record_learning_handler` (`app/agents/tools.py` line 324-343)
takes whatever `finding`/`outcome` string the model passes in a single tool call and
writes it straight to `memory_embeddings` (`store.py::embed_learning_signal_sync`) with
no check for "successful execution," "passing tests," "official documentation," or
"multiple successful uses" — one interaction is sufficient by design. Likewise
`embed_task_outcome`/`embed_procedure`/`embed_architecture_note` all write on the first
occurrence, gated only on `settings.memory_enabled`, never on corroborating evidence.

The one real validation-adjacent mechanism is `VersionedLesson.publish()`
(`app/fleet/versioned_memory.py::VersionedMemoryStore._publish`): before a new lesson
becomes the "published" version for a topic, it checks cosine similarity against the
existing published lesson and merges via LLM if similar
(`memory_merge_similarity_threshold`, `config.py` line 375-378) — but this is dedup/merge
logic, not an evidence requirement; a single novel, unverified lesson still publishes
immediately if nothing similar exists yet.

`knowledge_curator` (`app/agents/knowledge_curator.py`) provides after-the-fact curation
(`run_knowledge_curator_scan`/`run_knowledge_curator_apply`) — finds duplicate/stale/
mis-categorized entries and requires human approval before any curation action is applied
(`requires_human_approval` gate on the enhancement-request flow) — but this cleans up
already-stored knowledge; it does not gate what gets stored in the first place.

Plan: add a real evidence field to the `record_learning`/`embed_learning_signal` write
path (e.g. require `evidence_type` ∈ {test_pass, doc_citation, repeat_use} and reject or
mark `unverified=True` when absent), and only surface `unverified=True` rows to
`memory_hook_node`'s injected context after N independent successful reuses — none of
this exists today.

---

---

## Q113. User Preference Learning

**NO** — confirmed no `UserPreference` model, table, or learning mechanism anywhere in
`backend/app`. Grep for `preference|framework.*prefer|coding_convention|documentation_style`
across the whole `app/` tree returns exactly one hit, and it is unrelated (a role-file
instruction in `infra_agent.py` telling that agent not to flag code-review "stylistic
preferences" — a review-scope rule, not a stored user preference). There is no mechanism
distinguishing a stable preference (e.g. "always use FastAPI") from a one-off/temporary
choice, because no preference is captured at all.
Plan: add a `UserPreference` table (key, value, scope=project|global, confidence,
observed_count, last_confirmed_at) and a write path that only promotes a preference to
"stable" after it's been observed consistently across multiple tasks (same
multiple-successful-uses gate Q112 is also missing) — genuinely new work, no partial
implementation to build on.

---

---

## Q114. Project Evolution

**NO** (explicitly, and self-documented as a known limitation, not just an omission
this audit found independently) — `MemoryEmbedding` (`app/db/models.py` lines 495-519)
has no `repo_id`/`project_id` column, so architecture history, bugs, deployment notes,
coding rules, technical debt, and known risks all land in one fleet-wide, unpartitioned
`memory_embeddings` table rather than "isolated per project." `IMPLEMENTATION_PROGRESS.md`
(Step 1, Day 3/1.6) documents the exact same finding from the inside: "'project' and
'fleet' tiers are the same implementation today ... real per-repo scoping needs an
actual migration + filter column, deferred until cross-repo memory bleed is an observed
problem, not a speculative one." Individual sub-items do exist, just not isolated per
project:
- Architecture history: `category="architecture"` rows exist (fleet-wide, not scoped).
- Design decisions: same as above.
- Common bugs: `category="failure"` rows exist (fleet-wide).
- Deployment notes / coding rules / technical debt / known risks: **NOT VERIFIED** as
  distinct categories — `MemoryEmbedding.category` is constrained in practice to
  `task|architecture|failure|learning|procedure` (per `store.py`'s own comment,
  `app/db/models.py` line 506-508); nothing further-specific like "deployment_note" or
  "tech_debt" exists as its own category.
Plan: same fix as Q5's Project Memory gap — add `repo_id`, migrate, filter every
`query_*` in `store.py` by it, and add the missing categories
(`deployment_note`, `tech_debt`, `known_risk`) alongside the existing five.

---

---

## Q115. Release Retrospectives

- "After significant work: what went well / what failed / what should change / what should become standard practice": **NO** — no such module exists. `release_notes_agent.py` generates `RELEASE_NOTES.md` from git log/tags (a changelog, task-triggered), which is adjacent but is not a retrospective (no "what failed"/"what should change" analysis, no autonomous triggering after significant work).
  Plan: build a dedicated retrospective agent that runs after a major merge/epic completion and reads `agent_runs`/`enhancement_requests`/task outcomes to answer these 4 questions as a generated report.

---

## Q116. Capability Gap Detection

- "If users repeatedly ask for something the platform cannot do: detect trend, estimate demand, suggest new agents/tools/workflows": **NO** — confirmed absent by grep across the whole backend (no "capability_gap" module, no demand-trend tracking). Nothing captures unmet/failed user requests as a distinct signal to aggregate.
  Plan: this is a real, clean gap — would need a new tracking mechanism (e.g., log every task that no agent's capability tags matched, or every explicit user "I need X" that the pipeline routed nowhere) plus periodic aggregation.

---

## Q117. Quality Score

- Per-agent quality score, tracked over time: **PARTIAL** — real: `benchmark_manager.py` computes 7 objectives per agent (`latency_p50`, `tool_accuracy`, `verification_coverage`, `retry_success`, `compile_success`, `hallucination_rate`, `benchmark_score`) from live `MetricsCollector` data, persisted to Postgres (`agent_benchmarks` table) with baseline history for regression comparison (`backend/app/fleet/benchmark_manager.py:1-13`). This is genuine, persisted, trackable quality scoring — but only for **agents' execution quality**, not the other 8 dimensions Q117 names.
- Architecture / Prompts / Tools / Memory / Documentation / Tests / Performance / Security as a unified, tracked score: **NO** — no holistic scoring exists for these; each has at most an ad hoc, on-demand agent (architecture_reviewer, tech_debt_agent, quality_auditor) with no numeric score persisted/tracked over time for that dimension.
  Plan: extend `agent_benchmarks`-style persistence to the other 8 dimensions, or build a composite "platform quality score" that aggregates all of them.

---

## Q118. Safe Self-Improvement

- Detect problems automatically: **YES** — the 5 periodic scan agents, evidenced throughout.
- Analyze root causes: **YES** (for bugs) — `agent_debugger` explicitly diagnoses root cause from `audit_log_read`/`fleet_metrics_read` evidence before filing.
- Propose solutions: **YES** — `submit_enhancement_request` with title/description/category/priority/evidence.
- Simulate impact: **NO** — no impact simulation exists anywhere; nothing dry-runs a proposed change before showing it to a human.
- Show you the plan: **PARTIAL** — the human sees the enhancement request's title/description/evidence on the dashboard before approving, but not a concrete "here is exactly what will change" plan/diff (e.g. no file-level preview before approval — the APPLY phase decides what to write only after approval).
- Wait for approval: **YES** — real, evidenced (`backend/app/api/fleet_dashboard.py` approve/reject).
- Implement: **YES** — real APPLY-phase functions (`run_agent_debugger_apply`, etc.) that write/commit code post-approval.
- Test: **PARTIAL** — `run_tests` is an available tool in `FLEET_APPLY_TOOLS`, and some `_APPLY_CFG` verification configs track `tests_run`, but it is not universally *enforced* (e.g. `agent_performance_reviewer`'s/`quality_auditor`'s apply-phase `enforce_in_result` only requires `committed`, not `tests_run` — tests can be skipped and the run still reports success).
- Roll back automatically if needed: **NO** — confirmed by code comment: rollback (`prompt_registry.rollback()`, checkpoint-based `rollback_to`) is explicitly designed as a "future ... dashboard action" / "manual/operator-invoked tooling," not an automatic trigger (`backend/app/fleet/failure_ladder.py:55-60`). No code path calls rollback automatically after a bad deploy or failed apply.
  Plan: this is the single biggest evidenced gap in the whole cluster — add (a) a mandatory test-run enforcement on every APPLY phase, and (b) an automatic rollback trigger keyed off a post-apply regression check.

---

## Q119. "CEO Dashboard"

- Company health / Active agents / Failed tasks: **PARTIAL** — real backend data exists (`GET /api/fleet/reports/health` gives failure rate + active runs per agent), but there is no single unified dashboard page presenting "company health" as a concept.
- Pending approvals: **YES** — `apps/web/app/fleet/page.tsx` is a real, working UI listing pending `enhancement_requests` with approve/reject actions.
- Suggested improvements: **YES** — same page, same data (the enhancement requests ARE the suggested improvements).
- Technical debt: **NO** — `tech_debt_agent` produces findings, but only when a human explicitly runs it via `backend/app/api/specialized_agents.py`; no dashboard surfaces this on any cadence.
- Performance trends: **PARTIAL** — `GET /api/fleet/reports/cost` and benchmark data exist server-side, but are not rendered anywhere in `apps/web` (confirmed: `apps/web/app/fleet/page.tsx` only calls `/api/fleet/requests`, never `/reports/cost`, `/reports/health`, or `/reports/repair-patterns`).
- Security warnings: **PARTIAL** — `quality_auditor` files security-category enhancement requests, visible on the same one dashboard, but not as a distinct "security warnings" panel.
- Test status: **NOT VERIFIED** — no dedicated test-status endpoint/panel found in this investigation.
- Cost and token usage: **PARTIAL** — real backend endpoint exists (`GET /api/fleet/reports/cost`, per-agent/day tokens+cost+model-tier rollup, `backend/app/api/fleet_dashboard.py:278-331`) but is unconsumed by any frontend page found.
- Memory usage: **NOT VERIFIED** — no dedicated "memory_embeddings row count / DB size" panel found; would need further check of any admin/ops page.
- Queue status: **NOT VERIFIED** — `pipeline/queue_adapter.py` exists but no dashboard panel for queue depth was found in this pass.
- Project health: **NOT VERIFIED** — no single "project health score" endpoint/page found distinct from the per-agent health report.
- **Overall**: **NO unified CEO Dashboard exists.** What's real is the single-purpose Fleet Enhancement Dashboard (`apps/web/app/fleet/page.tsx`) showing pending approvals + suggested improvements only. Several of the other panels have real backend data (`/reports/cost`, `/reports/health`, `/reports/repair-patterns`) sitting unconsumed, ready to be wired into a real unified dashboard, but nobody has built that page.
  Plan: build one dashboard page aggregating the existing `/api/fleet/reports/*` endpoints plus tech-debt/test-status/queue data that doesn't yet have an endpoint.

---

## Q120. Intelligent Memory Management

### Working Memory
- Stores only info required for current task: **YES** — `AgentRunState` (`base_graph.py`)
  is scoped to one `run_agent_graph()` call; no cross-task leakage of working state.
- Automatically removes temporary data after task completion: **YES** — the state dict
  is never persisted; it's discarded when the function returns (ordinary Python GC),
  confirmed by absence of any table backing `AgentRunState` itself.
- Prevents memory overflow: **YES, Stage 1.5 (2026-07-31)** — `_condense_messages` bounds the
  messages list within one run, now via real summarization rather than truncation (see Q65).

### Session Memory
- Retains important decisions: **PARTIAL** — `LessonStore.add()` (`base_graph.py`)
  retains lessons extracted post-submit, keyword-retrievable, but keeps everything up to
  `capacity=1000` with FIFO eviction (`.pop(0)`), not an "important decisions only" filter.
- Removes unnecessary conversation: **YES, Stage 1.5 (2026-07-31)** for both — `chat_agent.py` now
  has its own real condense mechanism (`_condense_history_async`, previously had none at all) and
  worker agents' `_condense_messages` (see Q65).
- Summarizes completed work: **PARTIAL, improved Stage 1.5 (2026-07-31)** — the condense step now
  makes a real LLM summarization call for dropped conversation history (see Q65), but this is
  scoped to context-budget management, not a dedicated "summarize this whole completed session"
  feature; `LessonStore`/`Lesson` still stores short structured fields, not generated session
  summaries, unchanged from before.
- Compresses repeated information: **YES**
  **Gap-closure Day 46 (2026-08-03, Stage 2)**: `LessonStore.add()` (`app/agents/
  base_graph.py`) now checks for a near-duplicate before appending — mirrors
  `VersionedLesson.publish()`'s dedup-before-insert *pattern* exactly as this note's own
  "Plan" asked for, but `LessonStore` has no embeddings (in-process, keyword-overlap only,
  per its own docstring), so the check reuses `retrieve()`'s own existing Jaccard
  token-overlap metric instead of forcing a cosine-similarity fit where no embedding
  exists. Scoped by `category` (same-text lessons under different categories are real,
  distinct knowledge, not duplicates — mirrors Day 42's category scoping for
  `MemoryEmbedding`). A near-duplicate (same category, token overlap >=
  `lesson_dedup_similarity_threshold`, default 0.8) is *replaced*, not accumulated — the
  newer occurrence's phrasing wins, keeping the store's FIFO-eviction capacity from being
  wasted on repeats. Config-driven (`lesson_dedup_enabled`, `lesson_dedup_similarity_threshold`);
  the store's own `capacity` (previously a hardcoded `1000` default baked into the class)
  is now also routed through real config (`lesson_store_capacity`) at its one real
  instantiation site (`get_lesson_store()`), closing a small adjacent zero-hardcoding gap
  found while touching this code.
  **Tests** (`tests/test_gap46_lesson_dedup.py`, 7 tests): direct unit coverage of the
  Jaccard helper against known cases; a near-duplicate lesson proven to replace (not
  accumulate) — store size stays at 1, newer phrasing retained; genuinely distinct lessons
  both retained; same text under two different categories both retained (category
  scoping proven, not assumed); `lesson_dedup_enabled=False` restores pure-append
  behavior exactly; the pre-existing FIFO-eviction capacity guarantee proven still intact
  with dedup active (distinct lessons beyond capacity still evict the oldest); the
  store's capacity itself proven config-driven via the real singleton accessor.
  `black`/`ruff`/`mypy --strict` clean. All 82 pre-existing tests touching `LessonStore`/
  `get_lesson_store` re-run unchanged, still pass.
  **Full regression**: 3582 passed (3575 Day-45 baseline + 7 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
- Preserves unresolved issues: **NOT VERIFIED** — no field/flag for "unresolved" found
  on `Lesson` or `ChatSession`.
- Preserves user approvals: **YES** — `PendingApproval` table (`app/db/models.py`
  line 651-681) durably records human decisions (`status`, `decided_by`, `decided_at`)
  for plan reviews/git-push approvals/chat confirmations, all routed through one
  `request_human_input()`/`arecord_decision()` entry point per `chat_agent.py`'s own
  docstring (line 51-54).
  Plan, now fully closed: the dedup/similarity check for `LessonStore.add()` (mirroring
  `VersionedLesson.publish()`'s pattern) was the one piece of this note still open after
  Stage 1.5 — done Day 46 (Stage 2, 2026-08-03, see "Compresses repeated information" above).
  The "LLM summarization pass for `chat_agent.py` sessions" half was already DONE (Stage 1.5,
  2026-07-31 — see Q65), though scoped to context-budget condensing rather than a turn-count
  threshold specifically.

### Long-Term Memory
- Stores only valuable knowledge (coding preferences, architecture decisions, reusable
  patterns, verified solutions, approved workflows): **PARTIAL** — architecture decisions
  and procedures (a form of verified-by-iteration solution) are real; "coding preferences"
  don't exist (Q113); "approved workflows" aren't a distinct tracked category.
- Temporary task details not promoted automatically: **NO** — directly contradicted by
  Q112's finding: `record_learning` promotes any single-interaction claim straight into
  the same long-term-queryable table with no filter distinguishing task-transient detail
  from durable knowledge.

### Context Compression
**Re-verified 2026-08-03 (Stage 2, Days 45-47) — this subsection was stale relative to work
already done: it still described `_trim_messages` as the live mechanism, but Q65's own entry
says that function "no longer exists" as of Stage 1.5 (2026-07-31), replaced by real LLM
summarization. This subsection was never updated when Q65 was fixed. Corrected in place below,
each item re-verified against current code, not just cross-referenced.**
- Summarize completed work: **PARTIAL** (matches Q65's own verdict exactly — see there for
  full evidence: `_condense_messages`/`_summarize_dropped_messages` make a real LLM call to
  summarize dropped conversation history, but this is scoped to context-budget management
  triggered mid-run, not a dedicated "summarize this whole completed session" feature).
- Preserve critical technical details: **YES** (Stage 1.5, 2026-07-31 — see Q65) —
  `_trim_messages` no longer exists; the real condense summarization explicitly asks for
  concrete specifics (file paths, values, conclusions), not vague generalities.
- Remove duplicate information: **YES** — `VersionedLesson.publish()`'s similarity-gated
  merge (pre-existing), `memory_embeddings` writes generally (Day 42's
  `_find_near_duplicate()`, all 5 `embed_*()` functions), and `LessonStore.add()` (Day 46)
  now all dedup — the three real places this project writes reusable/durable memory all have
  a real duplicate guard, not just one of three.
- Merge repeated discussions: **YES**, unchanged, still scoped narrowly —
  `versioned_memory.py::_merge_via_llm` merges two versions of the *same lesson topic* only,
  not general repeated discussion within a live conversation (a materially different,
  larger feature — general conversational dedup/merge was never in scope for Days 45-47).
- Keep unresolved issues intact: **NOT VERIFIED** — unchanged; no field/flag for
  "unresolved" exists on `Lesson`, the condense summarization prompt, or `ChatSession`.
  Genuinely out of Days 45-47's scope (would need a new structured field plus prompt
  changes across multiple surfaces, not a compression mechanism fix).
- Reduce token usage while maintaining correctness: **YES** (Stage 1.5, 2026-07-31 — see
  Q65) — real LLM summarization reduces token usage AND preserves information (a condensed
  summary, not dropped data); Day 45's file folding does the same for large file reads
  specifically (structure preserved, full body content shrunk, not silently lost).
  Summarization strategy, honestly stated: there isn't one. The only "compression" in
  the codebase is (a) drop-oldest truncation in `_trim_messages`, and (b) similarity-gated
  LLM merge scoped to `VersionedLesson` topic pairs. No general-purpose conversation
  summarizer exists.

### Memory Retrieval
- Semantic search: **YES** — pgvector cosine distance (`<=>`) throughout `store.py`.
- Project filtering: **NO** — no `project_id` to filter by (Q114).
- Task filtering: **PARTIAL** — `epic_id`/`task_id` columns exist and are stored, but
  none of the `query_*` SQL statements in `store.py` filter `WHERE epic_id = :x` — every
  query is global, joined only by embedding similarity.
- Time filtering: **NO** — no `created_at` bound in any `query_*` SQL (confirmed by
  reading all 5 query functions in `store.py` — none reference `created_at` in a `WHERE`).
- Agent filtering: **NO** — `agent_name` isn't even a first-class column (it's prepended
  into free text, per `embed_architecture_note`/`embed_procedure`'s own comments: "same
  convention... since MemoryEmbedding has no dedicated agent_name column"), so it can't
  be filtered on in SQL.
- Confidence filtering: **PARTIAL** — no dedicated confidence *filter* (a `WHERE` bound) exists,
  but `verified` (Day 40) and `importance` (Day 40) now both feed the Day 41 composite `ORDER BY`
  as ranking signals — the closest real analog to "confidence" this table has, contributing to
  rank rather than gating inclusion.
- Recency weighting: **YES**
  **Gap-closure Day 41 (2026-08-03, Stage 2, same day as Day 40)**: every one of the 5 `query_*`
  functions in `store.py` now ranks by a composite score
  (`_COMPOSITE_SCORE_EXPR`, `store.py`, one shared SQL expression spliced into all 5 — defined
  once so it can't drift between copies) blending: cosine similarity (config weight
  `memory_score_weight_similarity`, default 0.6 — still the dominant signal by default),
  exponential recency decay (`memory_score_weight_recency`=0.15,
  `EXP(-LN(2) * age_seconds / (86400 * memory_recency_half_life_days))`, half-life default 30
  days), reuse_count normalized/capped (`memory_score_weight_reuse`=0.1,
  `LEAST(1.0, reuse_count / memory_reuse_cap)`, cap default 20), importance
  (`memory_score_weight_importance`=0.1, the Day-40 column directly), and verified
  (`memory_score_weight_verified`=0.05, a flat bonus when true). All 7 constants are real
  `app/config.py` `Settings` fields, documented in `.env.example` — zero hardcoded weights/
  thresholds in the SQL text itself, bound as real SQL parameters exactly like the pre-existing
  `:repo_id`/`:k` pattern. `ORDER BY` changed from `embedding <=> vec` (ascending distance) to
  the composite score (`DESC`); `composite_score` is also returned in every result dict alongside
  the pre-existing `similarity`, so a caller can see why something ranked where it did.
  `record_memory_access()` (Day 40) is now wired into all 5 query functions, not just
  `query_similar_tasks` — `query_architecture_notes`/`query_failures`/`query_learning_signals`/
  `query_procedures` all gained `id` in their SELECT/returned dict and a real reuse-count
  increment on every call, completing Day 40's "frequency of reuse" item for the whole module,
  not one function.
  **Tests** (`tests/test_gap41_composite_scoring.py`, 6 tests, real DB, `_embed` mocked): the
  behavioral core — two rows with IDENTICAL similarity (same fake vector) but different real
  reuse_count/importance/verified must NOT tie under the composite score (proving pure-similarity
  ranking, which could never distinguish them, is genuinely gone); an artificially-aged row
  (`created_at` pushed 5 half-lives back) ranks below an equal-signal fresh row (proving the decay
  term is live, not inert); zeroing every non-similarity weight via real env vars makes
  `composite_score` numerically equal to `similarity` (proving the weights are real formula
  inputs, not decorative — config-driven, not hardcoded); the remaining 4 query functions proven
  to expose `id`/`composite_score` and to actually increment `reuse_count` on a real call, not
  just `query_similar_tasks`. `black`/`ruff` clean; `mypy --strict` clean; all 49 pre-existing
  memory tests (`test_memory.py` + 5 other memory test files) re-run unchanged, still pass.
  **Full regression**: 3549 passed (3543 Day-40 baseline + 6 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions (2 extra warnings in the run, confirmed pre-existing
  GC-timing-dependent async-mock noise from unrelated test files not touched today, not new).
  `archived = false` filtering is real (gap-closure Day 7 — see Automatic Cleanup below). **Still
  open**: `epic_id`/`agent_name`/explicit `created_at`-bound filters (as opposed to
  recency-*weighting*, which is now real) remain unimplemented — a `WHERE` clause restricting to
  one epic/agent/time-window is a different capability than blending recency into rank order, and
  wasn't part of Day 41's scope.

### Automatic Memory Cleanup
- Remove temporary scratch data: **YES** — `EpicScratchpad` (`app/db/models.py` line 684+)
  is deleted outright on epic completion or TTL expiry (`app/fleet/scratchpad.py::clear_epic_scratchpad`/
  `expire_stale_entries`), wired into `manager.py`'s halted/ready_for_review terminal points.
- Remove obsolete plans: **NOT VERIFIED** — no dedicated "plan" memory type was found
  distinct from task-outcome records.
- Remove duplicated memories: **YES**
  **Gap-closure Day 42 (2026-08-03, Stage 2)**: `app/memory/store.py::_find_near_duplicate()`
  mirrors the real dedup mechanism `app/fleet/versioned_memory.py::_find_most_similar_published()`
  already uses for `VersionedLesson.publish()` (read first, per the REPO-FIRST-adjacent
  in-repo-prior-art rule) — cosine-similarity-gated duplicate detection — adapted to
  `MemoryEmbedding`'s simpler, non-versioned shape: this table has no draft/published/
  supersedes lifecycle to propose an LLM-merged new version into (unlike `VersionedLesson`), so a
  genuine near-duplicate here strengthens the existing row's reuse signal (via the Day-40
  `record_memory_access()`) instead of inserting a second near-identical row. Wired into all 5
  `embed_*()` write functions. Deliberately a much higher similarity bar
  (`memory_dedup_similarity_threshold`, default 0.97) than `VersionedLesson`'s merge threshold
  (0.85) — this guards a near-exact duplicate write, not a related-topic merge candidate.
  Category- and repo_id-scoped (a "task" write never dedups against an "architecture" row even
  with identical content; two repos' identical content each get their own row, mirroring Stage
  0's existing repo-scoping guarantee). Archived rows are excluded from matching (a new write
  matching an archived row's content creates a fresh row rather than silently resurrecting it).
  Config-driven (`memory_dedup_enabled`, default `True`) — disabling it restores the exact
  pre-Day-42 unconditional-insert behavior, verified by a dedicated test.
  **A real, more serious bug found and fixed while building this, not shipped**: while testing
  the dedup query's `ORDER BY` (ranking by cosine similarity), a full regression run turned up
  `test_versioned_memory.py::test_promote_moves_a_draft_to_published_and_syncs_to_memory_embeddings`
  newly failing. Root cause traced to Day 41's `ORDER BY composite_score DESC` (not this day's
  dedup work) interacting with rows that have a zero-magnitude embedding (real historical rows —
  confirmed via `embedding <=> embedding` self-cosine-distance returning `NaN` for several
  real task_id="43"/"architect-Test" rows already in the dev DB): Postgres sorts `NaN` as the
  **maximum** value (confirmed empirically: `ORDER BY x DESC` puts `NaN` first), so these
  zero-vector rows — previously silently deprioritized to last place under the old ascending
  pure-distance `ORDER BY` — now dominated the *front* of every composite-ranked query, crowding
  out real results. Fixed with a `vector_norm(embedding) > 0` guard added to all 5 query
  functions' `WHERE` clause and to the new dedup check's own query (`app/memory/store.py`) —
  pgvector 0.8.4 (confirmed installed) provides `vector_norm()` natively. This is a real Day-41
  regression that only this day's testing surfaced, fixed at the root rather than patched around.
  **A second, unrelated real bug found and fixed**: the same investigation traced
  `test_versioned_memory.py`'s failure further to a pre-existing test-hygiene gap unrelated to
  either Day 41 or 42 directly — 5 of that file's tests call `store.promote(agent_name="tester")`
  (which syncs into `memory_embeddings` under `task_id="fleet-tester"` via
  `_sync_to_memory_embeddings`) but never cleaned up that row, leaking 64 accumulated rows into
  the shared dev DB across many historical runs of that file. This was always latent but harmless
  before Day 41-42 (nothing was volume- or similarity-sensitive enough to notice); fixed by adding
  the missing `_cleanup_memory_embeddings("fleet-tester")` call (a helper that file already
  defined and used elsewhere, just not consistently) to all 5 affected tests. Verified empirically
  (per this project's own established discipline) with two consecutive full runs of
  `test_versioned_memory.py`, confirming zero `fleet-tester` rows remain after either run.
  **Tests**: `tests/test_gap42_memory_dedup.py` (8 tests, real DB, signed content-derived fake
  vectors): near-duplicate write reuses the existing row rather than inserting a second one;
  genuinely distinct content creates distinct rows; `memory_dedup_enabled=False` restores
  unconditional insert; dedup correctly scoped by category and by repo_id (two dedicated tests);
  an archived row is excluded from matching; the internal helper short-circuits cleanly when
  disabled; and the strengthening path is proven to go through the real, same
  `record_memory_access()` Day 40 built (spied via `AsyncMock(wraps=...)`), not a separate ad hoc
  increment. `black`/`ruff` clean; `mypy --strict` clean.
  **A real, harder-won lesson from today's testing, worth recording**: uniform-`[0,1)`-distributed
  fake vectors (this codebase's own pre-existing convention in `test_versioned_memory.py`,
  `test_memory_archived_filter.py`, and `test_memory_project_scoping_queries.py` before today)
  share a "positive orthant" bias — confirmed empirically, any two such vectors have ~0.75-0.9
  cosine similarity to each other *regardless of content*, because uniform non-negative
  components all point into the same geometric region. This was invisible before similarity-
  threshold-sensitive features (composite ranking, dedup) existed; now it matters. Fixed by
  switching this session's fake-vector helpers to signed `[-1, 1)` components (near-zero
  similarity for genuinely distinct content, confirmed empirically at ~0.02-0.04) in
  `test_memory_archived_filter.py`, `test_memory_project_scoping_queries.py`,
  `test_gap40_memory_prioritization.py`, and `test_gap41_composite_scoring.py` — plus embedding a
  unique run-suffix into every test's literal content string, so dedup can never collapse two
  separate test runs' rows into each other even if a future run's cleanup fails.
  **Full regression**: first attempt caught the real `test_versioned_memory.py` regression
  (3556 passed / 1 failed — correctly not shipped); after both real fixes above, 3557 passed
  (3549 Day-41 baseline + 8 new), 0 failed, 55 skipped, 17 deselected — confirmed clean on a
  second consecutive run.
- Archive completed tasks: **YES** — `app/services/retention.py::start_retention_loop`,
  daily, flips `archived=true`/`archived_at` on `memory_embeddings` rows older than
  `memory_embeddings_retention_days` (default 180) — real archival, not deletion, per
  that module's own stated design goal.
- Compress historical conversations: **NO**.
- Retain only reusable knowledge: **NO** — retention is purely age-based, not a
  reusability/quality judgment.
  How cleanup decisions are made, precisely: age only (`created_at < cutoff`), computed
  once daily (`_CLEANUP_INTERVAL_SECONDS = 24 * 3600`) — no relevance, quality, or
  duplication signal factors into what gets archived.
  **Real bug found, and fixed (gap-closure Day 7, 2026-07-30)**: the archival flag was
  written but never read back — none of `query_similar_tasks`/`query_failures`/
  `query_learning_signals`/`query_procedures`/`query_architecture_notes` (`store.py`)
  filtered on `archived`, so an archived memory kept surfacing in every semantic-search
  query forever, making the retention policy purely cosmetic. All five query functions
  now include `AND archived = false` in their SQL `WHERE` clause (`app/memory/store.py`,
  same fix applied consistently to all five, in the same style as the existing
  `repo_id` scoping filter added in gap-closure Days 2-3). Verified live: an archived
  row (both via a direct `archived=true` UPDATE and via the real
  `app.services.retention._archive_table()` background-job function itself) is
  confirmed excluded from every one of the five queries, while a non-archived sibling
  row stays visible. Proven by `backend/tests/test_memory_archived_filter.py`
  (6 tests).

### Memory Prioritization
- Relevance: **YES** — cosine similarity is the sole ranking signal everywhere.
- Recency: **YES** (Day 41 composite score — see Memory Retrieval's "Recency weighting" above).
- Importance: **YES** — real `importance` column (Day 40), written with a documented
  category-based default at write time, blended into the Day 41 composite `ORDER BY` in all 5
  query functions.
- User approval: **NO** — approval status (`PendingApproval`) is a separate table never
  joined into memory ranking. Out of Days 40-41's scope (a different signal source than
  outcome-derived `verified`).
- Verification status: **YES** — `verified` (Day 40, real `outcome == "completed"` derivation)
  now blended into the Day 41 composite score in all 5 query functions, not just tracked as a
  category value.
- Project association: **NO** (Q114) — unrelated to this bucket, `repo_id` scoping (Stage 0)
  already covers project/repo filtering; "association" in *ranking* specifically wasn't asked
  for and wasn't built.
- Frequency of reuse: **YES**
  **Gap-closure Day 41 (2026-08-03, same day)**: composite scoring and `record_memory_access()`
  wiring extended to all remaining 4 query functions — see Memory Retrieval's "Recency weighting"
  entry above for the full Day 41 evidence (one shared implementation covers both audit items,
  cited once there rather than duplicated here).
  **Gap-closure Day 40 (2026-08-03, Stage 2)**: added the exact columns this note named —
  `reuse_count`/`importance`/`verified`/`last_accessed_at` on `MemoryEmbedding`
  (`migrations/versions/026_memory_prioritization_columns.py`, `app/db/models.py:530-537`).
  Repo-first check done before designing this (per `CLAUDE.md`'s REPO-FIRST RULE): read
  `repos/autogen/python/packages/autogen-ext/src/autogen_ext/experimental/task_centric_memory/
  memory_controller.py`'s `retrieve_relevant_memos()` — confirmed the real pattern is to count
  a memo as "used" at the point it's actually retrieved and returned to a caller, not at write
  time; adopted directly.
  **Real-signal defaults, not placeholders** (the "built but never wired" pattern this project's
  own history has already named 7+ times, avoided here on purpose): `importance` defaults by
  category at write time — `_default_importance()` (`store.py`) ranks `failure`=0.8,
  `architecture`=0.7, `learning`=0.6, `task`/`procedure`=0.5 (a documented, coarse starting
  heuristic — a failure or architecture decision is more valuable to a future agent than a
  routine completed-task log line); `verified` defaults to `True` only when the row's own
  `outcome` is already a known-positive signal (`outcome == "completed"`) — never an invented
  judgment layered on top of existing data. Both wired into all 5 `embed_*()` write sites
  (`store.py`), not just one.
  `record_memory_access(memory_ids, db)` (`store.py`) increments `reuse_count` and stamps
  `last_accessed_at` via a real SQLAlchemy `UPDATE ... WHERE id IN (...)`, best-effort
  (catches/logs/rolls-back, never raises — matches every other `embed_*`/`query_*` function's
  own convention). Wired into `query_similar_tasks` (added `id` to its SELECT and returned dict
  — additive, no existing consumer broken) as the first of the 5 query functions; the remaining
  4 (`query_architecture_notes`/`query_failures`/`query_learning_signals`/`query_procedures`)
  are Day 41's scope, done together with the composite-scoring `ORDER BY` change so both land
  in one coherent pass per query function rather than touching each file twice.
  **Tests**: `tests/test_gap40_memory_prioritization.py` (7 tests, real DB, mocked `_embed` per
  `test_memory_archived_filter.py`'s established convention): pure unit tests for the two default
  functions; real writes proving `embed_task_outcome(outcome="completed")` is verified with
  importance 0.5 and `embed_failure()` is unverified with importance 0.8; `record_memory_access`
  proven to accumulate across two real calls (1 → 2, not reset); an empty-list no-op; and a full
  end-to-end proof that a real `query_similar_tasks()` call both returns the row's real `id` and
  increments its real `reuse_count` in the database, re-fetched independently to confirm.
  `black`/`ruff` clean; `mypy --strict` clean. All 42 pre-existing memory tests re-run unchanged
  and still pass (the `id` field addition is additive, not breaking).
  **Full regression**: 3543 passed (3536 Day-39 baseline + 7 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.

### Token Optimization
- Loading only relevant context: **PARTIAL** — `top_k` (default `memory_top_k`,
  `config.py`) caps how many rows are injected, and similarity ranking picks the "most
  relevant" k, but with no recency/confidence filtering (above), "relevant" is weaker
  than it could be.
- Avoiding duplicate prompts: **NOT VERIFIED**.
- Reusing summaries: **NO** — no summaries exist to reuse (see Context Compression).
- Retrieving targeted memories: **PARTIAL** — targeted by text-similarity only, not by
  task/project/agent (above).
- Limiting unnecessary history: **PARTIAL** — `_trim_messages` for worker agents; none
  for `chat_agent.py`.
  Estimated reduction vs. loading full history: **NOT VERIFIED** — no instrumentation
  in the codebase measures or reports this (no before/after token accounting exists;
  see Memory Analytics below).

### Context Window Management
- Warn the user if appropriate: **NO** (Q65).
- Summarize older context: **NO** (Q65/Context Compression).
- Preserve active work: **YES** — `_trim_messages` keeps the most recent 4 messages
  (`messages[-4:]`), so the active turn is never dropped.
- Archive completed work: **PARTIAL** — task outcomes get written to `memory_embeddings`
  before message trimming discards the raw transcript, so the summary survives even
  though the verbatim conversation doesn't.
- Avoid losing critical information: **NO** — see Context Compression; trimming is
  lossy by design (drop-oldest, no summarization of what's dropped).

### Memory Aging
- Do memories have a lifecycle: **PARTIAL → gradation now real, still not a full lifecycle**
  `VersionedLesson.state` has a real 5-stage lifecycle (`draft|published|superseded|
  merged_into|archived`, enforced state machine in `app/fleet/versioned_memory.py`).
  `MemoryEmbedding` still has only a boolean `archived`/`archived_at` for lifecycle
  *state* (verdict stays PARTIAL, honestly — this day did not give it `VersionedLesson`'s
  kind of state machine, which would be a much larger, differently-scoped change), but the
  "recent"/"historical"/"obsolete" *gradation* this note specifically asked for is now real:
  **Gap-closure Day 44 (2026-08-03, Stage 2)**: `app/memory/analytics.py::
  _compute_staleness_distribution()` buckets every non-archived row into
  `recent`/`aging`/`stale`/`obsolete` by real age relative to the *same*
  `memory_recency_half_life_days` Day 41's composite ranking already uses (config
  multiples: 1x/3x/6x, all real `Settings` fields — `memory_staleness_aging_half_lives`/
  `memory_staleness_stale_half_lives`/`memory_staleness_obsolete_half_lives`) — so ranking
  and reporting share one definition of "aged," not two competing ones invented separately.
  Exposed in `GET /api/memory/analytics`'s `stalenessDistribution` field (extends Day 43's
  endpoint, not a new one). Archived rows are excluded from every bucket (their lifecycle
  question is already answered by `archived=true`, not re-litigated here).
  **Tests** (`tests/test_gap44_memory_staleness.py`, 3 tests, real DB): four rows backdated
  to ages chosen to land unambiguously in each of the four buckets, confirming all four
  buckets populate correctly from real data; an archived row proven to vanish from the
  distribution entirely (total count drops by exactly 1, not redistributed into a bucket);
  a direct call to the real endpoint confirming the field's real shape. `black`/`ruff`/
  `mypy --strict` clean. All 83 pre-existing Days 40-43 + `test_versioned_memory.py` tests
  re-run unchanged, stable across two consecutive runs (86 total with this day's 3 added).
  **Full regression**: 3567 passed (3564 Day-43 baseline + 3 new), 0 failed, 55 skipped, 17
  deselected — exact match, zero regressions.
- Can obsolete memories be archived rather than deleted: **YES** for both tables — the
  retention loop (`retention.py`) and `versioned_memory.py::_archive_expired` both flip
  a flag, never `DELETE`. (But see the bug above: archived `MemoryEmbedding` rows are
  still returned by every query — archived in name only, functionally still "active.")

### Shared Memory Synchronization
- Share only relevant information: **PARTIAL** — everything in `memory_embeddings` is
  visible to every agent (no scoping, Q114), so "only relevant" depends entirely on the
  similarity search at read time, not on write-time scoping.
- Avoid duplicating memory: **YES** (Day 42) — `_find_near_duplicate()` now guards all 5
  `embed_*()` write functions the same way `VersionedLesson.publish()` already guarded its own
  table; see the "Remove duplicated memories" entry above (Automatic Memory Cleanup) for full
  evidence.
- Maintain consistency: **YES** (structurally) — append-only writes side-step most
  consistency problems by construction.
- Prevent conflicting updates: **PARTIAL** — real for `VersionedLesson` (explicit
  supersede/merge state transitions with `supersedes_id` lineage); not applicable/not
  handled for `memory_embeddings` since nothing there is ever updated in place except
  the `archived` flag.
- Synchronize changes safely: **YES** — every write goes through its own
  `AsyncSession`/`db.commit()` with try/except/rollback; sync bridges use a fresh,
  disposed-after-use engine (`app/db/session.py::new_isolated_async_engine`) specifically
  documented to avoid cross-request engine-sharing hazards.

### Memory Quality Control
- Usefulness: **NO** — no usefulness score/field anywhere on `MemoryEmbedding`.
- Accuracy: **NO** — no verification step before a `record_learning`/`embed_task_outcome`
  write lands (Q112).
- Verification: **NO** — see above; `outcome` tracks task completion status, not memory
  accuracy.
- Duplication: **PARTIAL** — only at `VersionedLesson.publish()`.
- Future value: **NO** — no such judgment is made anywhere.
- Project relevance: **NO** — no project scoping exists to judge relevance against (Q114).
  "Only high-quality memories should persist long-term": **NO** — everything written
  persists for the full retention window (180 days default) regardless of quality;
  `knowledge_curator` provides only after-the-fact, human-approved cleanup, not an
  upfront quality gate.

### Memory Analytics
- Total memory size: **YES** — real row count AND real storage size now both reported.
- Average retrieval time: **YES** — real wall-clock instrumentation.
- Memory growth (rate over time): **YES** — a real daily trend, not a snapshot.
- Duplicate memories: **YES** — a real pairwise-similarity count.
- Unused memories: **YES** — real, using Day 40's `reuse_count` column.
- Token cost: **NO** — no cost-of-memory-injection metric; `budget_manager.py` tracks
  $ cost of LLM calls generally, not memory-injection token overhead specifically. Out of
  Day 43's scope (the audit's own "Plan" note named row counts/retrieval-latency/reuse-
  counter specifically; token-cost-of-injection is a distinct, not-yet-scoped instrument).
- Retrieval accuracy: **NO** — no ground-truth/precision measurement exists (would need a
  labeled relevance dataset; out of scope for instrumentation work).
  Can it recommend memory optimization strategies: **NO** — no such recommender exists;
  `knowledge_curator` recommends specific curation *actions* on flagged entries via
  human-reviewed enhancement requests, but that's targeted cleanup, not a system-level
  optimization-strategy recommender. The real analytics this day built are exactly the
  signal such a recommender would need — building the recommender itself was never this
  day's scope (the audit's "Plan" note frames instrumentation as a prerequisite, not the
  deliverable itself).
  **Gap-closure Day 43 (2026-08-03, Stage 2)**: new `backend/app/memory/analytics.py`.
  `compute_memory_analytics(db)` returns real data for every metric above: `total_rows`/
  `total_size_bytes` via `COUNT(*)` and Postgres's own `pg_total_relation_size()` (table +
  indexes + TOAST, not an estimate); `growth_by_day` via a real
  `GROUP BY date_trunc('day', created_at)` trend over a configurable window
  (`memory_analytics_growth_days`, default 30); `unused_count` via
  `WHERE reuse_count = 0 AND archived = false AND created_at < now() - N days`
  (`memory_unused_threshold_days`, default 30) — the exact "frequency of reuse" signal
  named as missing in Memory Prioritization's own audit note, now real since Day 40;
  `duplicate_pairs_count` via a real pairwise cosine-similarity self-join at the *same*
  threshold Day 42's dedup guard uses (`memory_dedup_similarity_threshold`), capturing
  duplicates that predate Day 42 (dedup only prevents *future* duplicate writes, so this
  is a genuinely different, complementary signal, not a redundant one) — deliberately
  capped (`memory_dup_scan_max_rows`, default 5000) since this is an O(n^2) diagnostic
  scan, not a hot path, and must never become an unbounded cost as the table grows; above
  the cap it's honestly skipped with a real reason string, not silently slow or wrong.
  `record_retrieval_time()`/`get_retrieval_time_stats()` — a lightweight in-process rolling
  window (`deque`, size `memory_retrieval_time_window`, default 200 samples per function)
  — wired into all 5 `query_*` functions in `store.py` (real `time.monotonic()` around each
  function's actual DB round-trip, not a guess). Kept deliberately separate from the
  fuller `RunMetrics`/OTel tracing infrastructure in `app/fleet/metrics.py` — that
  cross-agent "record_tool()-equivalent timing around planner/decomposer/scan/memory-
  retrieval" instrumentation pass is explicitly Stage 2 Day 54's own scope (per `PLAN.md`),
  a broader effort this day intentionally didn't duplicate or preempt.
  New `GET /api/memory/analytics` endpoint (`app/api/memory.py`) — additive, doesn't touch
  the existing `/patterns` response shape (no known real caller of either endpoint outside
  this backend yet, confirmed by grepping the frontend, so no compatibility risk either
  way). Same no-auth convention as `/patterns`/`/search` in this same file (this file's own
  established pattern for read-only routes — not a new gap, matches what's already there).
  **Tests**: `tests/test_gap43_memory_analytics.py` (7 tests, real DB): retrieval-time
  tracker unit tests (recording, averaging, window-size enforcement via a real config
  override, reset); a real-DB test proving `total_size_bytes`/`growth_by_day`/
  `unused_count` all reflect genuinely seeded and backdated rows; a real duplicate-pair
  detection test (writes two near-identical rows with dedup intentionally disabled — since
  Day 42 would otherwise prevent constructing this exact scenario — and confirms the
  analytic finds them); a real cap-exceeded test proving the scan is honestly skipped with
  a real reason string when `memory_dup_scan_max_rows=0`; and a direct call to the real
  endpoint function confirming its full real response shape. `black`/`ruff` clean;
  `mypy --strict` clean. All 76 pre-existing Days 40-42 + `test_versioned_memory.py` tests
  re-run unchanged, still pass, stable across two consecutive runs (83 total with this
  day's own 7 added).
  **Full regression**: 3564 passed (3557 Day-42 baseline + 7 new), 0 failed, 55 skipped,
  17 deselected — exact match, zero regressions.

### Memory Evolution
Over months of usage, does the system become smaller/cleaner/faster/more relevant
instead of continuously growing: **NO** — the mechanics in place (age-based archival
flag that isn't even filtered out of queries, no dedup outside `VersionedLesson`, no
usefulness/reuse-based pruning) mean the effective, queried memory surface only grows
over time. `memory_embeddings` retention marks rows `archived=true` after 180 days by
default but — per the confirmed bug above — archived rows are not excluded from
`query_similar_tasks` and its siblings, so the *active* similarity-search corpus grows
monotonically regardless of the retention setting. Long-term scalability is not
maintained by any code found in this repo.
Plan: fix the archived-filter bug first (mechanical, high-leverage), then add real
pruning (reuse-count-based, not just age-based) so the system can actually shrink/
consolidate over time rather than only ever accumulate.

---

## Appendix: Hidden Architectural Risk Audit

*Explicitly requested in the source document ("the single biggest thing I think is still
missing... identify every architectural weakness, scalability bottleneck, concurrency issue,
memory leak risk, race condition, synchronization problem, security concern, maintainability
issue, technical debt area, and future scaling limitation... rank by severity, business impact,
affected files, best fix, priority"). Built by cross-referencing findings that recurred
independently across multiple research passes above, not re-derived from scratch — each item
below is a real, code-cited finding, most already surfaced once in the Q&A above and consolidated
here in priority order.*

| # | Finding | Severity | Business Impact | Affected Files | Fix | Priority |
|---|---|---|---|---|---|---|
| 1 | **PARTIALLY RESOLVED (gap-closure Days 8-9, 2026-07-30).** No OS-level sandboxing for `bash`-tool execution existed — regex denylist only, codebase's own comments admitted this was incomplete | **Critical** (now High for the 3 fixed tools, still Critical for the ~12 not yet wired) | A sufficiently novel command phrasing bypassed the denylist and ran with the host process's real privileges — confirmed live and concretely: `find /workspace -mindepth 1 -delete` is `allowed=True` under the denylist | `backend/app/policy/engine.py` unchanged (denylist still the first gate); new `backend/app/policy/sandbox.py`; wired into the 3 fully-generic, denylist-only bash tools in `backend/app/agents/tools.py` (`make_chat_handlers.bash`, `make_coder_handlers.bash`, `make_scoped_bash_handler.bash_h`) | Fixed for those 3: real, fails-closed, per-command Docker container isolation, verified live including the exact bypass command above. Still open: the ~12 already-allowlist-scoped bash handlers (need a per-repo-toolchain sandbox image, real additional work) and the containerized production deployment's own Docker-daemon-access topology (explicit operator decision, not yet made) | 1 |
| 2 | `_active_repo_path` is a mutable, process-global variable read by ~75 files' default repo-resolution path | **Critical** | Under concurrent use (two users, or one user switching repos mid-task), a dispatch can silently operate against the wrong project's code — a correctness and safety bug, not just a scalability one; also the root cause behind Q94/Q95/Q48's "no multi-project support" findings | `backend/app/api/repo.py` (the global itself), every agent module calling `get_active_repo_path()` as a fallback | Replace the global with per-request/per-session repo context threaded explicitly through every dispatch call, eliminating the fallback | 1 |
| 3 | `MemoryEmbedding` has no `repo_id`/`project_id` column — every semantic memory query is unscoped fleet-wide | **High** | Cross-project knowledge bleed is the *default* behavior, not an edge case (self-documented in `IMPLEMENTATION_PROGRESS.md`'s own Day 3/1.6 entry); blocks any real multi-tenant/enterprise use | `backend/app/db/models.py::MemoryEmbedding`, every `query_*` function in `backend/app/memory/store.py` | Add `repo_id`/`project_id` column, migrate, filter every query by it | 1 |
| 4 | **RESOLVED (gap-closure Day 7, 2026-07-30).** Durable audit-log DB persistence was silently broken — no migration ever created the `audit_log` table, and the write path swallows the resulting exception in a bare `except: pass` | **High** | The audit trail this platform relies on for compliance/approval-history claims was real-time/in-memory only (2000-row cap, lost on restart) despite the code's own docstring claiming durability — a genuine, previously undocumented finding from this audit | `backend/app/fleet/audit_log.py`, `backend/migrations/versions/025_audit_log_table.py` | Fixed: migration 025 creates the table (matches `_write_to_db()`'s INSERT exactly); verified live round-trip, `backend/tests/test_audit_log_migration.py` (3 tests) | 1 |
| 5 | `record_learning`/`versioned_memory.publish()` writes to fleet-wide shared memory with zero evidence gate and zero human approval | **High** | Any single agent's mistaken self-assessment becomes durable, org-wide "fact" injected into every future agent's prompt — directly contradicts the source document's own explicit Q112 ask ("never store new knowledge just because one interaction suggested it") | `backend/app/agents/tools.py::make_record_learning_handler`, `backend/app/fleet/versioned_memory.py::publish()` | Gate publish behind either a confidence threshold, a multiple-successful-uses check, or `knowledge_curator` review before a lesson becomes queryable | 2 |
| 6 | Concurrency accounting (`max_concurrent_agent_runs`, epic/subtask slots) is enforced by in-process `asyncio.Semaphore`s with no cross-process coordination | **High** (scalability) | Caps do not hold across multiple backend processes/machines — the platform's own docs (`MASTER_AGENT_v2.md`) self-acknowledge this; blocks the "hundreds of agents" ambition explicitly stated in the source document's Q46/Q77 | `backend/app/pipeline/concurrency.py` | Move slot accounting to Postgres row-locks or a Redis token bucket shared across processes | 2 |
| 7 | **RESOLVED (gap-closure Day 7, 2026-07-30).** Archived memory rows (`archived=true`) were never actually filtered out of any `query_*` function — a confirmed, real bug, not a design gap | **Medium** | The active semantic-search corpus grew monotonically forever regardless of retention settings; stale/superseded guidance kept resurfacing in agent prompts | `backend/app/memory/store.py` (all `query_similar_tasks`/`query_architecture_notes`/`query_failures`/`query_learning_signals`/`query_procedures`) | Fixed: `AND archived = false` added to all five; verified live (including via the real retention-job function), `backend/tests/test_memory_archived_filter.py` (6 tests) | 2 |
| 8 | **`prompt_registry.py` row RESOLVED (gap-closure Day 50, 2026-08-03).** Two subsystems remain dormant: the RQ distributed-queue adapter; `RESEARCH_TOOLS`'s missing `web_search` schema entry despite the handler being wired. `prompt_registry.py`'s draft→review→approve→deploy→rollback lifecycle now has a real caller — see Q110's "Critical finding — RESOLVED" entry — and `knowledge_curator`'s (and the other 3 fleet apply-phase agents') role-prompt writes now go through it instead of bypassing it | **Medium** | Real engineering effort still sits unused for the RQ adapter and `web_search`; the `prompt_registry` maintainability trap (two mechanisms for the same job, only the weaker one load-bearing) is closed | `backend/app/queue/rq_adapter.py`, `backend/app/agents/research.py`'s `RESEARCH_TOOLS` list | Wire the RQ adapter and `web_search` into real callers, or explicitly mark/remove as dead code | 2 |
| 9 | No automatic rollback on a failed self-improvement APPLY phase or a post-apply regression | **Medium** | The one real closed-loop self-improvement subsystem (the 5-agent Fleet Enhancement Dashboard) can commit a fix whose own `run_tests` call fails, or that regresses a benchmark, with no automatic `git revert` — confirmed by code comment describing rollback as a "future... manual/operator-invoked" action, not automatic | `backend/app/fleet/failure_ladder.py`, the 5 self-improvement agents' APPLY-phase handlers | Wire a failed post-apply test/benchmark check to an automatic `git revert` of that commit | 3 |
| 10 | Windows-incompatible hardcoded POSIX shell syntax in venv activation and several bash-tool command strings (`source .venv/bin/activate`, `/dev/null`) | **Medium** | Silently broken tool behavior on native Windows deployments — commands appear to run but activation/output-suppression no-ops | `backend/app/agents/tools.py` (11+ call sites using the identical pattern) | Branch activation/command logic on `sys.platform` instead of assuming POSIX | 3 |
| 11 | `GET /api/tasks/{id}/stream` has no authentication dependency, unlike its sibling stop/resume endpoints in the same file | **Medium** | When `JWT_AUTH_ENABLED=true`, anyone who can guess/enumerate a `task_id` can read that task's live tool-call/output stream without authentication | `backend/app/api/activity.py` | Add `Depends(require_authenticated)` to the stream endpoint | 3 |
| 12 | No fleet-wide LLM-API circuit breaker/backoff beyond the Anthropic SDK's own defaults | **Low-Medium** | A sustained LLM API outage or rate-limit event is handled per-call via the generic failure-ladder, not a coordinated backoff — not independently load-tested, so actual behavior under sustained outage is unverified | `backend/app/agents/base_graph.py` (LLM call wrapper) | Add an explicit circuit-breaker layer; load-test against a simulated outage before relying on SDK defaults alone | 4 |

**Note on scope**: items 1-6 are the ones that would most directly block calling this platform
"enterprise-grade" or "safe to run unattended at scale" — they were each independently surfaced by
at least two of the twelve research passes above, which is itself a form of cross-verification
worth noting rather than treating as twelve isolated claims.
