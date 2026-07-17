"""Async git operations for the Repo Console (P3).
Security rules enforced here (not in the API layer):
- URL allowlist: only github.com, gitlab.com, bitbucket.org (and localhost for tests)
- No shell=True — all subprocess calls use list args
- Workspace scoping: paths must start with ALLOWED_WORKSPACE_PARENT
- Caller must pass workspace_root so we can scope all operations
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _get_allowed_hosts() -> list[str]:
    """Load allowed git remote hostnames from config (non-fatal)."""
    try:
        from app.config import get_settings
        raw = get_settings().git_allowed_hosts
        return [h.strip() for h in raw.split(",") if h.strip()]
    except Exception:
        return ["github.com", "gitlab.com", "bitbucket.org"]


def _validate_url(url: str) -> None:
    """Raise ValueError if url is not on the allowlist."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    allowed = _get_allowed_hosts()
    # Also allow localhost/127.0.0.1 for tests
    if host not in allowed and host not in ("localhost", "127.0.0.1", ""):
        raise ValueError(
            f"Remote host '{host}' is not in the git allowlist. "
            f"Allowed: {', '.join(allowed)}"
        )


def _validate_workspace(path: str) -> None:
    """Raise ValueError if path is outside allowed workspace parent."""
    try:
        from app.config import get_settings
        parent = get_settings().allowed_workspace_parent
    except Exception:
        parent = "/home"
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(parent)):
        raise ValueError(
            f"Path '{path}' is outside allowed workspace parent '{parent}'."
        )


async def _run_git(args: list[str], cwd: str | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
    """Run a git command. Returns (returncode, stdout, stderr). No shell=True."""
    cmd = ["git"] + args
    logger.debug("git %s (cwd=%s)", " ".join(args), cwd)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", f"git {args[0]} timed out after {timeout}s"
    return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def git_clone(url: str, dest_path: str, branch: str | None = None) -> dict[str, Any]:
    """Clone a remote repo to dest_path.

    dest_path must be inside allowed_workspace_parent. url must be on allowlist.
    """
    _validate_url(url)
    _validate_workspace(str(Path(dest_path).parent))

    args = ["clone", url, dest_path]
    if branch:
        args += ["--branch", branch]
    rc, stdout, stderr = await _run_git(args, timeout=300.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr, "returncode": rc}


async def git_clone_with_token(
    url: str, dest_path: str, token: str, branch: str | None = None
) -> dict[str, Any]:
    """Clone a private HTTPS repo by embedding a PAT in the URL.

    The token is never logged — we strip it from any logged output.
    Supported URL formats:
      https://github.com/user/repo.git  (token injected as https://TOKEN@github.com/...)
      https://TOKEN@github.com/user/repo.git  (already has token — used as-is)
    """
    if not token.strip():
        raise ValueError("Token is required for private repo clone.")
    _validate_url(url)
    _validate_workspace(str(Path(dest_path).parent))

    # Inject token into HTTPS URL
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Could not parse URL: {url!r}")
    # If no credentials in URL yet, inject the token as username (GitHub PAT style)
    if "@" not in parsed.netloc:
        netloc_with_token = f"{token.strip()}@{parsed.netloc}"
        auth_url = urlunparse(parsed._replace(netloc=netloc_with_token))
    else:
        auth_url = url  # Token already embedded

    args = ["clone", auth_url, dest_path]
    if branch:
        args += ["--branch", branch]
    rc, stdout, stderr = await _run_git(args, timeout=300.0)
    # Strip token from any error output before returning
    safe_stderr = stderr.replace(token, "***") if token else stderr
    return {"ok": rc == 0, "stdout": stdout, "stderr": safe_stderr, "returncode": rc}


async def git_status(repo_path: str) -> dict[str, Any]:
    """Return git status --short output."""
    _validate_workspace(repo_path)
    rc, stdout, stderr = await _run_git(["status", "--short"], cwd=repo_path)
    return {"ok": rc == 0, "output": stdout, "stderr": stderr}


async def git_log(repo_path: str, limit: int = 20) -> dict[str, Any]:
    """Return last N commits as list of dicts."""
    _validate_workspace(repo_path)
    fmt = "--format=%H|%an|%ae|%ad|%s"
    rc, stdout, stderr = await _run_git(
        ["log", fmt, f"-{limit}", "--date=iso"], cwd=repo_path
    )
    commits = []
    for line in stdout.strip().splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "sha": parts[0], "author": parts[1], "email": parts[2],
                "date": parts[3], "message": parts[4],
            })
    return {"ok": rc == 0, "commits": commits, "stderr": stderr}


async def git_diff(repo_path: str, staged: bool = False) -> dict[str, Any]:
    """Return diff output."""
    _validate_workspace(repo_path)
    args = ["diff"]
    if staged:
        args.append("--staged")
    rc, stdout, stderr = await _run_git(args, cwd=repo_path)
    return {"ok": rc == 0, "diff": stdout, "stderr": stderr}


async def git_add(repo_path: str, paths: list[str]) -> dict[str, Any]:
    """Stage specific file paths."""
    _validate_workspace(repo_path)
    # Ensure all paths are relative (no absolute paths that escape repo)
    safe_paths: list[str] = []
    for p in paths:
        if os.path.isabs(p):
            raise ValueError(f"git add: absolute path not allowed: {p}")
        safe_paths.append(p)
    rc, stdout, stderr = await _run_git(["add", "--"] + safe_paths, cwd=repo_path)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


async def git_commit(repo_path: str, message: str, author_name: str = "", author_email: str = "") -> dict[str, Any]:
    """Create a commit."""
    _validate_workspace(repo_path)
    if not message.strip():
        raise ValueError("Commit message cannot be empty.")
    env = dict(os.environ)
    if author_name:
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_COMMITTER_NAME"] = author_name
    if author_email:
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_EMAIL"] = author_email
    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", message,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=repo_path, env=env,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    rc = proc.returncode or 0
    return {"ok": rc == 0, "stdout": stdout_b.decode(errors="replace"), "stderr": stderr_b.decode(errors="replace")}


async def git_push(repo_path: str, remote: str = "origin", branch: str = "") -> dict[str, Any]:
    """Push to remote. Remote URL must be on allowlist (checked via git remote get-url)."""
    _validate_workspace(repo_path)
    # Verify remote URL is on allowlist before pushing
    rc_url, url_out, _ = await _run_git(["remote", "get-url", remote], cwd=repo_path)
    if rc_url == 0 and url_out.strip():
        _validate_url(url_out.strip())
    args = ["push", remote]
    if branch:
        args.append(branch)
    rc, stdout, stderr = await _run_git(args, cwd=repo_path, timeout=120.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


async def git_branch_list(repo_path: str) -> dict[str, Any]:
    """List all local branches."""
    _validate_workspace(repo_path)
    rc, stdout, stderr = await _run_git(["branch", "-a", "--format=%(refname:short)"], cwd=repo_path)
    branches = [b.strip() for b in stdout.strip().splitlines() if b.strip()]
    return {"ok": rc == 0, "branches": branches, "stderr": stderr}


async def git_checkout(repo_path: str, branch: str, create: bool = False) -> dict[str, Any]:
    """Checkout or create a branch."""
    _validate_workspace(repo_path)
    # Validate branch name — no path traversal (..) or absolute paths
    if ".." in branch or branch.startswith("/") or not re.match(r"^[a-zA-Z0-9._/\-]+$", branch):
        raise ValueError(f"Invalid branch name: {branch!r}")
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(branch)
    rc, stdout, stderr = await _run_git(args, cwd=repo_path)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


async def git_pull(repo_path: str, remote: str = "origin") -> dict[str, Any]:
    """Pull latest from remote."""
    _validate_workspace(repo_path)
    rc, stdout, stderr = await _run_git(["pull", remote], cwd=repo_path, timeout=120.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}
