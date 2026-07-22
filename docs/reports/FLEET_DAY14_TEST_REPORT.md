# Fleet Day 14 Test Report — Git Push Workflow
Date: 2026-07-22

## What was built

Per `docs/DAY14_PLAN.md`, grounded in REPO-FIRST research before any design (CLAUDE.md rule),
per the user's explicit instruction: "check repos and get idea then implement all things one by
one."

### Research

- `repos/open-hands/openhands/app_server/integrations/github/service/prs.py`
  (`GitHubPRsMixin.create_pr()`) — real GitHub REST API PR-creation call shape (`POST
  /repos/{owner}/{repo}/pulls`, `head`/`base`/`title`/`body`/`draft` fields).
- `repos/aider/aider/repo.py` (`GitRepo.commit()`) — real commit-attribution mechanism
  (`GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` env vars), reused in the fix below.
- Confirmed the codebase already has everything needed for the git-ops layer
  (`app/services/git_service.py`, Day 5A: `git_add`/`git_commit`/`git_push`, host-allowlisted,
  workspace-scoped, no `shell=True`, tokens scrubbed from logs) and the approval mechanism
  (`app/fleet/approval_gate.py`, Day 13) — Day 14 reuses both rather than building parallel
  systems, exactly as anticipated in the Day 13 report's own closing note.

### A real, pre-existing bug found during research, not assumed away

Nothing in the dev-agent path (`submit_patch` handler in `run_manager()`) ever committed file
changes to the worktree's branch. This means `worktree.get_diff()` (`git diff HEAD...branch`) has
returned empty since Day 0 — **the Reviewer agent's own diff review has been reviewing nothing**,
every single run. Verified empirically against a real temp git repo (branch HEAD unchanged after
a `submit_patch` call) before writing any code. Fixed by adding a `git_add` + `git_commit` step
in `run_manager()`'s per-subtask retry loop, right after `run_backend_dev`/`run_frontend_dev`
succeeds and before `run_qa` — using real `git_service.git_add`/`git_commit` (Day 5A), non-fatal
on failure (logged, retry loop continues; a failed commit doesn't block QA, matching this
codebase's existing "log and continue" convention for non-critical side effects). This was a
necessary prerequisite for the push/PR workflow to mean anything: with no commits, there is
nothing to push.

## What was built (the Day 14 feature itself)

- **Migration 016** + `DevTask.branch_name`/`pr_url`/`pr_status` (`none|pending|pushed|failed`).
- **`app/tools/git_push_tool.py`** (new package `app/tools/`): `parse_repo_full_name()` (regex,
  handles `https://`/`git@`/`.git`-suffixed GitHub URLs), `generate_commit_message()` (one Haiku
  call for the PR title, deterministic fallback on any failure — never raises),
  `create_github_pr()` (real `httpx.AsyncClient` POST to the GitHub REST API, reusing the
  established outbound-HTTP pattern from `app/services/alert.py`), `push_and_create_pr()`
  (orchestrates the existing `git_service.git_push` + the new `create_github_pr`).
- **GitHub token storage**: `SystemSetting` key-value table reused (already backs the
  Anthropic/OpenAI keys — no credential vault exists yet, that's Day 17). New
  `POST`/`DELETE /api/settings/github-token`, mirroring the existing `/api-key` endpoints exactly.
- **Approval wiring**: on task completion, `launch_manager()` (`api/agents.py`) registers a
  `git_push` pending approval into Day 13's generic `pending_approvals` system — the SAME
  table/API Day 13's own closing note anticipated, not a parallel mechanism. Extracted into a
  standalone `_record_git_push_approval()` function (not inlined) so it's directly testable
  against an isolated DB session without driving the full pipeline machinery.
- **`app/api/approvals.py`**: `_dispatch_decision()` gained a `git_push` branch calling the new
  `dispatch_git_push_decision()` — reject marks `pr_status="failed"` (no push attempted); approve
  pushes the already-committed `agent/task-{id}` branch and creates the PR.
- **`GET /api/tasks/{id}/pr`** (branch/PR/status) and **`POST /api/tasks/{id}/push`** (manual
  retry — bypasses the approval gate since approval already happened once) added to
  `app/api/tasks.py`.
- **Frontend**: `apps/web/lib/api.ts` gained `TaskPr` + `fetchTaskPr`/`retryTaskPush`. Task detail
  page (`apps/web/app/tasks/[id]/page.tsx`) gained a "Git branch & pull request" section — branch
  name, a colored status badge (`pushed`/`failed`/`pending`/`none`), a link to the PR when set,
  and a "Retry push" button shown only when `prStatus === "failed"`.

## Plan/reality mismatch corrected (mirrors the same class of finding in Day 12/13)

The plan's literal pipeline-integration snippet assumed a `qa_node` inside `pipeline/graph.py`
(the real LangGraph `StateGraph`). Confirmed via direct reads that QA/review actually happens in
`manager.py`'s `run_manager()`/`launch_manager()` — plain `async def` orchestration functions with
no LangGraph involvement. Wired the push-approval recording into `launch_manager()` instead (the
correct completion point with DB access), not the literal plan text.

## The asyncio shared-engine hazard — a new variant, now with a clearer taxonomy

Two more occurrences this session, both from the SAME new cause: `_record_git_push_approval()`
and `dispatch_git_push_decision()` are production code that, by design, run inside FastAPI's
`BackgroundTasks` on the app's own already-running event loop, so they correctly use the shared
`get_session_factory()` singleton. Calling them via a bare `asyncio.run()` from sync test code
fails ("attached to a different loop") because that creates a second, separate event loop.

This is distinct from the two previously-known variants (isolated-engine-per-call is safe to
re-run; calling already-async code from a sync `asyncio.run()` wrapper fails outright) — fixed
here two different ways: (1) `_record_git_push_approval()` is tested directly against a fresh
isolated engine, since its logic doesn't depend on the shared engine's runtime lifecycle; (2)
`dispatch_git_push_decision()` genuinely needs the shared engine's request-scoped lifecycle, so
`test_git_push_approval_dispatch.py` drives it entirely through a real `TestClient` instead
(`TestClient`'s `BackgroundTasks` execute synchronously within the request/response cycle, on one
continuous event loop the whole test block shares).

## A real mypy bug found and fixed (new code, not pre-existing)

`generate_commit_message()`'s original list comprehension (`[b.text for b in r.content if
getattr(b, "type", "") == "text"]`) defeated mypy's discriminated-union narrowing — `getattr()`
with a string comparison doesn't type-narrow the Anthropic SDK's `ContentBlock` union the way a
direct `b.type == "text"` attribute check does. Fixed by rewriting as an explicit `for`/`if` loop
matching the established pattern already used in `app/agents/base.py`. 11 new mypy errors → 0.

## Frontend verification

- `npx tsc --noEmit` — clean.
- `npx eslint app/tasks/[id]/page.tsx lib/api.ts` — clean.
- `npm run build` — succeeds; only 2 pre-existing warnings in unrelated files (`epics/page.tsx`,
  `review/page.tsx`), unchanged from Day 13's baseline.

## Test Results

```
pytest tests/ -q
→ 2633 passed, 0 failed, 55 skipped, 17 deselected, 15 warnings in 81.64s

mypy app/ --strict
→ 0 errors (11 new errors found and fixed during this day; 0 remaining)
```

37 new backend tests: 2 (`test_manager_git_commit.py`) + 4 (GitHub token settings) + 17
(`test_git_push_tool.py`) + 4 (`test_launch_manager_push_approval.py`) + 10
(`test_git_push_approval_dispatch.py`), plus 5 existing tests updated (`git_add`/`git_commit`
mocks added to pre-existing `with patch(...)` blocks in `test_failure_ladder.py`,
`test_day12_smoke_test.py`, `test_hierarchy_chain.py`) to account for the new commit step in
`run_manager()`.

## Verdict
✅ GREEN FLAG — DAY 14 COMPLETE. Ready for Day 15.
