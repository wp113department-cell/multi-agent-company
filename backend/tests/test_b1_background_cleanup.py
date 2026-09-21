"""Verification batch B1, items #4/#21-#25 (terminal/session manager, shell
registry, background jobs, monitoring / recovery / cleanup).

Proved live before the fix: with the DEFAULT config (Docker sandbox on) a
run_background job is `sh -c "docker run ... <cmd>"`. Three of the four
cleanup paths signalled only that `sh` wrapper, so the `docker run` client and
the CONTAINER kept running indefinitely:

  * ChatAgent session close        (delete_chat_agent -> proc.terminate())
  * startup orphan sweep           (sweep_orphaned_processes -> os.kill(pid))
  * kill_process(signal=KILL)      (a SIGKILLed docker client can't forward it)
  * liveness reaper                (dead wrapper => entry dropped, container left)

Also: the startup sweep signalled ANY process that currently held a registered
PID, so a recycled PID (after a crash/restart) meant SIGTERM to an unrelated
process.

These tests use real Docker, real processes and the real registry file.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.fleet import bg_process_registry as reg
from app.fleet import process_manager as pm

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "version"], capture_output=True).returncode != 0
    or sys.platform == "win32",
    reason="needs a working Docker daemon and a POSIX host",
)


def _containers(prefix: str = "gridiron-bg-") -> set[str]:
    out = subprocess.run(
        ["docker", "ps", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout.split()
    return set(out)


def _wait_gone(names: set[str], timeout: float = 20.0) -> set[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        left = names & _containers()
        if not left:
            return set()
        time.sleep(0.5)
    return names & _containers()


def _wait_new_container(before: set[str], timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = _containers() - before
        if new:
            return next(iter(new))
        time.sleep(0.3)
    raise AssertionError("sandbox container never started")


@pytest.fixture
def registry(tmp_path: Path):
    path = tmp_path / "bg-processes.json"
    before = _containers()
    with patch.object(reg, "_registry_path", return_value=path):
        yield path
    for c in _containers() - before:  # never leave a stray container behind
        subprocess.run(["docker", "kill", c], capture_output=True)


def _spawn(tmp_path: Path, procs: dict) -> tuple[int, str]:
    before = _containers()
    msg = pm.spawn("sleep 300", str(tmp_path), procs)
    assert msg.startswith("Started background process PID"), msg
    pid = int(msg.split("PID ")[1].split(":")[0])
    return pid, _wait_new_container(before)


def test_kill_process_term_stops_the_container(tmp_path, registry) -> None:
    procs: dict = {}
    pid, name = _spawn(tmp_path, procs)
    assert "Sent TERM" in pm.kill(pid, "TERM", procs)
    assert _wait_gone({name}) == set(), "TERM must stop the sandbox container"


def test_kill_process_kill_stops_the_container(tmp_path, registry) -> None:
    """SIGKILL to the `docker run` client alone leaves the container running."""
    procs: dict = {}
    pid, name = _spawn(tmp_path, procs)
    assert "Sent KILL" in pm.kill(pid, "KILL", procs)
    assert _wait_gone({name}) == set(), "KILL must stop the sandbox container"


def test_startup_sweep_stops_the_container(tmp_path, registry) -> None:
    procs: dict = {}
    pid, name = _spawn(tmp_path, procs)
    killed = reg.sweep_orphaned_processes()
    assert pid in killed
    assert _wait_gone({name}) == set(), "startup sweep must stop the container"
    assert not registry.exists()


def test_session_close_stops_the_container(tmp_path, registry) -> None:
    from app.agents import chat_agent as ca

    procs: dict = {}
    pid, name = _spawn(tmp_path, procs)
    agent = ca.ChatAgent.__new__(ca.ChatAgent)
    agent._background_processes = procs
    ca._chat_agents["b1-session-close"] = agent
    ca.delete_chat_agent("b1-session-close")
    assert _wait_gone({name}) == set(), "session close must stop the container"
    assert str(pid) not in (registry.read_text() if registry.exists() else "")


def test_liveness_reaper_kills_container_of_a_dead_wrapper(tmp_path, registry) -> None:
    """A crashed/killed `sh` wrapper used to just drop the registry entry."""
    procs: dict = {}
    pid, name = _spawn(tmp_path, procs)
    os.kill(pid, signal.SIGKILL)  # the wrapper dies; the container survives
    procs[pid].wait(timeout=10)
    assert name in _containers(), "precondition: container outlives its wrapper"
    dead = reg._sweep_dead_registry_entries()
    assert pid in dead
    assert _wait_gone({name}) == set(), "reaper must stop the orphaned container"


def test_sweep_never_signals_a_recycled_pid(tmp_path, registry) -> None:
    """The registry says PID N was OUR job; N now belongs to an unrelated
    process (created after the entry). It must be left alone."""
    bystander = subprocess.Popen(["sleep", "60"])
    try:
        created = reg.process_start_time(bystander.pid)
        assert created is not None
        reg._write(
            registry,
            {
                str(bystander.pid): {
                    "command": "old job",
                    "cwd": str(tmp_path),
                    "started_at": created - 3600,  # entry predates this process
                    "proc_start": created - 3600,
                    "container": None,
                }
            },
        )
        killed = reg.sweep_orphaned_processes()
        assert bystander.pid not in killed
        time.sleep(0.5)
        assert bystander.poll() is None, "an unrelated process was SIGTERMed"
        assert not registry.exists()
    finally:
        bystander.kill()
        bystander.wait(timeout=5)


def test_signal_process_only_signals_a_group_it_leads() -> None:
    """A child in OUR process group must be signalled individually — killpg
    would take the caller (this test run / the API server) down with it."""
    child = subprocess.Popen(["sleep", "60"])  # same pgid as this process
    try:
        assert os.getpgid(child.pid) == os.getpgid(0)
        assert reg.signal_process(child.pid, signal.SIGTERM) is True
        child.wait(timeout=5)
        assert child.returncode == -signal.SIGTERM
    finally:
        if child.poll() is None:
            child.kill()
    assert reg.signal_process(child.pid, signal.SIGTERM) is False  # already reaped


def test_kill_container_refuses_names_it_did_not_create() -> None:
    """A tampered registry must not be able to `docker kill` arbitrary containers."""
    with patch("app.fleet.bg_process_registry.subprocess.run") as run:
        reg.kill_container("crr2906-db-1", "KILL")
        reg.kill_container("gridiron-bg-zzzzzzzzzzzz", "KILL")
        reg.kill_container("gridiron-bg-0123456789ab; rm -rf /", "KILL")
        assert not run.called
        reg.kill_container("gridiron-bg-0123456789ab", "KILL")
        assert run.called
