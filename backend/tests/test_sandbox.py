"""Gap-closure Day 9 (answers.md Q21) — real-Docker proof of
app/policy/sandbox.py's run_sandboxed(), the primitive Day 8's standalone
prototype proved and this day turned into real, wired, tested production
code. Every test here runs a real `docker run` (no mocking of Docker
itself) except test_run_sandboxed_raises_when_docker_unavailable, the one
deliberate exception — there is no way to make a real Docker daemon
"unavailable" for a test without breaking every other test in this file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.policy.sandbox import (
    SandboxUnavailableError,
    _docker_available,
    reset_docker_probe_cache,
    run_sandboxed,
)


def test_docker_is_available_in_this_real_environment() -> None:
    reset_docker_probe_cache()
    assert _docker_available() is True


def test_docker_probe_is_cached_not_reprobed_every_call() -> None:
    reset_docker_probe_cache()
    with patch("app.policy.sandbox.shutil.which", return_value=None) as mock_which:
        first = _docker_available()
        second = _docker_available()
    assert first == second
    mock_which.assert_called_once()  # only probed once, cached after
    reset_docker_probe_cache()


def test_run_sandboxed_executes_a_real_command(tmp_path: Path) -> None:
    result = run_sandboxed("echo hello-sandbox-test", str(tmp_path))
    assert result.returncode == 0
    assert "hello-sandbox-test" in result.stdout
    assert result.timed_out is False


def test_run_sandboxed_env_vars_reach_the_container(tmp_path: Path) -> None:
    result = run_sandboxed(
        "echo $MY_TEST_SECRET",
        str(tmp_path),
        env={"MY_TEST_SECRET": "sandbox-secret-value-123"},
    )
    assert "sandbox-secret-value-123" in result.stdout


def test_run_sandboxed_env_omitted_means_no_leakage_from_host(tmp_path: Path) -> None:
    """A container does NOT inherit the host process's environment
    automatically — a variable set on the host (but not explicitly passed
    via env=) must not appear inside the sandbox."""
    import os

    os.environ["HOST_ONLY_MARKER_DO_NOT_LEAK"] = "should-not-appear"
    try:
        result = run_sandboxed("echo [$HOST_ONLY_MARKER_DO_NOT_LEAK]", str(tmp_path))
        assert "should-not-appear" not in result.stdout
        assert "[]" in result.stdout
    finally:
        del os.environ["HOST_ONLY_MARKER_DO_NOT_LEAK"]


def test_run_sandboxed_contains_a_denylist_bypassing_destructive_command(
    tmp_path: Path,
) -> None:
    """The exact acceptance criterion named in the plan: a command that
    app.policy.engine.check_command() does NOT block (confirmed separately
    — 'find ... -delete' contains no 'rm -rf' substring) is still contained
    to only the mounted workspace when run through the sandbox."""
    from app.policy.engine import check_command

    bypass_cmd = "find /workspace -mindepth 1 -delete"
    assert check_command(bypass_cmd, strict=True).allowed is True, (
        "this test's premise requires the denylist to NOT catch this command"
    )

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside_secret"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "real_file.txt").write_text("must be deleted for real")
    secret = outside / "secret.txt"
    secret.write_text("must never be touched")

    result = run_sandboxed(bypass_cmd, str(workspace))

    assert result.returncode == 0
    assert not any(workspace.iterdir()), "the command must have really executed"
    assert secret.exists() and secret.read_text() == "must never be touched"


def test_run_sandboxed_raises_when_docker_unavailable(tmp_path: Path) -> None:
    reset_docker_probe_cache()
    with patch("app.policy.sandbox.shutil.which", return_value=None):
        with pytest.raises(SandboxUnavailableError):
            run_sandboxed("echo unreachable", str(tmp_path))
    reset_docker_probe_cache()


def test_run_sandboxed_network_none_blocks_egress(tmp_path: Path) -> None:
    result = run_sandboxed(
        "wget -T 3 -q -O- http://example.com >/dev/null 2>&1; echo EXIT=$?",
        str(tmp_path),
        network="none",
    )
    assert "EXIT=0" not in result.stdout


# ---------------------------------------------------------------------------
# Hardening follow-up (tool_enhance.md productionization pass, 2026-08-15) —
# real gaps found by direct empirical testing before being fixed here, not
# assumed: a timed-out `docker run` client dying does NOT stop the
# underlying container (verified by starting one, SIGKILLing the client,
# and finding the container still `Up` seconds later) — this is the real
# regression-proof for the fix.
# ---------------------------------------------------------------------------


def _running_sandbox_container_names() -> list[str]:
    import subprocess

    result = subprocess.run(
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
        timeout=15,
    )
    return [name for name in result.stdout.splitlines() if name]


def test_run_sandboxed_kills_the_container_on_timeout_no_orphan(
    tmp_path: Path,
) -> None:
    """The real regression proof: a command that runs far longer than the
    timeout must not leave its container running in the background after
    run_sandboxed() returns."""
    before = set(_running_sandbox_container_names())

    result = run_sandboxed("sleep 30", str(tmp_path), timeout=2)

    assert result.timed_out is True
    # Give the explicit `docker kill` a brief moment to be reflected in
    # `docker ps` (kill is synchronous, but this stays robust to any
    # daemon-side scheduling delay rather than asserting instantaneously).
    import time

    for _ in range(20):
        after = set(_running_sandbox_container_names())
        if not (after - before):
            break
        time.sleep(0.5)
    else:
        after = set(_running_sandbox_container_names())
    assert not (after - before), (
        f"timed-out sandbox container(s) still running: {after - before}"
    )


def test_run_sandboxed_root_filesystem_is_read_only(tmp_path: Path) -> None:
    result = run_sandboxed(
        "touch /etc/should-not-be-writable 2>&1; echo EXIT=$?", str(tmp_path)
    )
    assert "EXIT=0" not in result.stdout


def test_run_sandboxed_tmp_is_writable_via_tmpfs(tmp_path: Path) -> None:
    result = run_sandboxed(
        "echo scratch > /tmp/scratch.txt && cat /tmp/scratch.txt", str(tmp_path)
    )
    assert "scratch" in result.stdout


def test_run_sandboxed_workspace_remains_writable_despite_read_only_root(
    tmp_path: Path,
) -> None:
    result = run_sandboxed("echo written > /workspace/output.txt", str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "output.txt").read_text().strip() == "written"


def test_run_sandboxed_runs_as_non_root(tmp_path: Path) -> None:
    import os

    result = run_sandboxed("id -u", str(tmp_path))
    assert result.stdout.strip() == str(os.getuid())
    assert result.stdout.strip() != "0"
