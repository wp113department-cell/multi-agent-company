"""Verification batch B1, items #15/#16/#23 (hang detection, waiting for
commands, background vs foreground) and #13/#14 (detect completion/failure).

Proved live before the fix:
  * a background job that prints more than the ~64 KB pipe buffer STALLED
    forever (1.5 MB of output never reached the `touch DONE` after it) because
    nothing drained its pipes unless an agent polled read_output (8 KB/call);
  * read_output on an EXITED job returned only "has exited (code N)" — the job's
    stdout and, crucially, the stderr explaining a failure were discarded.

Real jobs, real pipes; the sandbox is disabled here so the tests exercise the
pipe/drain logic itself on any host (the Docker path streams through the same
Popen pipes and is covered by test_b1_background_cleanup.py).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from app.config import reset_settings_cache
from app.fleet import bg_process_registry as reg
from app.fleet import process_manager as pm


@pytest.fixture(autouse=True)
def _no_sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("BASH_SANDBOX_ENABLED", "false")
    reset_settings_cache()
    monkeypatch.setattr(reg, "_registry_path", lambda: tmp_path / "reg.json")
    yield
    reset_settings_cache()


def _start(cmd: str, cwd: Path, procs: dict) -> int:
    msg = pm.spawn(cmd, str(cwd), procs)
    m = re.search(r"PID (\d+)", msg)
    assert m, msg
    return int(m.group(1))


def _never(_stream) -> str | None:  # legacy reader must not be used for spawned jobs
    raise AssertionError("read_output must use the drained buffer")


def _wait_exit(procs: dict, pid: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while procs[pid].poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert procs[pid].poll() is not None, "job never finished (pipe stall?)"


def test_chatty_job_is_not_blocked_by_a_full_pipe(tmp_path) -> None:
    procs: dict = {}
    pid = _start(f"seq 1 250000; touch {tmp_path}/DONE", tmp_path, procs)
    _wait_exit(procs, pid)
    assert (tmp_path / "DONE").exists()
    out = pm.read_output(pid, 5, procs, _never)
    assert "250000" in out, out  # the tail is there
    assert "earlier line(s) dropped" in out  # bounded buffer said so honestly
    assert "has exited (code 0)" in out


def test_failed_job_output_and_stderr_survive_exit(tmp_path) -> None:
    procs: dict = {}
    pid = _start("echo hello-stdout; echo boom-stderr >&2; exit 3", tmp_path, procs)
    _wait_exit(procs, pid)
    out = pm.read_output(pid, 50, procs, _never)
    assert "hello-stdout" in out
    assert "boom-stderr" in out, "stderr explaining the failure was discarded"
    assert out.rstrip().endswith("has exited (code 3)")


def test_read_output_returns_only_new_lines_each_call(tmp_path) -> None:
    procs: dict = {}
    pid = _start("echo first; sleep 1.5; echo second; sleep 30", tmp_path, procs)
    try:
        time.sleep(0.7)
        assert pm.read_output(pid, 50, procs, _never) == "first"
        assert "no output yet" in pm.read_output(pid, 50, procs, _never)
        time.sleep(1.5)
        assert pm.read_output(pid, 50, procs, _never) == "second"
    finally:
        pm.kill(pid, "KILL", procs)


def test_buffer_is_bounded_and_reports_dropped_lines(tmp_path) -> None:
    procs: dict = {}
    pid = _start("seq 1 20000", tmp_path, procs)
    _wait_exit(procs, pid)
    out = pm.read_output(pid, 10, procs, _never)
    assert "earlier line(s) dropped" in out
    assert "20000" in out
    # nothing left buffered after the read: memory does not accumulate
    buf = procs[pid]._gridiron_output
    assert buf.drain() == ([], 0)


def test_one_enormous_line_cannot_blow_up_memory(tmp_path) -> None:
    procs: dict = {}
    pid = _start("head -c 3000000 /dev/zero | tr '\\0' 'x'", tmp_path, procs)
    _wait_exit(procs, pid)
    buf = procs[pid]._gridiron_output
    lines, _ = buf.drain()
    assert lines and max(len(line) for line in lines) <= pm._MAX_LINE_CHARS
    assert len(lines) <= pm._MAX_BUFFERED_LINES


def test_running_job_reports_no_output_yet_and_unknown_pid_errors(tmp_path) -> None:
    procs: dict = {}
    pid = _start("sleep 30", tmp_path, procs)
    try:
        assert "no output yet" in pm.read_output(pid, 5, procs, _never)
        assert pm.read_output(424242, 5, procs, _never).startswith("[ERROR]")
    finally:
        pm.kill(pid, "KILL", procs)


def test_background_returns_immediately_while_foreground_bash_blocks(tmp_path) -> None:
    """#23: run_background is fire-and-forget; the foreground bash primitive
    returns only after the command finished."""
    from app.tools.execution.bash import _run_bash_command

    procs: dict = {}
    t0 = time.monotonic()
    pid = _start("sleep 3; touch bg_done", tmp_path, procs)
    started_in = time.monotonic() - t0
    try:
        assert started_in < 1.5, f"run_background blocked for {started_in:.1f}s"
        assert not (tmp_path / "bg_done").exists()

        t1 = time.monotonic()
        out, err, rc, timed_out = _run_bash_command(
            "sleep 1; echo fg_done", str(tmp_path), timeout=30
        )
        assert time.monotonic() - t1 >= 1.0
        assert "fg_done" in out and rc == 0 and not timed_out
    finally:
        _wait_exit(procs, pid)
    assert (tmp_path / "bg_done").exists()
