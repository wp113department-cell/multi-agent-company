"""subprocess with the platform's secrets removed from the child's environment.

The code-running tools (run_python_snippet, run_node, run_script, run_make, run_tests,
run_single_test, type_check, run_linter, coverage_report, deps_outdated, find_unused_imports)
started their child processes with no `env=`, so the child inherited the server's whole
environment: ANTHROPIC_API_KEY, JWT_SECRET_KEY and DATABASE_URL were readable by any code an
agent ran — including code written by a prompt-injected agent, which can also reach the network.
(The coder's `bash` runs in the Docker sandbox with a minimal environment; these did not.)

Drop-in module: the tool files do `from app.tools.execution import safe_subprocess as subprocess`
and keep calling subprocess.run / Popen / check_output unchanged.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess as _subprocess
from subprocess import (  # noqa: F401  (re-exported so callers keep using the same names)
    DEVNULL,
    PIPE,
    STDOUT,
    CalledProcessError,
    CompletedProcess,
    TimeoutExpired,
)
from typing import Any, Mapping

__all__ = [
    "DEVNULL",
    "PIPE",
    "STDOUT",
    "CalledProcessError",
    "CompletedProcess",
    "TimeoutExpired",
    "safe_env",
    "run",
    "check_output",
    "Popen",
]

_SECRET_NAME = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|AUTH|PRIVATE|DSN|COOKIE)",
    re.IGNORECASE,
)
_SECRET_EXACT = frozenset(
    {"DATABASE_URL", "REDIS_URL", "REDIS_URI", "MONGODB_URI", "AMQP_URL"}
)


def safe_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """`base` (default: the current environment) minus every variable that looks like a credential."""
    source = os.environ if base is None else base
    return {
        name: value
        for name, value in source.items()
        if name not in _SECRET_EXACT and not _SECRET_NAME.search(name)
    }


def _scrubbed(kwargs: dict[str, Any]) -> dict[str, Any]:
    kwargs["env"] = safe_env(kwargs.get("env"))
    return kwargs


def run(*args: Any, **kwargs: Any) -> "_subprocess.CompletedProcess[Any]":
    """Drop-in subprocess.run. Shell commands run in the job sandbox.

    Extra keyword (job sandbox only): `job_network="install"` selects the
    package-install network instead of the default no-network sandbox."""
    job_network = kwargs.pop("job_network", None)
    command = args[0] if args else kwargs.get("args")
    if kwargs.get("shell") and isinstance(command, str) and _job_sandbox_enabled():
        return _run_in_job_container(command, job_network=job_network, **kwargs)
    return _subprocess.run(*args, **_scrubbed(kwargs))


# ---------------------------------------------------------------------------
# Job sandbox (Sol audit A01 / gap audit G1, 2026-10-06)
# ---------------------------------------------------------------------------
# Scrubbing the environment is not isolation: the code-running tools
# (run_python_snippet, run_node, run_script, run_make, run_tests,
# run_single_test, coverage_report, type_check, run_linter, and the npm/pip/
# profiler/formatter tools routed here) ran repository- or model-controlled code
# on the backend host, able to read and write anything the server user can.
# Every SHELL command they run now executes in a throwaway container of the
# toolchain image instead — the same hardening as the bash tool's sandbox:
# non-root, read-only root, all capabilities dropped, no-new-privileges,
# memory/pid/CPU limits, no host environment. Only the working directory is
# mounted, at the SAME absolute path so the tools' existing paths keep working;
# nothing else of the host exists inside. The host's .venv (its interpreter is a
# host path, not runnable inside) is masked so the image's own Python is used;
# node_modules is plain JavaScript and stays usable. Fixed list-form commands (git, rg, ruff, ...) still run on the host —
# they don't execute repository code. Docker unavailable -> the command is
# refused (returncode 126), never run on the host; BASH_SANDBOX_ENABLED=false
# is the explicit, operator-only opt-out, shared with the bash tool.


def run_trusted_on_host(
    *args: Any, **kwargs: Any
) -> "_subprocess.CompletedProcess[Any]":
    """Run on the host, never in the job sandbox — environment still scrubbed.

    Only for commands that need the platform's own environment and cannot
    work in the isolated job container: the fleet APPLY phase re-running
    the platform's OWN test suite (its dependencies, its database) inside a
    human-approved, isolated worktree. Never use it for repository- or
    model-supplied code from a user's workspace."""
    return _subprocess.run(*args, **_scrubbed(kwargs))


def _job_sandbox_enabled() -> bool:
    try:
        from app.config import get_settings

        return bool(get_settings().bash_sandbox_enabled)
    except Exception:
        return True


def _run_in_job_container(
    command: str, *, job_network: str | None = None, **kwargs: Any
) -> "_subprocess.CompletedProcess[Any]":
    import uuid

    from app.config import get_settings
    from app.policy.sandbox import _docker_available

    text = bool(kwargs.get("text") or kwargs.get("universal_newlines"))
    timeout = kwargs.get("timeout")
    cwd = _job_workdir(command, kwargs.get("cwd"))

    def _done(rc: int, out: str, err: str) -> "_subprocess.CompletedProcess[Any]":
        if text:
            return CompletedProcess(command, rc, out, err)
        return CompletedProcess(command, rc, out.encode(), err.encode())

    if cwd is None:
        return _done(
            126,
            "",
            "[SANDBOX] Refusing to mount this directory into the job sandbox "
            "(filesystem root, home directory or one of their ancestors).",
        )
    if not _docker_available():
        return _done(
            126,
            "",
            "[SANDBOX UNAVAILABLE] Docker is not reachable; this command runs only "
            "inside the job sandbox and is never executed on the host.",
        )
    settings = get_settings()
    name = f"gridiron-job-{uuid.uuid4().hex[:12]}"
    # The caller's environment minus secrets (safe_env), minus host-specific
    # paths that would break the image's own toolchain. Passed through an env
    # file, not argv, so values never show up in `ps`.
    # Allowlist, not pass-through: the host's environment (desktop session,
    # IDE sockets, tool paths) is none of the job's business. Variables the
    # caller passes explicitly via env= are kept, minus secrets.
    explicit = dict(kwargs.get("env") or {})
    env = {
        k: v
        for k, v in safe_env(explicit).items()
        if (k in _PASS_ENV or (k in explicit and explicit.get(k) != os.environ.get(k)))
        and k not in _HOST_ONLY_ENV
    }
    for k in _PASS_ENV:
        if k in os.environ and k not in env:
            env[k] = os.environ[k]
    # Packages installed inside the sandbox (pip --user) persist in the
    # worktree between calls, so a repository's own dependencies can be
    # installed once and used by its tests; git ignores the folder.
    user_base = os.path.join(cwd, ".gridiron-sandbox-py")
    env.update(
        {
            "HOME": "/tmp",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUSERBASE": user_base,
            "PATH": f"{user_base}/bin:/usr/local/bin:/usr/bin:/bin",
        }
    )
    _exclude_from_git(cwd, ".gridiron-sandbox-py/")
    import tempfile

    env_file = tempfile.NamedTemporaryFile(
        "w", prefix="gridiron-job-env-", suffix=".env", delete=False
    )
    with env_file:
        for key, value in env.items():
            if "\n" not in value:
                env_file.write(f"{key}={value}\n")
    from app.policy.docker_host import SharedFolderError, mount_args

    try:
        workdir_mount = mount_args(cwd, cwd, "rw")
    except SharedFolderError as exc:
        os.unlink(env_file.name)
        return _done(126, "", f"[SANDBOX UNAVAILABLE] {exc}")
    masks: list[str] = []
    for hidden in (".venv",):
        if os.path.exists(os.path.join(cwd, hidden)):
            masks += ["--tmpfs", f"{os.path.join(cwd, hidden)}:size=1m"]
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network="
        + (
            settings.job_sandbox_install_network
            if job_network == "install"
            else settings.job_sandbox_network
        ),
        "--memory=2g",
        "--pids-limit=512",
        "--cpus=2.0",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/tmp:size=256m,mode=1777",
        "--user",
        f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000",
        "--env-file",
        env_file.name,
        *workdir_mount,
        *masks,
        "-w",
        cwd,
        settings.bash_sandbox_toolchain_image,
        *(["timeout", "-s", "KILL", str(int(timeout))] if timeout else []),
        "sh",
        "-c",
        # GPG_KEY: the python base image's (public) release-signing key id;
        # harmless, but it looks like a credential to the code we run.
        "unset GPG_KEY; " + command,
    ]
    import time

    started = time.monotonic()
    try:
        proc = _subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=(timeout + 30) if timeout else None,  # + container start-up
        )
    except _subprocess.TimeoutExpired:
        _subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)
        raise TimeoutExpired(command, timeout or 0) from None
    finally:
        os.unlink(env_file.name)
    if timeout and proc.returncode == 137 and time.monotonic() - started >= timeout:
        # the in-container `timeout -s KILL` fired: same contract as the host
        raise TimeoutExpired(command, timeout)
    return _done(proc.returncode, proc.stdout, proc.stderr)


_LEADING_CD = re.compile(r"^\s*cd\s+('[^']*'|\S+)\s*&&")


def _job_workdir(command: str, cwd: Any) -> str | None:
    """The one host directory mounted into the job container.

    Explicit `cwd` wins; otherwise a leading `cd X &&` names it (the tool
    handlers build commands that way). With neither, the job gets a fresh
    empty directory: the server's own working directory (which holds the
    platform's code and .env) is never mounted implicitly. Returns None for
    a directory too broad to mount (/, $HOME or an ancestor of either)."""
    import tempfile

    if not cwd:
        m = _LEADING_CD.match(command)
        if m:
            cwd = shlex.split(m.group(1))[0]
    if not cwd:
        return tempfile.mkdtemp(prefix="gridiron-job-")
    real = os.path.realpath(str(cwd))
    home = os.path.realpath(os.path.expanduser("~"))
    for broad in ("/", home):
        if real == broad or broad.startswith(real.rstrip("/") + "/"):
            return None
    return real


# Host variables a job may see (locale, timezone, CI hints).
_PASS_ENV = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TERM",
    "CI",
    "NODE_ENV",
    "PYTHONHASHSEED",
)

# Host paths/settings that must not leak into the image's toolchain.
_HOST_ONLY_ENV = (
    "PATH",
    "HOME",
    "PWD",
    "OLDPWD",
    "SHELL",
    "TMPDIR",
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "SSH_AUTH_SOCK",
)


def _exclude_from_git(cwd: str, pattern: str) -> None:
    """Keep sandbox-local state out of commits: a repo-local, never-committed
    .git/info/exclude entry (the repo's own .gitignore is left untouched)."""
    try:
        top = _subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if top.returncode != 0:
            return
        path = os.path.join(cwd, top.stdout.strip())
        existing = open(path).read() if os.path.exists(path) else ""
        if pattern not in existing.splitlines():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as fh:
                fh.write(
                    ("" if existing.endswith("\n") or not existing else "\n")
                    + pattern
                    + "\n"
                )
    except Exception:
        pass


def check_output(*args: Any, **kwargs: Any) -> Any:
    return _subprocess.check_output(*args, **_scrubbed(kwargs))


def Popen(
    *args: Any, **kwargs: Any
) -> "_subprocess.Popen[Any]":  # noqa: N802 - mirrors subprocess
    return _subprocess.Popen(*args, **_scrubbed(kwargs))
