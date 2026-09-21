"""Verification batch B1, items #8 (Docker terminal handling) and #10 (safe
shell execution / injection prevention).

The regex denylist is documented as ONE layer; the real defense for the generic
bash tool is the Docker sandbox. So these are black-box tests of that boundary:
hostile commands (chaining, redirection, host paths, env probing, docker.sock,
fork/mem/pids caps, timeouts, Docker outage) sent through the REAL chat `bash`
tool dispatch, asserting on real host-visible side effects.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "version"], capture_output=True).returncode != 0
    or sys.platform == "win32",
    reason="needs a working Docker daemon and a POSIX host",
)


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP-SECRET-HOST-FILE\n")
    return repo, outside


def _bash(repo: Path, command: str, cwd: str | None = None) -> str:
    agent = ChatAgent(ChatSession(session_id="b1_sandbox", repo_path=str(repo)))
    inp = {"command": command}
    if cwd:
        inp["cwd"] = cwd
    return asyncio.run(agent._execute_tool("bash", inp))


def test_runs_as_the_host_user_not_root(world) -> None:
    repo, _ = world
    assert str(os.getuid()) in _bash(repo, "id -u")


def test_root_filesystem_is_read_only(world) -> None:
    repo, _ = world
    out = _bash(repo, "touch /etc/pwned && echo WROTE")
    assert "WROTE" not in out
    assert "Read-only" in out or "Permission denied" in out


def test_docker_socket_is_not_exposed(world) -> None:
    repo, _ = world
    out = _bash(repo, "ls -l /var/run/docker.sock /run/docker.sock 2>&1; echo END")
    assert "No such file" in out and "srw" not in out


def test_host_files_outside_the_worktree_are_invisible(world) -> None:
    repo, outside = world
    out = _bash(repo, f"cat {outside}/secret.txt")
    assert "TOP-SECRET-HOST-FILE" not in out


def test_host_environment_is_not_inherited(world, monkeypatch) -> None:
    repo, _ = world
    monkeypatch.setenv("B1_HOST_SECRET_ENV", "sekret-value-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    out = _bash(repo, "env")
    assert "sekret-value-123" not in out
    assert "sk-ant-should-not-leak" not in out


def test_worktree_is_writable_and_visible_on_the_host(world) -> None:
    repo, _ = world
    _bash(repo, "echo hello > made-in-sandbox.txt")
    assert (repo / "made-in-sandbox.txt").read_text().strip() == "hello"


@pytest.mark.parametrize(
    "template",
    [
        "echo x; touch {m}",
        "echo x && touch {m}",
        "echo $(touch {m})",
        "echo `touch {m}`",
        "true | touch {m}",
        "echo x > {m}",
        "sh -c 'touch {m}'",
        "cd / && touch {m}",
    ],
)
def test_injection_shapes_never_reach_the_host_filesystem(world, template) -> None:
    repo, outside = world
    marker = outside / "HOST_MARKER"
    _bash(repo, template.format(m=marker))
    assert not marker.exists(), f"escaped the sandbox via: {template}"


def test_resource_caps_are_real_cgroup_limits(world) -> None:
    repo, _ = world
    out = _bash(
        repo,
        "cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max "
        "/sys/fs/cgroup/cpu.max 2>&1",
    )
    assert "1073741824" in out  # --memory=1g
    assert "512" in out  # --pids-limit=512
    assert "100000 100000" in out  # --cpus=1.0


def test_fork_bomb_is_contained_by_the_pids_limit(world) -> None:
    repo, _ = world
    t0 = time.monotonic()
    _bash(repo, "for i in $(seq 1 3000); do sleep 30 & done; wait", cwd=None)
    # the run must end (pids cap => fork failures, not a host meltdown)
    assert time.monotonic() - t0 < 120


def test_cwd_outside_the_repo_is_rejected(world) -> None:
    repo, outside = world
    out = _bash(repo, "cat secret.txt", cwd=str(outside))
    assert "[POLICY DENIED]" in out
    assert "TOP-SECRET-HOST-FILE" not in out


def test_fails_closed_when_docker_is_unreachable(world, monkeypatch) -> None:
    """Never silently run a hostile command on the host instead."""
    repo, outside = world
    marker = outside / "RAN_ON_HOST"
    monkeypatch.setattr("app.policy.sandbox._docker_available", lambda: False)
    out = _bash(repo, f"touch {marker}")
    assert "[SANDBOX UNAVAILABLE]" in out
    assert not marker.exists()


def test_timeout_kills_the_container_not_just_the_client(world) -> None:
    from app.tools.execution.bash import _run_bash_command

    repo, _ = world

    def running() -> set[str]:
        return set(
            subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=gridiron-sandbox-",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
            ).stdout.split()
        )

    before = running()
    _, err, rc, timed_out = _run_bash_command("sleep 300", str(repo), timeout=3)
    assert timed_out and rc == -1
    deadline = time.monotonic() + 15
    while (running() - before) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not (running() - before), "timed-out command left its container running"


def test_sandbox_disabled_is_an_explicit_operator_opt_out_only(
    world, monkeypatch
) -> None:
    """With BASH_SANDBOX_ENABLED=false the command runs on the host — proving the
    default really is the sandbox (the marker below only appears when opted out)."""
    from app.config import get_settings

    repo, outside = world
    marker = outside / "HOST_RAN_OPTED_OUT"
    monkeypatch.setattr(get_settings(), "bash_sandbox_enabled", False)
    _bash(repo, f"touch {marker}")
    assert marker.exists()
