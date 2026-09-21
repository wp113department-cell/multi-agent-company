"""run_background tool #58 — tool_enhance.md productionization pass
(2026-08-20).

Three real, empirically-verified findings, all fixed in the shared
`app.fleet.process_manager` implementation (not duplicated per call
site):

1. `command` had zero sandboxing — full unrestricted host shell
   execution. Fixed via a real Docker sandbox (mirrors `bash`, tool
   #1's, own `run_sandboxed()`), raised to the user before fixing
   (AskUserQuestion) given the scope.
2. Retroactive fix to `kill_process` (tool #49, already shipped):
   `spawn()`'s `shell=True` Popen made the tracked PID the WRAPPING
   shell, not the real command — `kill()` sent signals to that shell
   wrapper only, leaving the real process orphaned. Fixed via
   `os.killpg()` + `start_new_session=True`.
3. The sandbox originally bind-mounted `cwd` at a fixed `/workspace`
   inside the container (mirroring `run_sandboxed()`) — this broke a
   real, pre-existing test (AUDIT_Q_BATCH01's wait_for_pids dependency
   test) that used an ABSOLUTE HOST PATH under `cwd` in its command:
   that path resolves to nothing inside a `/workspace`-mounted
   container. Fixed by mounting `cwd` at its own path instead.

All tests here spawn REAL Docker containers / REAL OS processes and
check REAL host-visible side effects — nothing is mocked. Tests that
need a real `docker` binary/daemon are marked and skipped if
unavailable, matching this codebase's own convention for
infra-dependent tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.fleet import process_manager as pm
from app.models.chat import ChatSession
from app.tools.execution.run_background import (
    RUN_BACKGROUND_TOOL,
    validate_run_background_cwd,
)

_HAS_DOCKER = shutil.which("docker") is not None


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_run_background_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_run_background_tool_schema_requires_command() -> None:
    assert RUN_BACKGROUND_TOOL["name"] == "run_background"
    assert RUN_BACKGROUND_TOOL["input_schema"]["required"] == ["command"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# cwd worktree-boundary validation (pure, no docker/process needed)
# ---------------------------------------------------------------------------


def test_validator_allows_repo_root_cwd(tmp_path: Path) -> None:
    assert validate_run_background_cwd(str(tmp_path), str(tmp_path)) is None


def test_validator_allows_relative_subdir_cwd(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    assert validate_run_background_cwd(str(sub), str(tmp_path)) is None


def test_validator_rejects_absolute_outside_repo_cwd(tmp_path: Path) -> None:
    outside = tmp_path.parent
    result = validate_run_background_cwd(str(outside), str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


def test_validator_rejects_dotdot_traversal_cwd(tmp_path: Path) -> None:
    result = validate_run_background_cwd(str(tmp_path / ".." / ".."), str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Finding #1 — real Docker sandboxing (skipped if docker unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")
def test_spawn_sandboxed_command_cannot_write_outside_cwd(tmp_path: Path) -> None:
    outside_marker = tmp_path.parent / "rb_hardening_exploit_marker.txt"
    if outside_marker.exists():
        outside_marker.unlink()
    procs: dict[int, "subprocess.Popen[str]"] = {}
    try:
        result = pm.spawn(f"echo pwned > {outside_marker}", str(tmp_path), procs)
        assert "Started background process PID" in result
        time.sleep(3)
        assert (
            not outside_marker.exists()
        ), "sandboxed command must not be able to write outside cwd"
    finally:
        if outside_marker.exists():
            outside_marker.unlink()


@pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")
def test_spawn_sandboxed_command_can_write_inside_cwd(tmp_path: Path) -> None:
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn("echo hello > inside.txt", str(tmp_path), procs)
    assert "Started background process PID" in result
    time.sleep(3)
    assert (tmp_path / "inside.txt").exists()


@pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")
def test_spawn_sandboxed_absolute_path_under_cwd_reaches_host(tmp_path: Path) -> None:
    """Finding #3 regression: an absolute host path under `cwd` (a common
    real pattern — e.g. anything built from `tmp_path` or `repo_path`)
    must still land on the real host filesystem, not vanish inside a
    `/workspace`-mounted container's own ephemeral filesystem."""
    marker = tmp_path / "abs_marker.txt"
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn(f"touch {marker}", str(tmp_path), procs)
    assert "Started background process PID" in result
    time.sleep(3)
    assert marker.exists()


@pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")
def test_spawn_fails_closed_when_sandboxing_enabled_and_docker_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.policy.sandbox._docker_available", lambda: False)
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn("echo hi", str(tmp_path), procs)
    assert "[SANDBOX UNAVAILABLE]" in result
    assert procs == {}


# ---------------------------------------------------------------------------
# Explicit opt-out (BASH_SANDBOX_ENABLED=false) — must still work
# unsandboxed, matching the original pre-sandboxing behavior exactly
# ---------------------------------------------------------------------------


def test_spawn_unsandboxed_when_explicitly_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "bash_sandbox_enabled", False)
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn("echo hello > opt_out.txt", str(tmp_path), procs)
    assert "Started background process PID" in result
    time.sleep(1.5)
    assert (tmp_path / "opt_out.txt").exists()


# ---------------------------------------------------------------------------
# Finding #2 — retroactive kill_process fix: killing a tracked background
# process must reach the REAL command, not just a shell wrapper, whether
# sandboxed or not
# ---------------------------------------------------------------------------


def test_kill_unsandboxed_background_process_actually_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "bash_sandbox_enabled", False)
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn("sleep 60", str(tmp_path), procs)
    pid = int(result.split("PID ")[1].split(":")[0])
    time.sleep(0.5)
    kill_result = pm.kill(pid, "TERM", procs)
    assert "Sent TERM" in kill_result
    time.sleep(1)
    still_alive = subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode
    assert (
        still_alive == 1
    ), "the real sleep process must actually be gone, not orphaned"


@pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")
def test_kill_sandboxed_background_process_stops_container(tmp_path: Path) -> None:
    def _bg_containers() -> set[str]:
        return set(
            subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=gridiron-bg-",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
            ).stdout.split()
        )

    # Scoped to THIS test's own container: the old global "no gridiron-bg
    # anywhere" assertion failed whenever any other test's job was still alive.
    before = _bg_containers()
    procs: dict[int, "subprocess.Popen[str]"] = {}
    result = pm.spawn("sleep 300", str(tmp_path), procs)
    pid = int(result.split("PID ")[1].split(":")[0])
    time.sleep(2)
    mine = _bg_containers() - before
    assert mine, "precondition: the sandbox container should be running"
    kill_result = pm.kill(pid, "TERM", procs)
    assert "Sent TERM" in kill_result
    time.sleep(3)
    assert not (mine & _bg_containers()), "sandboxed container must not be left running"


# ---------------------------------------------------------------------------
# wait_for_pids dependency chaining regression (AUDIT_Q_BATCH01 §58) — must
# still work under sandboxing
# ---------------------------------------------------------------------------


def test_wait_for_pids_dependency_still_works_under_sandboxing(
    tmp_path: Path,
) -> None:
    procs: dict[int, "subprocess.Popen[str]"] = {}
    dep_msg = pm.spawn("sleep 0.3", str(tmp_path), procs)
    dep_pid = int(dep_msg.split("PID ")[1].split(":")[0])

    marker = tmp_path / "dependent_ran.txt"
    dependent_msg = pm.spawn(
        f"touch {marker}", str(tmp_path), procs, wait_for_pids=[dep_pid]
    )
    assert "waiting on" in dependent_msg
    assert not marker.exists()
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.2)
    assert marker.exists()


# ---------------------------------------------------------------------------
# Real dispatch paths (ChatAgent._execute_tool and make_chat_handlers) —
# cwd-escape rejection, and CHAT_TOOLS has no duplicate entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_background_rejects_cwd_outside_repo(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    outside = str(tmp_path.parent)
    result = await agent._execute_tool(
        "run_background", {"command": "echo hi", "cwd": outside}
    )
    assert "[ERROR]" in result


def test_make_chat_handlers_run_background_rejects_cwd_outside_repo(
    tmp_path: Path,
) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    outside = str(tmp_path.parent)
    result = handlers["run_background"]({"command": "echo hi", "cwd": outside})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_run_background_then_kill_process_real_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "bash_sandbox_enabled", False)
    agent = _agent(tmp_path)

    spawn_result = await agent._execute_tool("run_background", {"command": "sleep 60"})
    assert "Started background process PID" in spawn_result
    pid = int(spawn_result.split("PID")[1].split(":")[0].strip())

    kill_result = await agent._execute_tool(
        "kill_process", {"pid": pid, "signal": "KILL"}
    )
    assert "Sent KILL" in kill_result
    time.sleep(0.5)
    still_alive = subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode
    assert still_alive == 1


def test_run_background_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_background") == 1
