"""Apply a finished task to the user's own folder (W2, 2026-10-09).

A project that lives only on this computer (no GitHub link) has nowhere to
push: its finished work sits on the task's own branch, `agent/task-{id}`,
committed in a separate worktree. After the human approves delivery, this
module merges that branch into the branch the user's folder is on, so the
changes appear in the folder itself.

It never overwrites the user's own work:
- uncommitted changes to tracked files: refused, nothing touched;
- a conflict with the user's newer commits: the merge is undone
  (`git merge --abort`) and the conflicting files are listed;
- a folder that is not on a branch (detached HEAD): refused.

Git runs with the repository's hooks and fsmonitor disabled: the merge runs
in the backend's own process, and code from the repository must never run
there (code only runs in the sandbox).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.git_service import run_git_process

BOT_NAME = "Multi Agentic Company"
BOT_EMAIL = "bot@multi-agentic.local"
_SAFE = [
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    f"user.name={BOT_NAME}",
    "-c",
    f"user.email={BOT_EMAIL}",
]


@dataclass
class ApplyResult:
    applied: bool
    message: str
    commit: str | None = None


async def _git(folder: str, *args: str, timeout: float = 120) -> tuple[int, str]:
    rc, out, err, timed_out = await run_git_process(
        ["git", "-C", folder, *_SAFE, *args], folder, None, timeout
    )
    if timed_out:
        return -1, "git timed out"
    return rc, (out + err).decode(errors="replace").strip()


async def apply_task_branch(task_id: int, folder: str, title: str) -> ApplyResult:
    branch = f"agent/task-{task_id}"
    rc, _ = await _git(
        folder, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"
    )
    if rc != 0:
        return ApplyResult(
            False, f"There is no finished work to apply ({branch} not found)."
        )
    rc, current = await _git(folder, "symbolic-ref", "--short", "-q", "HEAD")
    if rc != 0 or not current:
        return ApplyResult(
            False,
            "Your folder is not on a branch (detached HEAD). Switch it to a "
            "branch, then click Try again.",
        )
    rc, out = await _git(folder, "merge-base", "--is-ancestor", branch, "HEAD")
    if rc == 0:
        _, head = await _git(folder, "rev-parse", "HEAD")
        return ApplyResult(True, f"Already in your folder (branch {current}).", head)
    rc, dirty = await _git(folder, "status", "--porcelain", "--untracked-files=no")
    if rc != 0:
        return ApplyResult(False, f"Could not read your folder's state: {dirty[:300]}")
    if dirty:
        _, names = await _git(folder, "diff", "--name-only", "HEAD")
        files = names.splitlines()[:10] or ["(some files)"]
        return ApplyResult(
            False,
            "Your folder has changes that are not saved in git yet: "
            + ", ".join(files)
            + ". Commit or stash them, then click Try again. Nothing was changed.",
        )
    rc, out = await _git(
        folder,
        "merge",
        "--no-ff",
        "--no-edit",
        "-m",
        f"Apply task #{task_id}: {title}"[:200],
        branch,
    )
    if rc != 0:
        _, conflicted = await _git(folder, "diff", "--name-only", "--diff-filter=U")
        await _git(folder, "merge", "--abort")
        if conflicted:
            return ApplyResult(
                False,
                "The finished work conflicts with newer changes in your folder: "
                + ", ".join(conflicted.splitlines()[:10])
                + ". Your folder was left exactly as it was.",
            )
        return ApplyResult(
            False,
            f"Could not apply the work to your folder: {out[:300]}. "
            "Your folder was left exactly as it was.",
        )
    _, head = await _git(folder, "rev-parse", "HEAD")
    return ApplyResult(True, f"Applied to your folder (branch {current}).", head)


# -- W4: the user's unsaved edits (2026-10-09) --------------------------------
# A task works in its own worktree, which starts from the folder's last
# commit: edits the user has not committed are invisible to the agents. Before
# a task starts, the user is told and can save them first.

# never committed by "save my changes": secrets stay out of git
_SECRET_EXCLUDES = [
    ":(exclude,glob)**/.env",
    ":(exclude,glob)**/.env.*",
    ":(exclude,glob)**/*.pem",
    ":(exclude,glob)**/*.key",
]


async def unsaved_changes(folder: str) -> list[str]:
    """Files changed or added in the folder but not committed (ignored files
    excluded). Empty when the folder isn't a git repository."""
    rc, tracked = await _git(folder, "diff", "--name-only", "HEAD")
    if rc != 0:
        return []
    _, untracked = await _git(folder, "ls-files", "--others", "--exclude-standard")
    names = [n for n in (tracked + "\n" + untracked).splitlines() if n.strip()]
    return list(dict.fromkeys(names))


async def save_changes(folder: str, task_id: int) -> ApplyResult:
    """Commit the user's unsaved edits (never .env/keys) so the task sees
    them. Only on the user's explicit request."""
    rc, out = await _git(folder, "add", "-A", "--", ".", *_SECRET_EXCLUDES)
    if rc != 0:
        return ApplyResult(False, f"Could not save your changes: {out[:300]}")
    rc, staged = await _git(folder, "diff", "--cached", "--name-only")
    if rc == 0 and not staged:
        return ApplyResult(True, "Nothing to save.")
    rc, out = await _git(
        folder, "commit", "-m", f"Save my changes before task #{task_id}"
    )
    if rc != 0:
        return ApplyResult(False, f"Could not save your changes: {out[:300]}")
    _, head = await _git(folder, "rev-parse", "HEAD")
    return ApplyResult(
        True, "Your changes were saved in git before the task started.", head
    )


# -- W7: start from the latest code (2026-10-09) ------------------------------
# A GitHub project's folder is a clone; without an update a task could start
# from code that is days old. Before a task starts the folder is fast-
# forwarded to GitHub's latest when that's safe; otherwise it is left as it
# is and the task log says why. Never blocks the task.


async def update_from_github(folder: str, token: str | None) -> ApplyResult:
    """Fast-forward the folder's current branch to origin's. `applied` is
    True only when new commits were brought in."""
    from app.services.git_service import (
        NON_INTERACTIVE_GIT_ENV,
        _auth_env,
        _validate_remote_url,
    )

    rc, branch = await _git(folder, "symbolic-ref", "--short", "-q", "HEAD")
    if rc != 0 or not branch:
        return ApplyResult(
            False, "Not updated from GitHub: the folder is not on a branch."
        )
    rc, url = await _git(folder, "remote", "get-url", "origin")
    if rc != 0 or not url:
        return ApplyResult(
            False, "Not updated from GitHub: the folder has no GitHub link."
        )
    try:
        _validate_remote_url(url)
    except Exception:
        return ApplyResult(
            False, "Not updated: the folder's remote is not an allowed host."
        )
    env = _auth_env(url, token) if token else dict(NON_INTERACTIVE_GIT_ENV)
    rc_f, out, err, timed_out = await run_git_process(
        ["git", "-C", folder, *_SAFE, "fetch", "--quiet", "origin", branch],
        folder,
        env,
        120,
    )
    if rc_f != 0 or timed_out:
        reason = "timed out" if timed_out else (err or out).decode(errors="replace")
        from app.services.git_service import scrub_secret

        return ApplyResult(
            False,
            "Could not reach GitHub, so the task works from the copy on this "
            f"computer ({scrub_secret(reason.strip(), token)[:200]}).",
        )
    upstream = f"refs/remotes/origin/{branch}"
    rc, _ = await _git(folder, "rev-parse", "--verify", "--quiet", upstream)
    if rc != 0:
        return ApplyResult(False, f"Not updated: GitHub has no branch {branch}.")
    rc, behind = await _git(folder, "rev-list", "--count", f"HEAD..{upstream}")
    if rc != 0 or behind.strip() in ("", "0"):
        return ApplyResult(False, "Already up to date with GitHub.")
    _, dirty = await _git(folder, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        return ApplyResult(
            False,
            f"Not updated from GitHub ({behind} newer commits there): the folder "
            "has unsaved changes.",
        )
    rc, _ = await _git(folder, "merge-base", "--is-ancestor", "HEAD", upstream)
    if rc != 0:
        return ApplyResult(
            False,
            f"Not updated from GitHub ({behind} newer commits there): this copy "
            "has its own commits, so it was not changed automatically.",
        )
    rc, merged = await _git(folder, "merge", "--ff-only", upstream)
    if rc != 0:
        return ApplyResult(False, f"Not updated from GitHub: {merged[:200]}")
    _, head = await _git(folder, "rev-parse", "HEAD")
    return ApplyResult(
        True, f"Updated to the latest code from GitHub ({behind} new commits).", head
    )
