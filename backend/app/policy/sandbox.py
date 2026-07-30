"""Sandboxed command execution — gap-closure Day 9 (answers.md Q21).

Real, per-command OS-level isolation for agent bash-tool calls, replacing/
augmenting the previous regex-denylist-only containment — `check_command`'s
own module docstring already admitted that's incomplete ("a real OS-level
sandbox is the only complete fix for this class of gap"), and Day 8's
standalone prototype proved it concretely: `find /workspace -mindepth 1
-delete` is `allowed=True` under the current denylist (no `rm -rf` substring
to match), yet still only destroys the sandboxed container's own ephemeral
filesystem plus the one mounted worktree — never the host, never a sibling
repo, never anything else.

Mechanism: a fresh, `--rm` Docker container per command. `cwd` (the caller's
already-resolved, absolute repo-worktree path) is the ONLY host path made
visible, mounted read-write at /workspace. No `docker.sock` mount — a
sandboxed command has no path back to controlling the host's Docker engine.
Real cgroup-enforced memory/pids/cpu caps, not a wall-clock timeout guess.

Rollout scope, honestly stated (see IMPLEMENTATION_PROGRESS.md's Day 9
entry for the full reasoning): wired into the three fully-generic,
denylist-only bash tools — the ones with no command-prefix allowlist at
all, where a bypassable regex is the *entire* remaining defense. The other
~12 already-allowlist-scoped bash handlers (test-runner, dependency-audit,
QA, devops, etc.) are intentionally NOT wired to this yet: those commands
need the TARGET repo's own installed toolchain (its venv/node_modules),
which the minimal default sandbox image does not have — sandboxing them
correctly needs either a per-repo sandbox image or an install-then-run
flow, real additional work tracked as a named follow-up, not silently
skipped or claimed done.

Fails closed: if Docker isn't reachable, run_sandboxed() raises
SandboxUnavailableError rather than silently falling back to unsandboxed
host execution — a security boundary that silently degrades under a
misconfigured environment is worse than one that visibly fails loudly.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DOCKER_AVAILABLE: bool | None = None


class SandboxUnavailableError(RuntimeError):
    """Raised when the Docker sandbox mechanism cannot run at all.

    Callers must never catch this to silently re-run the command
    unsandboxed — that would defeat the entire point of this module. The
    only legitimate way to run unsandboxed is the explicit, operator-set
    `Settings.bash_sandbox_enabled = False` opt-out, checked by the caller
    before this module is invoked at all.
    """


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


def _docker_available() -> bool:
    """Cached probe — `docker version` is a fast, local, no-network call."""
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is None:
        if shutil.which("docker") is None:
            _DOCKER_AVAILABLE = False
        else:
            try:
                probe = subprocess.run(
                    ["docker", "version", "--format", "{{.Server.Version}}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                _DOCKER_AVAILABLE = probe.returncode == 0
            except Exception:
                _DOCKER_AVAILABLE = False
    return _DOCKER_AVAILABLE


def reset_docker_probe_cache() -> None:
    """Test-only: force the next _docker_available() call to re-probe
    rather than reuse a cached result from an earlier test/process state."""
    global _DOCKER_AVAILABLE
    _DOCKER_AVAILABLE = None


def run_sandboxed(
    command: str,
    cwd: str,
    *,
    image: str | None = None,
    network: str | None = None,
    memory: str = "1g",
    pids_limit: int = 512,
    cpus: str = "1.0",
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    """Run `command` inside a fresh, `--rm` Docker container.

    `cwd` must be an absolute host path — the caller's already-resolved
    repo worktree — bind-mounted read-write at /workspace and nothing else
    of the host visible. `image`/`network` default to
    `Settings.bash_sandbox_image`/`bash_sandbox_network` when not given
    explicitly, so callers don't each have to read settings themselves.
    `env`, when given, is passed as `-e KEY=VALUE` per entry — a container
    does NOT inherit the host process's environment automatically, so a
    caller relying on task-scoped secrets (e.g. make_coder_handlers'
    `extra_env`) must pass them explicitly here or they silently vanish.

    Raises SandboxUnavailableError if Docker cannot run at all.
    """
    if not _docker_available():
        raise SandboxUnavailableError(
            "Docker is not available in this environment — sandboxed "
            "command execution cannot proceed. Refusing to fall back to "
            "unsandboxed host execution. Set BASH_SANDBOX_ENABLED=false "
            "to explicitly opt out of sandboxing instead."
        )

    from app.config import get_settings

    settings = get_settings()
    resolved_image = image if image is not None else settings.bash_sandbox_image
    resolved_network = network if network is not None else settings.bash_sandbox_network

    env_flags: list[str] = []
    for key, value in (env or {}).items():
        env_flags.extend(["-e", f"{key}={value}"])

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        f"--network={resolved_network}",
        f"--memory={memory}",
        f"--pids-limit={pids_limit}",
        f"--cpus={cpus}",
        *env_flags,
        "-v",
        f"{cwd}:/workspace:rw",
        "-w",
        "/workspace",
        resolved_image,
        "sh",
        "-c",
        command,
    ]
    try:
        result = subprocess.run(
            docker_cmd, capture_output=True, text=True, timeout=timeout
        )
        return SandboxResult(
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            returncode=-1,
            timed_out=True,
        )
