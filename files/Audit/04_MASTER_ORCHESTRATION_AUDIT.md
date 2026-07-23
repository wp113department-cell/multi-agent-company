# MASTER ORCHESTRATION AUDIT — Pipeline, Manager Loop, Approvals, Failure Recovery

# DO NOT WRITE OR MODIFY CODE. READ-ONLY AUDIT.

You are a Principal LangGraph Engineer + Principal Backend Architect. Audit
the FULL execution orchestration of this system: how a task goes from
"created" to "completed/blocked/rejected", across BOTH real entry points,
under normal and failure conditions.

## PHASE 0 — Orientation

Read in full:
- `backend/app/api/tasks.py` and `backend/app/api/agents.py` — every
  endpoint that starts/resumes/approves/rejects a task
- `backend/app/pipeline/graph.py` — `run_planning_pipeline()`,
  `resume_pipeline()`, `human_review_node`, checkpointer setup/close
- `backend/app/agents/manager.py` — `run_manager()`, `launch_manager()`,
  the per-subtask dev→qa→review retry loop, retry cap, halt conditions
- `backend/app/fleet/approval_gate.py` — `pending_approvals` tracking,
  sync + async facades
- `backend/app/fleet/failure_ladder.py` — checkpoint / rollback / escalate /
  abort / resume / human_review implementations and their real call sites
- `backend/app/pipeline/concurrency.py`, `queue_adapter.py`,
  `conflict_guard.py`
- `backend/app/repo_tools/worktree.py` — namespacing by epic/task,
  preserve/cleanup logic
- `backend/app/db/models.py` — `DevTask` status enum and
  `VALID_TRANSITIONS` (wherever the state machine lives)

## PHASE 1 — Two-Entry-Point Parity Audit

This project has TWO real task lifecycles:
- **Simple mode**: `launch_planner` → human approves → `launch_coder`
- **Full mode**: `launch_planning_pipeline` (LangGraph, checkpointed,
  `interrupt()`-paused at human_review) → `resume_pipeline` →
  `launch_manager` → `run_manager`'s dev→qa→review loop per subtask

PROJECT.md documents multiple real bugs where a feature (bootstrap-on-blank-
repo, repo_id resolution, image forwarding, credential injection) was wired
into ONLY ONE of these two paths. For EVERY feature below, check BOTH paths
explicitly and report which path(s) it's actually wired into:

- [ ] Blank-repo bootstrap (`app/pipeline/bootstrap.py`)
- [ ] Repo resolution (`task.repo_id` → correct `local_path` passed to
      `create_worktree`)
- [ ] Task image forwarding (Day 16) into agent calls
- [ ] Custom credential injection (`extra_env`, Day 17) into bash tool calls
- [ ] Git commit-after-write (the fix ensuring Reviewer actually reviews a
      real diff)
- [ ] Git push / PR creation approval flow (Day 14)
- [ ] Activity-stream `task_id` threading (Day 18)
- [ ] Failure-transition-to-"blocked" on exception (confirm BOTH
      `launch_coder` and `launch_manager` transition to a terminal-ish state
      on failure, not leaving the task stuck in an in-progress status
      forever — PROJECT.md documents `launch_coder` once had this gap)

## PHASE 2 — State Machine Audit

- Extract the full `VALID_TRANSITIONS` table from code (not from memory of
  PROJECT.md) and diagram it.
- Find any status a task can enter but never leave (dead-end states).
- Find any status transition needed by the code but missing from the table
  (PROJECT.md documents `"planning"` → `"rejected"` was once missing,
  breaking the reject-during-approval-pause path — confirm still fixed,
  and check for OTHER missing transitions the same way: grep every
  `transition_task(db, task_id, "<status>")` call site and cross-check each
  target status against the table).
- Confirm `pr_status` (`none|pending|pushed|failed`) transitions are
  similarly complete for the git-push sub-flow.

## PHASE 3 — Human-in-the-Loop Correctness

- Confirm `interrupt()`/`Command(resume=...)` in `pipeline/graph.py` behaves
  as this project's own Day 13 empirical finding states: the ENTIRE node
  body re-runs from the top on resume. Check every node that uses
  `interrupt()` for any state mutation BEFORE the interrupt call that would
  incorrectly re-execute on resume (e.g. double-incrementing a counter,
  double-publishing an event).
- Confirm `approval_gate.record_pending()` correctly supersedes a prior
  undecided row for the same `thread_id` (Days 11-13 gap-closure fix) rather
  than accumulating orphaned pending rows — trace the actual superseding
  logic.
- Confirm every `interrupt()`-pausing code path (plan review, git push)
  registers into the SAME `pending_approvals` system, not a parallel
  ad-hoc mechanism — grep for any approval-like DB write NOT going through
  `approval_gate.py`.
- Confirm `/api/approvals/*` endpoints have correct 404/409 semantics for
  double-decision and unknown-thread cases.

## PHASE 4 — Failure Recovery Ladder Audit

For each of: Checkpoint, Rollback, Escalate, Abort, Resume, Human Review —
find the REAL call site (not just the function definition) and confirm it's
reachable from an actual failure condition, not just unit-tested in
isolation. Cross-check against PROJECT.md's Day 12 finding that Abort was
once genuinely unreachable (no transition ever led to `"failed"`).

## PHASE 5 — Concurrency & Conflict Safety

- Confirm `epic_slot()`, `agent_run_slot()`, `subtask_slot(epic_id)`
  semaphores are actually acquired/released around the real dispatch paths
  (not just defined and unused).
- Confirm `conflict_guard.check_file_conflicts()` is called before two
  concurrent epics could write the same file, and trace what happens on a
  detected conflict (blocked? queued? silently ignored?).
- Confirm worktree paths are namespaced by epic+task (`worktree_path()`)
  everywhere a worktree is created — grep every `create_worktree(` call
  site for the `epic_id` param being passed.

## PHASE 6 — Event Ordering & Idempotency

- Can `run_manager()`'s retry loop double-dispatch the same subtask to the
  same agent if a timeout/crash happens mid-retry? Check the retry-cap
  and state-check logic.
- Is event publishing ordered per-task (sequential publish guarantee)?
  Verify against `event_bus/bus.py`'s actual implementation, not the
  PROJECT.md claim.

## PHASE 6B — Orchestration Trace Simulation

Pick ONE realistic user request (e.g. "add a health check endpoint to the
API") and, using ONLY what you've read in code (not invented behavior),
narrate the exact real sequence of what happens in "full" pipeline mode,
step by step, citing the file:function responsible for each step:
task created → bootstrap check → pipeline pauses at human_review →
approval → manager dispatch → backend_dev → git commit → QA → (pass/fail
branch) → Reviewer → completion → memory embed → activity stream events
fired at each step. If any step in this trace doesn't match what you
verified in Phases 1-6, that's itself a finding — the trace either works
as claimed or it doesn't; state which, with evidence for any point where it
breaks.

## PHASE 6C — Failure Scenario Analysis (static reasoning from code, not live chaos testing)

For each scenario below, trace the ACTUAL code path (exception handling,
retry logic, fallback) that would fire, and state the real observable
outcome — a stuck task, a clean "blocked" status, a crash, or a silent
failure. Do not describe generic best-practice behavior; describe what
THIS codebase actually does, with file:line evidence.

- **Anthropic API unavailable / rate limited** — what happens to an
  in-flight `run_agent_graph()` call? Does it fall back (Groq/OpenAI) or
  fail the run? Does the task end up in a recoverable state?
- **Groq unavailable** (only relevant if `USE_GROQ=true` in that
  environment) — same question.
- **Postgres unavailable mid-run** — what happens to a task whose status
  update fails to persist? Could this leave DB and in-memory/checkpoint
  state inconsistent?
- **Redis unavailable** (if `REDIS_STREAMS_ENABLED`/RQ queue backend is in
  use in the target deployment) — does the system degrade to the asyncio
  in-memory queue, or hard-fail?
- **A tool call times out** (e.g. `bash` running a hanging test suite) —
  is there an actual enforced timeout, or could this hang a worker
  indefinitely? (Cross-reference audit 02's per-agent timeout-policy
  findings if already run.)
- **Retry exhaustion** — when `run_manager()`'s dev→qa→review loop
  exhausts its retry cap, confirm the EXACT resulting task/epic status and
  whether a human is actually notified (alert service) or the task just
  sits there.
- **Partial agent failure mid-epic** (one subtask fails permanently, others
  succeed) — does the epic reach a coherent terminal state, or can it be
  left in limbo with some subtasks done and others abandoned with no
  status reflecting that?
- **Worktree/git corruption** (e.g. a prior run left a dirty worktree) —
  does `create_worktree()`/`remove_worktree()` handle a pre-existing,
  unexpected worktree state gracefully, or would it error unhelpfully?
- **Checkpointer connection drop** (`AsyncPostgresSaver` in
  `pipeline/graph.py`) — if the DB connection used for checkpointing drops
  mid-pipeline, what's the actual failure mode on the next `interrupt()`/
  resume?

For each, classify the real outcome as: **Graceful** (clear blocked/failed
status, human-actionable), **Degraded-but-recoverable** (works but with a
gap, e.g. silent retry with no alert), or **Unsafe** (stuck state, silent
data loss, or crash with no recovery path). Any "Unsafe" classification is
at minimum a High finding.

## PHASE 7 — Final Report

1. Two-entry-point parity table (feature × path, ✅/❌/NOT FOUND) — this is
   the single most valuable output of this audit, treat it as the headline
2. State machine diagram + missing-transition findings
3. Human-in-the-loop correctness findings
4. Failure ladder reachability findings
5. Concurrency/conflict findings
6. Idempotency findings
7. Prioritized fix list (Critical → Low, file:line)
8. Orchestration Layer Production-Readiness score (0-100)

Do not write code. Do not modify files. Evidence or NOT FOUND only.
