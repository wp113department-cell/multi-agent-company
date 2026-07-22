# Fleet Day 15 Test Report — Blank Repo Bootstrap
Date: 2026-07-22

## What was built

Per `docs/DAY15_PLAN.md`, grounded in REPO-FIRST research before any design (CLAUDE.md rule).

### Research

- `repos/open-hands/openhands/app_server/app_conversation/app_conversation_service_base.py`'s
  `run_setup_scripts()`/`clone_or_init_git_repo()` — a fixed sequence of setup phases with
  observable status, run before the agent's normal tools have anything to work with. The reusable
  core: detect "nothing real exists yet" first, run a small fixed phase sequence, then hand off to
  the normal flow. Everything else in that file (remote sandboxes, Azure DevOps bearer tokens,
  skill-loading) is infrastructure this project doesn't have and doesn't need.

### A real, load-bearing constraint found empirically, not assumed

`repo_tools/worktree.py`'s `create_worktree()` runs `git worktree add -b branch path`, which
requires an existing commit to branch from. Verified against a real empty `git init`-only repo:
this fails with `fatal: invalid reference: HEAD` against a zero-commit repo. **This means bootstrap
must commit directly to the bare repo before any task's worktree can ever be created for it** — not
a stylistic choice, a hard ordering requirement that shaped where bootstrap writes its files
(directly into `repo_path`, never a worktree, since none can exist yet).

## What was built

- **`git_service.git_init(repo_path)`** — new function, same pattern as every other function in
  that file (`_validate_workspace`, no `shell=True`, the shared `_run_git` helper).
- **`app/pipeline/bootstrap.py`** (new module):
  - `is_blank_repo(repo_path)` — sync, cheap: `git log --oneline -1` non-zero return or empty
    stdout. Covers both "no `.git` at all" and "`.git` exists but zero commits" (the real shape
    after cloning a genuinely empty GitHub repo — `git clone` of an empty repo succeeds and creates
    `.git` with no commits) with a single check.
  - `detect_project_type(task_description, model)` — one Haiku call classifying into
    `web-app | api | cli | library | data-pipeline`, deterministic `"web-app"` fallback on any
    failure — mirrors Day 14's `generate_commit_message()` exactly.
  - `run_scaffold_planning(repo_path, project_type, task_description)` — reuses the architect
    agent's identity (`role_name="architect"`, `roles/architect.md`, `settings.model_planner`) with
    a scaffold-specific instruction and a local `submit_scaffold_plan` tool, instead of importing
    architect.py's private module attributes.
  - `bootstrap(task_id, repo_path, task_description, project_type=None, db=None)` — async
    orchestrator: no-op if not blank → detect project type if not given → `git init` if no `.git`
    → scaffold planning (architect, via `asyncio.to_thread`) → scaffold write (reuses
    `app/agents/coder.py`'s existing `run_coder()` UNCHANGED, passing `repo_path` as both
    `worktree_path` and `repo_path` since no separate worktree exists yet — confirmed mypy/ruff
    finding zero files in a non-Python scaffold exits 0 trivially, harmless for any project type)
    → `git_add` + `git_commit("chore: initial scaffold by gridiron")` → `git_log` for the resulting
    commit sha. Every phase logged via `append_log` (the task detail page's existing log stream —
    zero new frontend work). Any phase failure returns `BootstrapResult(bootstrapped=False,
    error=...)` rather than raising.
- **Wiring**: `launch_planning_pipeline()` (`api/agents.py`) calls `bootstrap()` before
  `run_planning_pipeline()` when `is_blank_repo(effective_repo_path)` is true.

## Plan/reality corrections (same class of finding as Days 12-14)

1. **"Emit `RepoBootstrapped` event"** — Day 12 hardened `fleet_events.py` to exactly 8 canonical
   `FleetEventType`s and added a static AST scan (`test_event_compliance.py`) that fails the build
   if any other event type is ever emitted. Inventing a 9th type would break that real, enforced
   invariant. Used the closest fitting real events instead (`task_started`/`task_completed` around
   the bootstrap phase, `agent_name="bootstrap"`) plus `append_log` for the phase-by-phase status
   text.
2. **"Ask the user (via `interrupt()`) OR detect from task description"** — the plan phrases this
   as an explicit choice between two alternatives. A third `interrupt()`-based approval type
   (alongside Day 13's `plan_review` and Day 14's `git_push`) for a one-shot, low-risk "what kind
   of project is this" classification is disproportionate scope next to an already-fallback-safe
   Haiku call. Took the detection branch of the explicit "or" — documented here rather than
   silently dropped.

## Testing

- `TestIsBlankRepo` (4 tests) — real temp dirs: no `.git` at all, `git init` with zero commits
  (both `True`), a repo with a real commit (`False`), a nonexistent path (`True`).
- `TestDetectProjectType` (3 tests) — mocked `anthropic.Anthropic`: valid type parsed, exception
  falls back to `"web-app"`, unrecognized response text falls back to `"web-app"`.
- `TestBootstrap` (7 tests) — real temp git repos, real `git_init`/`git_add`/`git_commit`, with
  `run_scaffold_planning`/`run_coder`/`detect_project_type` mocked at their `bootstrap.py` import
  site (each is independently a full LLM-agent-graph run, already covered by architect.py's/
  coder.py's own test suites — this file is about bootstrap's phase orchestration and git
  mechanics, not re-testing agent internals): no-op on a non-blank repo, full success produces a
  REAL commit with the exact expected message (verified via `git log`), scaffold-planning failure
  is non-fatal (and leaves the repo still blank — verified), coder error is non-fatal, coder
  producing zero files is non-fatal, an explicit `project_type` skips detection entirely, `db=None`
  never crashes logging.
- `test_git_init_creates_real_repo` / `test_git_init_outside_workspace_denied` (2 tests) — added to
  `test_git_service.py`, matching that file's existing convention exactly.
- **Wiring** (`test_bootstrap_wiring.py`, 2 tests) — driven through a real `TestClient`
  (`POST /api/tasks/{id}/run`), per the documented Day 14 asyncio shared-engine hazard
  (`launch_planning_pipeline()` uses the shared `get_session_factory()` singleton by design):
  `bootstrap()` is called with the correct `task_id`/`repo_path` when the task's repo is a real
  blank temp dir, and is never called when the repo already has a real commit.

## Real-caller verification (per the project's own recurring "built but never called" pattern)

```
bootstrap()      → called from app/api/agents.py:launch_planning_pipeline()
is_blank_repo()  → called from app/api/agents.py:launch_planning_pipeline()
                   AND from bootstrap() itself (self-check no-op guard)
git_init()       → called from app/pipeline/bootstrap.py:bootstrap()
```
No orphaned modules this day either (2/2 clean days in a row — Day 14 was the first).

## Test Results

```
pytest tests/ -q
→ 2651 passed, 0 failed, 55 skipped, 17 deselected, 16 warnings in 85.75s (18 new tests)

mypy app/ --strict
→ 0 errors

Frontend: tsc --noEmit (clean — no frontend changes this day, Day 15's own plan has no
frontend section)
```

## Verdict
✅ GREEN FLAG — DAY 15 COMPLETE. Ready for Day 16 (Image Input Pipeline).
