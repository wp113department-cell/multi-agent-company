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
    assert (
        check_command(bypass_cmd, strict=True).allowed is True
    ), "this test's premise requires the denylist to NOT catch this command"

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
