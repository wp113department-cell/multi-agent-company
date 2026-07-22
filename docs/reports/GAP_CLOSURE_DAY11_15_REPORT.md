# Gap-Closure Report — Days 11–15 Audit
Date: 2026-07-22

## Why this audit happened

Per explicit user request, before starting Day 16: "check first plan 11 to 15 is there anything is
missing if yes so fill it first then implement plan 16." Days 11-13 already had a formal
gap-closure audit (2026-07-21, `GAP_CLOSURE_DAY11_13_REPORT.md`); this audit re-checked those three
plus Days 14-15, and specifically looked for wiring gaps in code paths NOT exercised by either
day's own end-of-day real-caller grep (which only checks "is this new function called by
something," not "is it called by EVERY real path that should reach it").

## Method

- Fresh full suite + mypy baseline (2651 passed, 0 mypy errors — the Day 15 close-of-day state).
- Re-verified Days 11-14's previously-closed findings are still closed (`versioned_memory.publish`,
  `archive_expired`, `benchmark_manager.store_baseline`, `tool_discovery`, `failure_ladder`,
  `hierarchy_chain` wiring in `manager.py` — all confirmed still wired, no regressions).
- Checked `prompt_registry.deploy()`/`approve()`/`submit_for_review()` for real callers: none exist
  anywhere, not even an API endpoint. Cross-checked against the MASTER plan's own Day 11 section
  (`docs/FLEET_ENHANCEMENT_PLAN.md` line 869) — titled "Infrastructure," success criteria is
  explicitly "Tests for all three... Tests pass," no API/wiring commitment. **Correctly out of
  scope, not a gap** — same standalone-infrastructure category the prior audit's own methodology
  distinguishes (matches how `approval_gate.py` was pure infra before Day 13 built its API).
- Specifically traced **every real entry point that can reach `create_worktree()`** (the function
  Day 15's own research identified as the hard constraint bootstrap exists to satisfy), since Day
  15 only wired bootstrap into ONE of the codebase's several task-lifecycle entry points.

## Findings

### 1. `launch_coder()` ("simple" pipeline mode) never checked for a blank repo — real, will crash

Day 15 wired `bootstrap()` into `launch_planning_pipeline()` ("full" mode only). The codebase has
a second, older, still-selectable pipeline mode (`PIPELINE_MODE=simple` or `POST
/api/tasks/{id}/run` with `{"mode": "simple"}`) whose coding step is `launch_coder()` — it calls
`create_worktree()` directly with zero blank-repo awareness. Verified: `create_worktree()` raises
`RuntimeError("git error: fatal: invalid reference: HEAD")` against a real zero-commit repo. Fixed
by adding the identical `is_blank_repo()`/`bootstrap()` check to `launch_coder()` that
`launch_planning_pipeline()` already has.

### 2. `launch_coder()`'s exception handler never transitioned the task to "blocked" — real, pre-existing, newly reachable

Found while fixing #1: `launch_coder()`'s outer `except Exception` handler (unlike
`launch_manager()`'s equivalent) never called `transition_task(..., "blocked")`. A task hitting
this path (which Day 15's blank-repo scenario makes newly common, not just a rare permission-error
edge case) was left stuck in `"coding"` status with no valid transition forward via the normal API.
Fixed by adding the missing `transition_task` call, matching `launch_manager()`'s pattern exactly.
`"coding"` → `"blocked"` is already a valid transition in `VALID_TRANSITIONS`.

### 3. `finish_agent_run()` / `heartbeat_agent_run()` — real, pre-existing datetime bug, exposed by writing the first-ever real test for `launch_coder()`

`launch_coder()`/`launch_planner()`'s `create_agent_run()`/`finish_agent_run()` pair had **zero
prior test coverage anywhere in the codebase** (confirmed by grep before writing tests for finding
#1). Writing a real test against the real DB immediately hit: `asyncpg.exceptions.DataError:
invalid input for query argument $6: ... can't subtract offset-naive and offset-aware datetimes`.
Root cause: both functions wrote `datetime.now(timezone.utc)` (timezone-AWARE) into `AgentRun`
columns declared as plain `Mapped[datetime]` (naive, `TIMESTAMP WITHOUT TIME ZONE`) — asyncpg
enforces this strictly. This has silently broken every real run of `launch_coder()`/`launch_planner()`
since whenever these functions were written (`launch_coder()`'s broad exception handler swallowed
it, logging a generic "Coder failed" with no hint the real cause was its own bookkeeping call, not
the coding agent). Fixed both call sites with `.replace(tzinfo=None)`, matching the established
convention already used elsewhere in the same file (`app/api/repo.py`'s `cloned_at` field).

### 4. `create_worktree()` called with no `repo_path` in BOTH `launch_coder()` and `launch_manager()` — real, pre-existing, breaks multi-repo tasks

Found while fixing #1 (test A's mock revealed a real Anthropic 401 call had been reached against
the *wrong* repo). Both `launch_coder()` (line ~549) and `launch_manager()` (line ~369) called
`create_worktree(task_id)` with no `repo_path` argument, silently defaulting to
`settings.target_repo_path` (the single global default repo) — **completely ignoring the task's
actual assigned repo** (`task.repo_id` → `Repo.local_path`), even though both functions correctly
resolve and use `effective_repo` for `run_coder()`/`run_manager()` immediately afterward. This
means: for any task on a repo other than the global default, the coding agent's worktree/branch has
always been created against the wrong repository entirely, while the agent's tool calls, diff
computation, and checks ran against the *right* one — a real, load-bearing correctness bug for this
project's own multi-repo Repo Console feature (Day 5A/P3), not something Days 11-15 introduced but
directly relevant since it's exactly the class of bug that makes Day 15's own bootstrap fix
ineffective (bootstrap correctly targets the task's real repo; a `create_worktree()` that ignores
it would silently create the worktree somewhere else). Fixed both call sites to pass
`effective_repo`; also fixed `launch_coder()`'s `get_diff(task_id)` call for the same reason (was
missing `repo_path` too, unlike `launch_manager()`'s equivalent call, which already had it right).

### 5. `POST /api/tasks/{id}/approve` never resolved the task's assigned repo — real, root cause of finding #4's user-visible symptom for simple mode

The actual root cause behind #4 being reachable for simple-mode tasks at all: `approve_task()`
(`/{task_id}/approve`, simple mode's plan-approval endpoint) never resolved `task.repo_id` →
`Repo.local_path` before calling `launch_coder(task_id, plan)` — unlike `run_task()`,
`restart_task()`, and `pipeline_approve()`, which all correctly do this resolution. `launch_coder()`
therefore always fell back to the single global active repo regardless of which repo the task was
actually assigned to. Fixed by adding the identical repo-resolution block already used by the other
three endpoints.

### 6. Frontend: `git_push` approvals showed an unlabeled raw action string — cosmetic, minor

`apps/web/app/approvals/page.tsx`'s `ACTION_LABELS` map only had `plan_review: "Plan Review"`.
`DetailsPreview` itself is fully generic (renders any `details` object), so Day 14's `git_push`
approvals were functionally fine, just displayed as the raw string `"git_push"` instead of a
friendly label. Added `git_push: "Git Push"`.

## Confirmed NOT gaps (checked, correctly out of scope)

- `prompt_registry.deploy()`/`approve()`/`submit_for_review()` having no caller — Day 11's own plan
  scoped this as standalone infrastructure with no wiring commitment (see Method above).
- Day 13's approval system not covering "simple" mode — an explicit, already-documented scope
  decision in Day 13's own report ("the one real, already-working call site").
- `failure_ladder`/hierarchy-chain wiring in `manager.py` — still intact, no regression.

## Testing

New: `tests/test_launch_coder_bootstrap.py` (2 tests, driven through a real `TestClient` per the
documented asyncio shared-engine hazard) — verifies bootstrap is called with the correct
task/repo args on a blank repo and the task correctly lands in `"blocked"` (not stuck) when the
downstream worktree step still fails; verifies bootstrap is skipped and the task reaches
`ready_for_review` normally on a non-blank repo, exercising the full `/approve` → `launch_coder` →
`create_worktree` → `run_coder` → `finish_agent_run` chain for the first time ever against a real
DB.

## Test Results

```
pytest tests/ -q
→ 2653 passed, 0 failed, 55 skipped, 17 deselected, 16 warnings in 85.49s

mypy app/ --strict
→ 0 errors

Frontend: tsc --noEmit (clean)
```

## Verdict
✅ GREEN FLAG — GAP-CLOSURE (DAYS 11-15) COMPLETE. Ready for Day 16 (Image Input Pipeline).
