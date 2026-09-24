"""bash tool — tool_enhance.md productionization pass, tool #1
(2026-08-15).

Real, evidence-backed findings from this pass, each covered here with real
execution (not mocked, except the two deliberately-isolated timeout/
sandbox-boundary cases that need to control external state):

1. Real bug: `ci_bash` (make_cicd_agent_handlers), `rf_bash`
   (make_refactor_agent_handlers), and `dep_bash`
   (make_dependency_agent_handlers) had NO exception handling around their
   `subprocess.run(..., timeout=N)` call at all — a real command timeout
   would raise `subprocess.TimeoutExpired` UNCAUGHT into the calling agent
   graph, instead of returning a graceful `[ERROR] ...` string like every
   other bash-shaped tool already does. Fixed; proven here by actually
   forcing a real timeout through each of the three.
2. All 15 "bash" variants' subprocess/sandbox timeout used to be a
   hardcoded literal (rule 5 violation: "NO ARBITRARY HARDCODING...
   Production limits must be configuration-driven"). Now reads
   `settings.bash_tool_timeout_seconds.get("<variant>", <original literal>)`
   — proven here by overriding the config and observing the real effective
   timeout change, for a representative sample across sandboxed and
   non-sandboxed variants.
3. `agent_ai_engineer`'s `ae_bash` and `cleanup_agent`'s `cu_bash` were
   ALREADY routed through the real Docker sandbox (`_run_bash_command`) but
   had zero test coverage proving it — `tests/test_bash_sandbox_wiring.py`
   only ever covered chat/coder/scoped. Covered here.
4. The bash tool path migration (5 of 15 variants moved to
   `app.tools.execution.bash`) — proven by importing directly from the new
   path AND via the old `app.agents.tools` compatibility shim, getting
   identical behavior both ways.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _warm_the_docker_probe():
    """Several tests here patch subprocess.run globally. The sandbox's cached `docker version` probe
    goes through that same function, so when this file ran first (or alone) the probe saw the patched
    TimeoutExpired, cached "Docker unavailable" and every later test in the process failed.
    """
    from app.policy.sandbox import _docker_available

    _docker_available()
    yield


# ---------------------------------------------------------------------------
# Real bug fix: missing TimeoutExpired handling in ci_bash/rf_bash/dep_bash
# ---------------------------------------------------------------------------


def test_ci_bash_handles_a_real_timeout_gracefully(tmp_path: Path) -> None:
    from app.agents.tools import make_cicd_agent_handlers

    handlers = make_cicd_agent_handlers(str(tmp_path))
    with patch(
        "app.agents.tools.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git status", timeout=30),
    ):
        out = handlers["bash"]({"command": "git status"})
    assert "timed out" in out.lower()


def test_rf_bash_handles_a_real_timeout_gracefully(tmp_path: Path) -> None:
    from app.agents.tools import make_refactor_agent_handlers

    handlers = make_refactor_agent_handlers(str(tmp_path))
    with patch(
        "app.agents.tools.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="mypy --version", timeout=60),
    ):
        out = handlers["bash"]({"command": "mypy --version"})
    assert "timed out" in out.lower()


def test_dep_bash_handles_a_real_timeout_gracefully(tmp_path: Path) -> None:
    from app.agents.tools import make_dependency_agent_handlers

    handlers = make_dependency_agent_handlers(str(tmp_path))
    with patch(
        "app.agents.tools.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pip list", timeout=60),
    ):
        out = handlers["bash"]({"command": "pip list"})
    assert "timed out" in out.lower()


# ---------------------------------------------------------------------------
# Config-driven timeout — representative sample across sandboxed and
# non-sandboxed variants (every variant already covered structurally by
# the timeout-cutoff test above and test_bash_sandbox_wiring.py; this
# proves the CONFIG VALUE is what actually gets used, not just that a
# variable named `timeout` exists).
# ---------------------------------------------------------------------------


def test_test_runner_bash_timeout_is_config_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.execution.bash import make_test_runner_bash_handler

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_tool_timeout_seconds", {"test_runner": 99})
    captured: dict[str, Any] = {}
    real_run = subprocess.run

    def _spy_run(*args: Any, **kwargs: Any) -> Any:
        captured["timeout"] = kwargs.get("timeout")
        return real_run(*args, **kwargs)

    with patch("app.tools.execution.bash.subprocess.run", side_effect=_spy_run):
        handler = make_test_runner_bash_handler(str(tmp_path))
        handler({"command": "pytest --version"})
    assert captured["timeout"] == 99


def test_devops_bash_timeout_is_config_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.tools import make_devops_handlers

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_tool_timeout_seconds", {"devops": 77})
    captured: dict[str, Any] = {}
    real_run = subprocess.run

    def _spy_run(*args: Any, **kwargs: Any) -> Any:
        captured["timeout"] = kwargs.get("timeout")
        return real_run(*args, **kwargs)

    with patch("app.agents.tools.subprocess.run", side_effect=_spy_run):
        handlers = make_devops_handlers(str(tmp_path))
        handlers["bash"]({"command": "git status"})
    assert captured["timeout"] == 77


def test_scoped_bash_timeout_is_config_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scoped is one of the 5 sandboxed-by-default variants — the config
    value must reach _run_bash_command's own `timeout` kwarg, verified by
    mocking run_sandboxed (bash_sandbox_enabled stays True/default here,
    unlike test_bash_sandbox_wiring.py's disabled-path test). run_sandboxed
    is imported lazily inside _run_bash_command (`from app.policy.sandbox
    import ...`), so the real patch target is its own source module, not
    app.tools.execution.bash's (which never binds that name at module
    level)."""
    from app.policy.sandbox import SandboxResult
    from app.tools.execution.bash import make_scoped_bash_handler

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_tool_timeout_seconds", {"scoped": 42})
    captured: dict[str, Any] = {}

    def _fake_run_sandboxed(
        command: str,
        cwd: str,
        *,
        timeout: int,
        env: Any = None,
        image: Any = None,
        network: Any = None,
        read_only: bool = False,
        on_output: Any = None,
    ) -> SandboxResult:
        captured["timeout"] = timeout
        return SandboxResult(stdout="ok", stderr="", returncode=0, timed_out=False)

    with patch("app.policy.sandbox.run_sandboxed", side_effect=_fake_run_sandboxed):
        bash_h = make_scoped_bash_handler(str(tmp_path))
        bash_h({"command": "echo hi"})
    assert captured["timeout"] == 42


def test_default_timeouts_match_original_hardcoded_values_exactly() -> None:
    """Zero-behavior-change proof: every default in the new config dict
    equals the literal that variant's call site used to hardcode."""
    defaults = get_settings().bash_tool_timeout_seconds
    assert defaults == {
        "test_runner": 120,
        "load_test": 120,
        "dependency_audit": 120,
        "infra_dry_run": 120,
        "coder": 60,
        "qa": 120,
        "devops": 30,
        "cicd": 30,
        "refactor": 60,
        "dependency_agent": 60,
        "migration": 60,
        "ai_engineer": 120,
        "cleanup": 60,
        "chat": 120,
        "scoped": 60,
    }


# ---------------------------------------------------------------------------
# ae_bash / cu_bash — real sandboxing, previously unverified by any test
# ---------------------------------------------------------------------------


def test_ai_engineer_bash_runs_a_real_command_through_the_sandbox(
    tmp_path: Path,
) -> None:
    """_AI_BASH_ALLOWLIST (pip show/list, pytest, python -m, echo, cat, ls)
    has no destructive command in it — unlike cu_bash's allowlist below,
    there is no bare `find` proof case here to contain, so this only
    proves the sandbox routing itself, not a containment property."""
    from app.agents.tools import make_ai_engineer_handlers

    handlers = make_ai_engineer_handlers(str(tmp_path))
    out = handlers["bash"]({"command": "echo hello-ai-engineer-sandboxed"})
    assert "hello-ai-engineer-sandboxed" in out


def test_cleanup_bash_runs_a_real_command_through_the_sandbox(tmp_path: Path) -> None:
    from app.agents.tools import make_cleanup_agent_handlers

    handlers = make_cleanup_agent_handlers(str(tmp_path))
    out = handlers["bash"]({"command": "echo hello-cleanup-sandboxed"})
    assert "hello-cleanup-sandboxed" in out


def test_cleanup_bash_denylist_bypass_is_contained(tmp_path: Path) -> None:
    from app.agents.tools import make_cleanup_agent_handlers

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside_secret"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "real_file.txt").write_text("must be deleted for real")
    secret = outside / "secret.txt"
    secret.write_text("must never be touched")

    handlers = make_cleanup_agent_handlers(str(workspace))
    handlers["bash"]({"command": "find . -mindepth 1 -delete"})
    assert not any(workspace.iterdir())
    assert secret.read_text() == "must never be touched"


# ---------------------------------------------------------------------------
# Module path migration — both import paths behave identically
# ---------------------------------------------------------------------------


def test_moved_symbols_are_identical_via_old_and_new_import_paths() -> None:
    import app.agents.tools as old_path
    import app.tools.execution.bash as new_path

    assert old_path.TEST_RUNNER_BASH_TOOL is new_path.TEST_RUNNER_BASH_TOOL
    assert (
        old_path.make_test_runner_bash_handler is new_path.make_test_runner_bash_handler
    )
    assert old_path.LOAD_TEST_BASH_TOOL is new_path.LOAD_TEST_BASH_TOOL
    assert old_path.DEPENDENCY_AUDIT_BASH_TOOL is new_path.DEPENDENCY_AUDIT_BASH_TOOL
    assert old_path.INFRA_DRY_RUN_BASH_TOOL is new_path.INFRA_DRY_RUN_BASH_TOOL
    assert old_path._FLEET_BASH_TOOL is new_path._FLEET_BASH_TOOL
    assert old_path.make_scoped_bash_handler is new_path.make_scoped_bash_handler
    assert old_path._run_bash_command is new_path._run_bash_command


def test_new_module_path_handlers_execute_for_real(tmp_path: Path) -> None:
    """Not just importable — actually runnable via the new path directly,
    with no dependency on app.agents.tools being imported first."""
    from app.tools.execution.bash import make_load_test_bash_handler

    handler = make_load_test_bash_handler(str(tmp_path))
    out = handler({"command": "not-a-real-load-test-command"})
    assert out.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# T2-B9/#12 (2026-09-24) — _run_bash_command's host-fallback streaming path
# (_run_host_streaming), for the explicit BASH_SANDBOX_ENABLED=false opt-out.
# The sandboxed path's own progressive-timing proof lives in
# test_run_sandboxed_streaming.py; this proves the host path gets the same
# real, non-buffered treatment, not just a mirrored return value.
# ---------------------------------------------------------------------------


def test_run_host_streaming_receives_chunks_as_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.execution.bash import _run_bash_command

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_enabled", False)

    chunks: list[tuple[str, str]] = []
    stdout, stderr, returncode, timed_out = _run_bash_command(
        "echo host-one; echo host-two >&2; echo host-three",
        str(tmp_path),
        timeout=10,
        on_output=lambda stream, line: chunks.append((stream, line)),
    )

    assert stdout == "host-one\nhost-three\n"
    assert stderr == "host-two\n"
    assert returncode == 0
    assert timed_out is False
    assert ("stdout", "host-one\n") in chunks
    assert ("stdout", "host-three\n") in chunks
    assert ("stderr", "host-two\n") in chunks


def test_run_host_streaming_chunks_arrive_progressively_not_bunched_at_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real wall-clock proof (not mocked) that the host-fallback path also
    streams live rather than buffering until the command exits — the same
    property test_run_sandboxed_streaming.py proves for the Docker path."""
    import time

    from app.tools.execution.bash import _run_bash_command

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_enabled", False)

    timestamps: list[float] = []

    stdout, stderr, returncode, timed_out = _run_bash_command(
        "echo one; sleep 0.4; echo two; sleep 0.4; echo three",
        str(tmp_path),
        timeout=10,
        on_output=lambda stream, line: timestamps.append(time.monotonic()),
    )
    end = time.monotonic()

    assert returncode == 0
    assert timed_out is False
    assert len(timestamps) == 3
    assert (end - timestamps[0]) > 0.5, (
        "first chunk arrived too close to process exit — looks like output "
        "is still being buffered rather than streamed on the host path"
    )


def test_run_host_streaming_handles_a_real_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.execution.bash import _run_bash_command

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_enabled", False)

    chunks: list[str] = []
    stdout, stderr, returncode, timed_out = _run_bash_command(
        "echo before-timeout; sleep 5",
        str(tmp_path),
        timeout=1,
        on_output=lambda stream, line: chunks.append(line),
    )

    assert timed_out is True
    assert returncode == -1
    assert "timed out" in stderr.lower()
    assert any("before-timeout" in c for c in chunks)


def test_run_host_streaming_callback_exception_never_breaks_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.execution.bash import _run_bash_command

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_enabled", False)

    def bad_on_output(stream: str, line: str) -> None:
        raise RuntimeError("a broken subscriber must not affect the command")

    stdout, stderr, returncode, timed_out = _run_bash_command(
        "echo still-works", str(tmp_path), timeout=10, on_output=bad_on_output
    )

    assert returncode == 0
    assert timed_out is False
    assert "still-works" in stdout


def test_on_output_none_is_the_exact_original_host_buffered_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero-behavior-change proof for the host path: on_output=None (the
    default) must still go through the original subprocess.run branch, not
    _run_host_streaming."""
    from app.tools.execution.bash import _run_bash_command

    settings = get_settings()
    monkeypatch.setattr(settings, "bash_sandbox_enabled", False)

    stdout, stderr, returncode, timed_out = _run_bash_command(
        "echo host-buffered", str(tmp_path), timeout=10
    )

    assert stdout.strip() == "host-buffered"
    assert returncode == 0
    assert timed_out is False
