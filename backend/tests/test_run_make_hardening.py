"""run_make tool #59 — tool_enhance.md productionization pass
(2026-08-22).

Three real, empirically-verified findings, all fixed at the shared
`run_make_handler()` / `validate_run_make_inputs()` in
`app.tools.execution.run_make`:

1. Classic shell injection in `chat_agent.py`'s real dispatch only (the
   `tools.py` implementation already used list-args argv, not exposed
   to this one) — `target` was interpolated raw into an f-string then
   run via a shell=True helper. Proved live: `target="build; touch
   /tmp/PWNED; echo"` created the marker file.
2. A second, independent code-execution primitive affecting BOTH real
   implementations, including the one already using list-args: GNU
   Make's own argument parser recognizes flag-shaped values even with
   no shell involved. Proved live against the list-args
   `make_chat_handlers` implementation: `target="--eval=$(shell touch
   /tmp/PWNED)"` was accepted by `make` as its own `--eval` flag.
3. A worktree-boundary escape via `directory` on BOTH implementations
   (same pathlib bug class as tools #10/#11/#18/#23/#43) — `root /
   directory` silently discards `root` when `directory` is absolute.
   Proved live end-to-end: a real Makefile OUTSIDE the repo had one of
   its targets genuinely executed.

All tests here use REAL `make` subprocess execution against real
temporary Makefiles and check REAL host-visible side effects — nothing
is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.run_make import RUN_MAKE_TOOL, validate_run_make_inputs


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_run_make_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_run_make_tool_schema_has_no_required_fields() -> None:
    assert RUN_MAKE_TOOL["name"] == "run_make"
    assert RUN_MAKE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


# ---------------------------------------------------------------------------
# validate_run_make_inputs (pure)
# ---------------------------------------------------------------------------


def test_validator_allows_plain_target_and_no_directory(tmp_path: Path) -> None:
    assert validate_run_make_inputs("build", "", str(tmp_path)) is None


def test_validator_allows_relative_subdir(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    assert validate_run_make_inputs("build", "sub", str(tmp_path)) is None


@pytest.mark.parametrize(
    "flag_target",
    ["-n", "-C/tmp", "-f/etc/passwd", "--eval=$(shell id)", "--", "-"],
)
def test_validator_rejects_flag_shaped_targets(
    flag_target: str, tmp_path: Path
) -> None:
    result = validate_run_make_inputs(flag_target, "", str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


def test_validator_rejects_directory_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent
    result = validate_run_make_inputs("build", str(outside), str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


def test_validator_rejects_directory_dotdot_traversal(tmp_path: Path) -> None:
    result = validate_run_make_inputs("build", "../../etc", str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Finding #1 — shell injection (chat_agent.py's real dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_make_rejects_shell_metacharacter_injection(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text("build:\n\t@echo building\n")
    marker = tmp_path.parent / "run_make_hardening_shell_pwn.txt"
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_make", {"target": f"build; touch {marker}; echo"}
        )
        assert "No rule to make target" in result or "[ERROR]" in result
        assert not marker.exists(), "shell metacharacters must not be interpreted"
    finally:
        if marker.exists():
            marker.unlink()


# ---------------------------------------------------------------------------
# Finding #2 — GNU make's own flag-injection (both real call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_make_rejects_eval_flag_injection(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("build:\n\t@echo building\n")
    marker = tmp_path.parent / "run_make_hardening_eval_pwn.txt"
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_make", {"target": f"--eval=$(shell touch {marker})"}
        )
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()


def test_make_chat_handlers_run_make_rejects_eval_flag_injection(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text("build:\n\t@echo building\n")
    marker = tmp_path.parent / "run_make_hardening_eval_pwn2.txt"
    if marker.exists():
        marker.unlink()
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["run_make"]({"target": f"--eval=$(shell touch {marker})"})
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()


# ---------------------------------------------------------------------------
# Finding #3 — directory worktree-escape (both real call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_make_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text("build:\n\t@echo building\n")
    outside_dir = tmp_path.parent / "run_make_hardening_outside"
    outside_dir.mkdir(exist_ok=True)
    marker = outside_dir / "pwned.txt"
    (outside_dir / "Makefile").write_text(f"evil:\n\t@touch {marker}\n")
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_make", {"target": "evil", "directory": str(outside_dir)}
        )
        assert "[ERROR]" in result
        assert not marker.exists(), "must not run a Makefile target outside the repo"
    finally:
        if marker.exists():
            marker.unlink()
        if (outside_dir / "Makefile").exists():
            (outside_dir / "Makefile").unlink()
        outside_dir.rmdir()


def test_make_chat_handlers_run_make_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text("build:\n\t@echo building\n")
    outside_dir = tmp_path.parent / "run_make_hardening_outside2"
    outside_dir.mkdir(exist_ok=True)
    marker = outside_dir / "pwned.txt"
    (outside_dir / "Makefile").write_text(f"evil:\n\t@touch {marker}\n")
    if marker.exists():
        marker.unlink()
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["run_make"]({"target": "evil", "directory": str(outside_dir)})
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()
        if (outside_dir / "Makefile").exists():
            (outside_dir / "Makefile").unlink()
        outside_dir.rmdir()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_make_runs_a_legitimate_target(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("hello:\n\t@echo hello_from_make\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("run_make", {"target": "hello"})
    assert "hello_from_make" in result


@pytest.mark.asyncio
async def test_chat_agent_run_make_lists_targets_when_empty(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("test:\n\t@echo t\n\nbuild:\n\t@echo b\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("run_make", {})
    assert "Targets" in result or "not parseable" in result


def test_make_chat_handlers_run_make_runs_a_legitimate_target(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("hello:\n\t@echo hello_from_make\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_make"]({"target": "hello"})
    assert "hello_from_make" in result


def test_make_chat_handlers_run_make_relative_subdir_still_works(
    tmp_path: Path,
) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "Makefile").write_text("hello:\n\t@echo hello_from_subdir\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_make"]({"target": "hello", "directory": "sub"})
    assert "hello_from_subdir" in result


def test_no_makefile_still_errors_cleanly(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_make"]({"target": "build"})
    assert "[ERROR]" in result and "Makefile" in result


def test_run_make_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_make") == 1
