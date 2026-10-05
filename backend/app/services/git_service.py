"""Async git operations for the Repo Console (P3).
Security rules enforced here (not in the API layer):
- URL allowlist: only github.com, gitlab.com, bitbucket.org (and localhost for tests)
- No shell=True — all subprocess calls use list args
- Workspace scoping: paths must start with ALLOWED_WORKSPACE_PARENT
- Caller must pass workspace_root so we can scope all operations
- Argument-injection safe: every caller-supplied URL/ref/remote is validated so
  it can never be parsed by git as an OPTION (`--upload-pack=CMD` executes a
  command; `checkout -f` discards work; `push --force`), and positional
  arguments are separated with `--` wherever git supports it.
- Credentials never touch argv, the clone URL, or `.git/config`: a token is
  handed to git through GIT_CONFIG_* environment variables as a host-scoped
  `http.<origin>.extraheader` (the same mechanism actions/checkout uses), so
  it is not persisted in the cloned repo and not visible in `ps`.
"""

from __future__ import annotations

import asyncio
import base64
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


_LOCAL_HOSTS = ("localhost", "127.0.0.1")
# First char alphanumeric/underscore => can never be read as an option; no
# whitespace, control chars, `..`, `@{`, `\\` etc. (git's own ref rules are
# looser, this is deliberately the conservative subset real branches use).
_REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/\-]*$")
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._\-]*$")
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+):(?!//)")


def _check_url_chars(url: str) -> None:
    """Reject anything that could change how git/curl parse the URL."""
    if not isinstance(url, str) or not url:
        raise ValueError("Git URL must be a non-empty string.")
    if (
        url != url.strip()
        or url.startswith("-")
        or any(ch.isspace() or ord(ch) < 32 or ch in "\\" for ch in url)
    ):
        raise ValueError(f"Invalid git URL: {url!r}")


def _validate_url(url: str) -> None:
    """Raise ValueError unless url is a plain https:// (or http:// to
    localhost) URL on the host allowlist, with no embedded credentials.

    Previously an EMPTY hostname was accepted, so `--upload-pack=CMD`,
    `ext::sh -c ...`, `/etc`, `file:///...` all passed the allowlist and
    `--upload-pack=CMD` was executed by `git clone` (argument injection).
    """
    _check_url_chars(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(
            f"Only https:// git URLs are supported (got scheme {parsed.scheme!r})."
        )
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise ValueError(
            "Git URLs must not embed credentials — pass the token separately."
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Git URL has no hostname.")
    allowed = [h.lower() for h in _get_allowed_hosts()]
    is_local = host in _LOCAL_HOSTS
    if host not in allowed and not is_local:
        raise ValueError(
            f"Remote host '{host}' is not in the git allowlist. "
            f"Allowed: {', '.join(allowed)}"
        )
    if parsed.scheme == "http" and not is_local:
        raise ValueError("Plain http:// is only allowed for localhost.")


def validate_clone_url(url: str) -> None:
    """Public alias — the one place every clone entry point validates a URL."""
    _validate_url(url)


def _validate_remote_url(url: str) -> None:
    """Validate an ALREADY-CONFIGURED remote's URL before a push.

    More permissive than `_validate_url` on purpose (this URL comes from the
    repo's own config, set by an earlier clone/operator, not from a request):
    userinfo is tolerated (legacy repos cloned with a token in the URL), ssh
    forms are accepted when the host is allowlisted, and a plain local path
    (bare-repo remotes) is fine since it cannot leave the machine. What it
    still refuses: option-looking strings, `ext::`/other transports, and
    http(s)/ssh hosts outside the allowlist.
    """
    _check_url_chars(url)
    if url.startswith(("/", "./", "../", "file://")):
        return
    allowed = [h.lower() for h in _get_allowed_hosts()]
    scp = _SCP_LIKE_RE.match(url)
    if scp:
        host = scp.group(1).lower()
    else:
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http", "ssh"):
            raise ValueError(f"Unsupported git remote URL scheme: {parsed.scheme!r}")
        host = (parsed.hostname or "").lower()
    if not host or (host not in allowed and host not in _LOCAL_HOSTS):
        raise ValueError(
            f"Remote host '{host}' is not in the git allowlist. "
            f"Allowed: {', '.join(allowed)}"
        )


def validate_ref(name: str, what: str = "branch") -> str:
    """A branch/ref name git can never mistake for an option."""
    if (
        not isinstance(name, str)
        or not _REF_RE.match(name)
        or ".." in name
        or "//" in name
        or name.endswith(("/", ".", ".lock"))
    ):
        raise ValueError(f"Invalid {what} name: {name!r}")
    return name


def _validate_remote_name(remote: str) -> str:
    if (
        not isinstance(remote, str)
        or not _REMOTE_NAME_RE.match(remote)
        or ".." in remote
    ):
        raise ValueError(f"Invalid remote name: {remote!r}")
    return remote


def _is_within(real: str, parent: str) -> bool:
    real_parent = os.path.realpath(parent)
    return real == real_parent or real.startswith(real_parent.rstrip(os.sep) + os.sep)


def _validate_workspace(path: str, allow_worktrees: bool = True) -> None:
    """Raise ValueError if path is outside allowed workspace parent.

    The server's own worktrees directory (WORKTREES_DIR, default
    /tmp/gridiron-worktrees) is also allowed for repository operations: the
    coding paths git_add/git_commit inside the task worktree they created. With
    the defaults (/home vs /tmp) every coding task that changed files was
    blocked here — found by the first live-AI run, 2026-10-05; unit tests had
    always pointed allowed_workspace_parent at their tmp dir. A user-supplied
    clone destination (allow_worktrees=False) must still be under the parent.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        parent = settings.allowed_workspace_parent
        worktrees = settings.worktrees_dir
    except Exception:
        parent, worktrees = "/home", ""
    real = os.path.realpath(path)
    if _is_within(real, parent):
        return
    if allow_worktrees and worktrees and _is_within(real, worktrees):
        return
    raise ValueError(f"Path '{path}' is outside allowed workspace parent '{parent}'.")


def _validate_dest(dest_path: str) -> str:
    """dest_path must be an absolute path that is ITSELF inside the workspace
    (previously only its parent was checked, and a relative path resolved
    against the server's cwd)."""
    if (
        not isinstance(dest_path, str)
        or not dest_path.strip()
        or not os.path.isabs(dest_path)
        or "\x00" in dest_path
    ):
        raise ValueError("dest_path must be an absolute path.")
    _validate_workspace(dest_path, allow_worktrees=False)
    return dest_path


def _strip_userinfo(url: str) -> str:
    """Drop any `user[:pw]@` from an http(s) URL so a credential can never be
    persisted as the cloned repo's `remote.origin.url`."""
    _check_url_chars(url)
    parsed = urlparse(url)
    if "@" not in parsed.netloc:
        return url
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"Could not parse URL: {url!r}")
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = parsed.port
    netloc = host + (f":{port}" if port else "")
    return parsed._replace(netloc=netloc).geturl()


# Qoder cross-check SEC-05-101 (2026-10-02): with only GIT_TERMINAL_PROMPT=0,
# git still runs GIT_ASKPASS / SSH_ASKPASS (set by VS Code, desktop sessions)
# on a 401, and that helper can wait forever — a wrong token hung the clone
# indefinitely (reproduced). Empty askpass vars disable the helper; the
# terminal prompt stays disabled, so authentication fails fast instead.
NON_INTERACTIVE_GIT_ENV: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GCM_INTERACTIVE": "never",
}


async def run_git_process(
    cmd: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
) -> tuple[int, bytes, bytes, bool]:
    """Run git non-interactively with a hard timeout. Returns
    (returncode, stdout, stderr, timed_out).

    The process gets its own session so a timeout kills the WHOLE group —
    git spawns git-remote-https (and possibly an askpass helper) which keep
    the pipes open; killing only `git` left communicate() waiting forever.
    """
    import signal

    full_env = {**os.environ, **NON_INTERACTIVE_GIT_ENV, **(env or {})}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=full_env,
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out, err, False
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            pass
        return -1, b"", b"", True


def _auth_env(url: str, token: str) -> dict[str, str]:
    """Environment that makes git send `Authorization: Basic x-access-token:
    <token>` to (only) `url`'s origin. Env vars, not argv/URL/config-file:
    invisible to `ps`, never written into `.git/config`. Needs git >= 2.31."""
    parsed = urlparse(url)
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        **NON_INTERACTIVE_GIT_ENV,
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"http.{parsed.scheme}://{parsed.netloc}/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        # an empty helper resets the list: no stored/OS credential is consulted
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
    }


def scrub_secret(text: str, token: str | None) -> str:
    """Remove a token (and its Basic-auth encoding) from text bound for
    logs, DB rows or API responses."""
    if not token:
        return text
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return text.replace(token, "***").replace(basic, "***")


async def _run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a git command. Returns (returncode, stdout, stderr). No shell=True.

    `env` entries are ADDED to the inherited environment (used to pass
    credentials without putting them on the command line).
    """
    cmd = ["git"] + args
    logger.debug("git %s (cwd=%s)", " ".join(args), cwd)
    rc, stdout_b, stderr_b, timed_out = await run_git_process(cmd, cwd, env, timeout)
    if timed_out:
        return -1, "", f"git {args[0]} timed out after {timeout}s"
    return rc, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def git_clone(
    url: str, dest_path: str, branch: str | None = None
) -> dict[str, Any]:
    """Clone a remote repo to dest_path.

    url must be an allowlisted https URL; dest_path must be an absolute path
    inside allowed_workspace_parent; branch (if given) must be a plain ref
    name. All three are validated BEFORE git sees them and passed after `--`
    so none can be interpreted as a git option.
    """
    _validate_url(url)
    _validate_dest(dest_path)
    args = ["clone"]
    if branch:
        args += ["--branch", validate_ref(branch)]
    args += ["--", url, dest_path]
    rc, stdout, stderr = await _run_git(args, timeout=300.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr, "returncode": rc}


async def git_clone_with_token(
    url: str, dest_path: str, token: str, branch: str | None = None
) -> dict[str, Any]:
    """Clone a private HTTPS repo using a PAT.

    The token is NEVER embedded in the URL or argv (that persisted it in
    plaintext in `<repo>/.git/config`): it is sent via an environment-scoped
    `http.<origin>.extraheader`, so the resulting repo's remote URL is the
    clean one. A `https://TOKEN@host/...` URL is still accepted — the
    userinfo is stripped before use — but the `token` argument is what
    authenticates. Token is scrubbed from any returned output.
    """
    if not token.strip():
        raise ValueError("Token is required for private repo clone.")
    token = token.strip()
    clean_url = _strip_userinfo(url)
    _validate_url(clean_url)
    _validate_dest(dest_path)

    args = ["clone"]
    if branch:
        args += ["--branch", validate_ref(branch)]
    args += ["--", clean_url, dest_path]
    rc, stdout, stderr = await _run_git(
        args, timeout=300.0, env=_auth_env(clean_url, token)
    )
    return {
        "ok": rc == 0,
        "stdout": scrub_secret(stdout, token),
        "stderr": scrub_secret(stderr, token),
        "returncode": rc,
    }


async def git_init(repo_path: str) -> dict[str, Any]:
    """Initialize a new git repository at repo_path (must already exist as a directory)."""
    _validate_workspace(repo_path)
    Path(repo_path).mkdir(parents=True, exist_ok=True)
    rc, stdout, stderr = await _run_git(["init"], cwd=repo_path)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


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
            commits.append(
                {
                    "sha": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "date": parts[3],
                    "message": parts[4],
                }
            )
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


async def git_commit(
    repo_path: str, message: str, author_name: str = "", author_email: str = ""
) -> dict[str, Any]:
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
        "git",
        "commit",
        "-m",
        message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=repo_path,
        env=env,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    rc = proc.returncode or 0
    return {
        "ok": rc == 0,
        "stdout": stdout_b.decode(errors="replace"),
        "stderr": stderr_b.decode(errors="replace"),
    }


async def git_revert(
    repo_path: str, commit_sha: str, author_name: str = "", author_email: str = ""
) -> dict[str, Any]:
    """AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — real primitive
    app.fleet.enhancement_rollback needs: `git revert --no-edit <sha>`
    creates a new commit undoing exactly `commit_sha`'s changes, keeping
    full history (unlike reset/force-push) — the same non-destructive
    rationale every other mutating git_service function here already
    follows. --no-edit accepts git's own auto-generated "Revert ..."
    message so this is safe to call from an unattended scheduled loop with
    no interactive editor available.
    """
    _validate_workspace(repo_path)
    if not commit_sha.strip():
        raise ValueError("commit_sha cannot be empty.")
    # A sha/ref only — never something git could parse as an option
    # (`--abort`, `--no-commit`, `-m 1`, ...).
    if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9._/~^@{}\-]*$", commit_sha.strip()):
        raise ValueError(f"Invalid commit ref: {commit_sha!r}")
    commit_sha = commit_sha.strip()
    env = dict(os.environ)
    if author_name:
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_COMMITTER_NAME"] = author_name
    if author_email:
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_EMAIL"] = author_email
    proc = await asyncio.create_subprocess_exec(
        "git",
        "revert",
        "--no-edit",
        commit_sha,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=repo_path,
        env=env,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    rc = proc.returncode or 0
    if rc != 0:
        # A conflicting/failed revert must never leave the worktree in a
        # half-reverted state for whatever runs next in this repo —
        # `git revert --abort` is a no-op (safe) if there's nothing to abort.
        await _run_git(["revert", "--abort"], cwd=repo_path)
    new_sha = ""
    if rc == 0:
        rc_sha, sha_out, _ = await _run_git(["rev-parse", "HEAD"], cwd=repo_path)
        if rc_sha == 0:
            new_sha = sha_out.strip()
    return {
        "ok": rc == 0,
        "stdout": stdout_b.decode(errors="replace"),
        "stderr": stderr_b.decode(errors="replace"),
        "revertCommitSha": new_sha,
    }


async def git_push(
    repo_path: str, remote: str = "origin", branch: str = ""
) -> dict[str, Any]:
    """Push to remote. Remote URL must be on allowlist (checked via git remote get-url)."""
    _validate_workspace(repo_path)
    # remote/branch used to be passed to git unvalidated, so branch="--force"
    # became a force-push and remote="--receive-pack=CMD" executed a command.
    _validate_remote_name(remote)
    if branch:
        validate_ref(branch)
    # Verify remote URL is on allowlist before pushing
    rc_url, url_out, _ = await _run_git(["remote", "get-url", remote], cwd=repo_path)
    if rc_url == 0 and url_out.strip():
        _validate_remote_url(url_out.strip())
    args = ["push", remote]
    if branch:
        args.append(branch)
    rc, stdout, stderr = await _run_git(args, cwd=repo_path, timeout=120.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


async def git_branch_list(repo_path: str) -> dict[str, Any]:
    """List all local branches."""
    _validate_workspace(repo_path)
    rc, stdout, stderr = await _run_git(
        ["branch", "-a", "--format=%(refname:short)"], cwd=repo_path
    )
    branches = [b.strip() for b in stdout.strip().splitlines() if b.strip()]
    return {"ok": rc == 0, "branches": branches, "stderr": stderr}


async def git_checkout(
    repo_path: str, branch: str, create: bool = False
) -> dict[str, Any]:
    """Checkout or create a branch."""
    _validate_workspace(repo_path)
    # Validate branch name — no path traversal (..), absolute paths or a
    # leading "-": `checkout -f` (force-discard uncommitted work) and
    # `--orphan`/`--detach` used to pass the old regex as a "branch".
    validate_ref(branch)
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(branch)
    rc, stdout, stderr = await _run_git(args, cwd=repo_path)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}


async def git_pull(repo_path: str, remote: str = "origin") -> dict[str, Any]:
    """Pull latest from remote."""
    _validate_workspace(repo_path)
    # `remote` is a request parameter on a login-only route: `--upload-pack=CMD`
    # / `--rebase` etc. must never reach git as an option.
    _validate_remote_name(remote)
    rc, stdout, stderr = await _run_git(["pull", remote], cwd=repo_path, timeout=120.0)
    return {"ok": rc == 0, "stdout": stdout, "stderr": stderr}
