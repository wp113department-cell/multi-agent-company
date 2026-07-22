# Day 14 Implementation Plan — Git Push Workflow
Researched and grounded 2026-07-22 (REPO-FIRST + codebase-first verification before design).

Source: `docs/FLEET_ENHANCEMENT_PLAN.md` lines 1029-1063.

## Repo research (read before designing)

- **`repos/open-hands/openhands/app_server/integrations/github/service/prs.py`** —
  `GitHubPRsMixin.create_pr()`: a plain REST call, `POST {BASE_URL}/repos/{repo}/pulls` with
  `{title, head, base, body, draft}`, returns `response['html_url']`. No magic — confirms the
  plan's own literal REST shape is correct and simple enough to implement directly.
- **`repos/aider/aider/repo.py`** — `GitRepo.commit()`: the real author/committer-attribution
  mechanism is `GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` env vars set via a context manager
  (`set_git_env`) around `self.repo.git.commit(cmd)`, not a `--author` CLI flag. Confirms the
  pattern this codebase's own `git_service.git_commit()` already uses (see below) is correct and
  matches the reference implementation's real mechanism.

## Codebase research — critical finding before any new code

**A pre-existing, unrelated-to-Day-14 bug**: nothing in the current pipeline ever commits an
agent's file changes to the worktree's branch. `create_worktree()` (`app/repo_tools/worktree.py`)
creates a real branch (`agent/task-{task_id}`, via `git worktree add -b`), but
`backend_dev.py`/`tools.py`'s `submit_patch` handler only records `files_changed`/`summary` in a
local dict — grepped for `git commit`/`.commit(` anywhere in the dev-agent path, found nothing.
This means `worktree.get_diff()` (`git diff HEAD...{branch}`, a three-dot ref comparison) has
**always returned an empty diff**, since the branch ref never advances — meaning the Reviewer
agent's own diff-review step has effectively been reviewing nothing since it was built. QA still
works (pytest reads files off disk regardless of git status), but review does not. **Day 14 must
add a commit step after the coding phase, not just a push step at the very end** — the plan's
literal "steps 1-4 create branch/stage/commit" undersold this: the branch already exists, but
staging+committing genuinely doesn't happen anywhere yet, and fixing it also fixes the review gap.

**Existing infrastructure to reuse, not rebuild**:
- `app/services/git_service.py` (Day 5A) already has a full async, secure git-ops layer:
  `git_add`, `git_commit` (real `GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` env-var attribution,
  matching aider's mechanism above), `git_push` (validates remote URL against the host allowlist
  before pushing), `git_checkout`. Host-allowlisted, workspace-scoped, no `shell=True`, tokens
  scrubbed from logged output. **Day 14 uses this directly — no new git-subprocess code.**
- `app/agents/tools.py` already has `git_push`/`create_pr`/`github_create_pr` — but these are
  interactive **chat-agent** tools (`session.request_confirmation`, or shelling out to the `gh`
  CLI). Neither matches the plan's automated-pipeline REST-API flow; Day 14's module is genuinely
  new, not a duplicate.
- **No credential vault exists** (Day 17 doesn't exist yet, as the plan itself flags) — but
  `SystemSetting` (key-value table) already stores the Anthropic/OpenAI API keys via
  `get_setting`/`set_setting`, exposed through `app/api/settings.py`'s
  `POST/DELETE /api/settings/api-key` pattern. **Reuse this exact pattern for a GitHub token**
  (`POST/DELETE /api/settings/github-token`) rather than inventing a vault.
- **Day 13's `pending_approvals`/`approval_gate.py` is the approval mechanism to register into**
  — not a new interrupt(). `run_manager()` is a plain async function, not a LangGraph graph with a
  checkpointer, so there's no `interrupt()` to hook after QA/review the way the plan's pipeline
  snippet implies (that snippet also assumes a `qa_node` inside `pipeline/graph.py`, which doesn't
  exist — QA/review happens in `manager.py`'s `run_manager()`, a separate flow, exactly the kind of
  plan/reality mismatch already found and worked around in Day 12). Mirrors Day 9's two-phase
  Scan→Approve→Apply pattern: `run_manager()` completing successfully records a pending approval
  (`action="git_push"`); `POST /api/approvals/{thread_id}/approve` (already built, Day 13) performs
  the actual push+PR via a new dispatch branch — no new approval infrastructure needed.

## Design

### 1. Commit step in `run_manager()` (closes the pre-existing review-gap bug)
After `run_backend_dev`/`run_frontend_dev` succeeds (`files_changed` non-empty, `dev_error` is
`None`) and before `run_qa`: `git_service.git_add(worktree_path, files_changed)` +
`git_service.git_commit(worktree_path, message, author_name="Gridiron Agent")`. Commit message:
simple deterministic `f"{subtask_type}: {subtask_title}"` for now (Haiku-generated message is used
at the final push step, matching the plan's step 3 — no need for two separate LLM-generated
messages per subtask).

### 2. `backend/app/tools/git_push_tool.py` (new)
- `generate_commit_message(task_title, diff, model) -> str` — one Haiku call, reuses the
  established `anthropic.Anthropic(api_key=get_effective_api_key())` pattern.
- `create_github_pr(repo_full_name, source_branch, target_branch, title, body, draft, token) -> dict`
  — real `POST https://api.github.com/repos/{repo}/pulls` via `httpx.AsyncClient` (already the
  established outbound-HTTP pattern, `app/services/alert.py`), Bearer token auth. Token never
  logged (matches `git_service.py`'s existing token-scrubbing convention).
- `push_and_create_pr(task_id, repo_path, github_url, token, title, body) -> PushResult` —
  orchestrates: `git_service.git_push` (reuse) → `create_github_pr` (new). Branch name reuses the
  **already-existing** `agent/task-{task_id}` convention from `worktree.py` — no new naming scheme.

### 3. DB: extend `DevTask` (migration 016)
New columns: `branch_name`, `pr_url`, `pr_status` (`none | pending | pushed | failed`). Simple
columns on the existing task row, consistent with `diff`/`files_touched` already living there —
no new table needed for a 1:1 relationship.

### 4. GitHub token storage
`app/api/settings.py` gains `POST/DELETE /api/settings/github-token`, exact mirror of the existing
`/api-key` endpoints, backed by `SystemSetting` (key=`"github_token"`). `get_settings_view()`
gains `githubTokenSet`/`githubTokenMasked`.

### 5. Wire into `run_manager()` completion
When `overall_status == "completed"`: record a pending approval via `approval_gate.arecord_pending()`
(reused from Day 13) — `thread_id=f"task-{task_id}-push"` (distinct from the plan-review
thread, `f"task-{task_id}"`, since these are two different decision points for the same task),
`action="git_push"`, `details={branch, files_changed, subtask_count}`.

### 6. `app/api/approvals.py` — extend `_dispatch_decision()`
New branch: `if row.action == "git_push"` → on approve, call `push_and_create_pr(...)`, store
`pr_url`/`pr_status="pushed"` on the `DevTask` row; on reject, set `pr_status="failed"` with no
push attempted. Token pulled via `get_setting(db, "github_token")` falling back to
`get_settings().github_token` env var (new config field, zero hardcoding).

### 7. New endpoints (`app/api/tasks.py`)
- `GET /api/tasks/{id}/pr` → `{branchName, prUrl, prStatus}`.
- `POST /api/tasks/{id}/push` → manual retry: re-runs `push_and_create_pr` directly (for a
  previously-approved push that failed transiently), bypassing the approval gate since approval
  already happened once.

### 8. Frontend
Day 13's `/approvals` page already generically lists any `pending_approvals` row — the new
`action="git_push"` entries show up there with zero frontend changes needed. Task detail page
(`apps/web/app/tasks/[id]/page.tsx`) gets a small PR-link section once `prUrl` is set.

## Build order
1. Migration 016 + `DevTask` model fields.
2. Commit-step fix in `run_manager()` (the real bug fix — do this first, verify independently).
3. `github_token` config + settings API endpoints.
4. `git_push_tool.py` + tests (mocked GitHub API).
5. Wire pending-approval recording into `run_manager()` completion.
6. Extend `approvals.py`'s dispatch + new task endpoints.
7. Minor frontend PR-link display.
8. Full suite + mypy, update `PROJECT.md`/Control Center, write
   `docs/reports/FLEET_DAY14_TEST_REPORT.md`, commit.
