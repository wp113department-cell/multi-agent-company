"""Gap-closure Day 23 (Stage 1.3, answers.md) — proves the durable
background-process registry (app/fleet/bg_process_registry.py) actually
persists PIDs to disk and sweep_orphaned_processes() actually terminates
real leftover processes, using real subprocess.Popen (not mocked) so the
os.kill()-based termination is genuinely exercised.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from app.fleet import bg_process_registry as reg


def _patched_registry_path(tmp_path: Path) -> Path:
    return tmp_path / "bg-processes.json"


def test_register_persists_to_disk(tmp_path: Path) -> None:
    path = _patched_registry_path(tmp_path)
    with patch.object(reg, "_registry_path", return_value=path):
        reg.register(pid=99999, command="npm run dev", cwd="/repo")

    assert path.exists()
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["99999"]["command"] == "npm run dev"
    assert data["99999"]["cwd"] == "/repo"


def test_unregister_removes_the_entry(tmp_path: Path) -> None:
    path = _patched_registry_path(tmp_path)
    with patch.object(reg, "_registry_path", return_value=path):
        reg.register(pid=99999, command="npm run dev", cwd="/repo")
        reg.unregister(pid=99999)

    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "99999" not in data


def test_unregister_on_a_missing_entry_is_a_safe_no_op(tmp_path: Path) -> None:
    path = _patched_registry_path(tmp_path)
    with patch.object(reg, "_registry_path", return_value=path):
        reg.unregister(pid=12345)  # never registered — must not raise
    assert not path.exists()


def test_sweep_terminates_a_real_leftover_process_and_clears_the_registry(
    tmp_path: Path,
) -> None:
    path = _patched_registry_path(tmp_path)
    # A real, long-lived process this test controls end to end — sleeps far
    # longer than the test needs, so if the sweep DIDN'T kill it we'd catch
    # that via proc.poll() below rather than the test just happening to
    # finish first.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    try:
        with patch.object(reg, "_registry_path", return_value=path):
            reg.register(pid=proc.pid, command="sleep 60", cwd=str(tmp_path))
            assert path.exists()

            killed = reg.sweep_orphaned_processes()

        assert proc.pid in killed
        # SIGTERM is not instant — give the OS a moment to actually reap it.
        deadline = time.monotonic() + 5.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert (
            proc.poll() is not None
        ), "sweep must have actually terminated the process"
        assert not path.exists(), "registry file must be cleared after sweep"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_sweep_skips_a_pid_that_is_already_gone(tmp_path: Path) -> None:
    path = _patched_registry_path(tmp_path)
    # A PID that (almost certainly) doesn't correspond to any live process.
    dead_pid = 999999
    with patch.object(reg, "_registry_path", return_value=path):
        reg.register(pid=dead_pid, command="already exited", cwd="/repo")
        killed = reg.sweep_orphaned_processes()

    assert dead_pid not in killed
    assert not path.exists()


def test_sweep_on_an_empty_or_missing_registry_is_a_safe_no_op(tmp_path: Path) -> None:
    path = _patched_registry_path(tmp_path)
    with patch.object(reg, "_registry_path", return_value=path):
        killed = reg.sweep_orphaned_processes()
    assert killed == []
