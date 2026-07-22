# Day 15 Plan — Blank Repo Bootstrap

Per `docs/FLEET_ENHANCEMENT_PLAN.md` lines 1067-1096. Goal: given an empty repo, agents scaffold
the entire project structure before the normal PM→Architect→Decomposer pipeline runs.

## Research (REPO-FIRST)

`repos/open-hands/openhands/app_server/app_conversation/app_conversation_service_base.py`:
- `run_setup_scripts()` (line 252): a 4-phase status-transition sequence
  (`PREPARING_REPOSITORY` → `RUNNING_SETUP_SCRIPT` → `SETTING_UP_GIT_HOOKS` →
  `SETTING_UP_SKILLS`), each phase `yield`ed as a status update before running.
- `clone_or_init_git_repo()` (line 396): if no repository is selected, `git init` the empty
  workspace directory rather than cloning.

The core pattern worth taking: **detect "nothing real exists yet" before the agent's normal tools
have anything to work with, run a small fixed sequence of setup phases with observable status at
each step, then hand off to the normal flow.** Everything else in that file (remote sandboxes,
Azure DevOps bearer tokens, skill-loading) is infrastructure this project doesn't have and doesn't
need — this project runs agents against local worktrees, not remote sandboxes.

## Codebase grounding

- `app/pipeline/graph.py`'s `run_planning_pipeline()` is the actual pipeline entry point, called
  from `launch_planning_pipeline()` in `api/agents.py` — the plan's own architect/coder agents are
  LangGraph nodes bound to `PipelineState`, not general-purpose functions; there's no clean place
  inside the `StateGraph` itself to inject an async pre-flight phase that also needs DB access for
  logging. Mirrors the same class of finding in Days 12-14: wire this into `launch_planning_pipeline()`
  before the `run_planning_pipeline()` call, not into `pipeline/graph.py`.
- **A real, load-bearing constraint found empirically, not assumed**: `create_worktree()`
  (`repo_tools/worktree.py`) runs `git worktree add -b branch path`, which requires an existing
  commit to branch from. Verified against a real empty `git init`-only repo: `git worktree add -b x
  path` fails with `fatal: invalid reference: HEAD` when there is no commit yet. **This means
  bootstrap MUST commit directly to the bare repo before any task's worktree can ever be created
  for it** — not a stylistic choice, a hard ordering requirement.
- `app/agents/coder.py`'s `run_coder(task_id, plan, worktree_path, repo_path)` is already exactly
  "run an agent that writes files into `worktree_path` and self-corrects via mypy/ruff" — reused
  directly for the scaffold-write phase by passing `repo_path` as both `worktree_path` and
  `repo_path` (no separate worktree exists yet to pass). `mypy`/`ruff` finding zero `.py` files in
  a non-Python scaffold (e.g. a `web-app` project) exit 0 trivially — confirmed this is harmless
  for any `project_type`, not just Python ones.
- `app/agents/architect.py`'s `architect_node` is tightly coupled to `PipelineState` (reads
  `state["pm_brief"]`, `state["task_title"]`) — not reusable as a bare function. Reused the same
  underlying mechanism instead (`run_agent_graph(role_name="architect", ...)` with the read-only
  tools + a submit tool, same role prompt `roles/architect.md`, same model tier
  `settings.model_planner`) with a bootstrap-specific instruction, defined locally in
  `bootstrap.py` rather than importing architect.py's private `_SUBMIT_TOOL`/`_VERIFICATION_CFG`
  module attributes.
- `app/services/git_service.py` (Day 5A/14) has no `git_init` — added one, following the exact
  same pattern as every other function in that file (`_validate_workspace`, no `shell=True`,
  `_run_git` helper).

## Plan/reality corrections (same class of finding as Days 12-14)

1. **"Emit `RepoBootstrapped` event"** — Day 12 hardened `fleet_events.py` to exactly 8 canonical
   `FleetEventType`s (`TaskCreated`/`TaskStarted`/`TaskCompleted`/`TaskFailed`/`ReviewRequested`/
   `LessonPublished`/`HealthUpdated`/`MemoryCreated`) and added a static AST scan
   (`test_event_compliance.py`) that fails the build if any other event type is ever emitted.
   Inventing a 9th type would break that real, enforced invariant. Used the closest fitting real
   events instead — `task_started`/`task_completed` around the bootstrap phase — plus
   `append_log(db, task_id, "bootstrap", ...)` for the phase-by-phase status text (the exact
   mechanism `launch_planning_pipeline()` already uses for "Planning pipeline started"), which is
   already rendered on the task detail page's log stream with zero new frontend work.
2. **"Ask the user (via `interrupt()`) OR detect from task description"** — the plan phrases this
   as an explicit choice between two alternatives. Implementing a third `interrupt()`-based
   approval type (alongside Day 13's `plan_review` and Day 14's `git_push`) for a one-shot,
   low-risk "what kind of project is this" classification is disproportionate scope for what a
   cheap, already-fallback-safe Haiku call handles just as well (same shape as Day 14's
   `generate_commit_message()` — one Haiku call, deterministic fallback on any failure, never
   raises). Took the detection branch of the explicit "or".

## Design

**New: `backend/app/services/git_service.py`** — `git_init(repo_path)`, mirroring `git_clone`'s
shape (`_validate_workspace`, `_run_git(["init"], cwd=repo_path)`).

**New: `backend/app/pipeline/bootstrap.py`**
- `is_blank_repo(repo_path: str) -> bool` — sync, cheap: `git log --oneline -1` non-zero return
  code or empty stdout (covers both "no `.git` at all" and "`.git` exists but zero commits", e.g.
  after cloning a genuinely empty GitHub repo — verified `git clone` of an empty repo succeeds and
  creates `.git` with no commits, so this one check correctly covers both real-world paths into a
  blank repo).
- `async def detect_project_type(task_description: str, model: str) -> str` — one Haiku call
  choosing from `web-app | api | cli | library | data-pipeline`, deterministic fallback
  (`"web-app"`) on any failure — mirrors `git_push_tool.generate_commit_message()` exactly.
- `def run_scaffold_planning(repo_path, project_type, task_description) -> dict[str, Any]` —
  sync (matches `architect_node`/`run_coder`'s sync `run_agent_graph()` shape), `role_name="architect"`,
  read-only tools + a local scaffold-submit tool, bootstrap-specific instruction.
- `bootstrap(task_id, repo_path, task_description, project_type=None) -> BootstrapResult` — async
  orchestrator: no-op if not blank → detect project type if not given → `git init` if no `.git` →
  `run_scaffold_planning` (via `asyncio.to_thread`) → `run_coder` (via `asyncio.to_thread`,
  `worktree_path=repo_path`) → `git_add` + `git_commit("chore: initial scaffold by gridiron")` →
  `git_log` for the resulting commit sha. Every phase logged via `append_log`; non-fatal errors at
  any phase return `BootstrapResult(bootstrapped=False, error=...)` rather than raising, so a
  bootstrap failure degrades to "pipeline runs against whatever state the repo ended up in" instead
  of blocking task creation outright.

**Wiring**: `launch_planning_pipeline()` calls `bootstrap()` first when `is_blank_repo(repo_path)`
is true, before `run_planning_pipeline()`.

## Success criteria (from the plan, verified against a real temp dir, not mocked)

Given a blank dir: `is_blank_repo()` returns `True`; `bootstrap()` runs `git init`, produces a real
scaffold plan and files via the same agent machinery as the rest of the pipeline, commits them, and
returns a real commit sha — then the normal task pipeline proceeds against the now-non-blank repo.
