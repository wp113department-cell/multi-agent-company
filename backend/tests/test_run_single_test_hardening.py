"""run_single_test tool #62 — tool_enhance.md productionization pass
(2026-08-22).

Two real, empirically-verified findings, both fixed at the shared
`validate_run_single_test_file()` / `run_single_test_handler()` in
`app.tools.execution.run_single_test`:

1. Classic shell injection in `chat_agent.py`'s real dispatch only (the
   `tools.py` implementation was already correctly `shlex.quote()`'d,
   not exposed to this one) — `keyword` was interpolated inside single
   quotes in an f-string with no escaping (`-k '{rst_kw}'`). Proved
   live: `keyword="x' ; touch /tmp/PWNED ; echo '"` created the marker
   file.
2. A worktree-boundary escape via `file` on BOTH real implementations,
   including the one already correctly `shlex.quote()`'d: pytest
   collection executes a Python file's module-level code at import
   time, so quoting the path (which only prevents shell metacharacter
   injection) does nothing to stop pytest from importing and running an
   attacker-chosen file's arbitrary top-level code. Proved live: a real
   outside-repo file with a module-level `os.system(...)` side effect
   was genuinely executed through both real call sites.

All tests here use REAL pytest subprocess execution against real
temporary test files and check REAL host-visible side effects — nothing
is mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.run_single_test import (
    RUN_SINGLE_TEST_TOOL,
    validate_run_single_test_file,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_run_single_test_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_run_single_test_tool_schema_requires_keyword() -> None:
    assert RUN_SINGLE_TEST_TOOL["name"] == "run_single_test"
    assert RUN_SINGLE_TEST_TOOL["input_schema"]["required"] == ["keyword"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# validate_run_single_test_file (pure)
# ---------------------------------------------------------------------------


def test_validator_allows_no_file(tmp_path: Path) -> None:
    assert validate_run_single_test_file("", str(tmp_path)) is None


def test_validator_allows_relative_file_inside_repo(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    assert (
        validate_run_single_test_file("tests/test_x.py", str(tmp_path)) is None
    )


def test_validator_rejects_absolute_file_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "evil.py"
    result = validate_run_single_test_file(str(outside), str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


def test_validator_rejects_dotdot_traversal(tmp_path: Path) -> None:
    result = validate_run_single_test_file("../../etc/evil.py", str(tmp_path))
    assert result is not None
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Finding #1 — shell injection (chat_agent.py's real dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_single_test_rejects_quote_breakout_injection(
    tmp_path: Path,
) -> None:
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    marker = tmp_path.parent / "run_single_test_hardening_shell_pwn.txt"
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        payload = f"x' ; touch {marker} ; echo '"
        result = await agent._execute_tool("run_single_test", {"keyword": payload})
        assert isinstance(result, str)
        assert not marker.exists(), "shell metacharacters must not be interpreted"
    finally:
        if marker.exists():
            marker.unlink()


# ---------------------------------------------------------------------------
# Finding #2 — worktree-boundary escape via `file` (both real call
# sites) — pytest's own import-time code execution, proven independent
# of shell-injection protection
# ---------------------------------------------------------------------------


def _write_evil_test_file(outside_dir: Path, marker: Path) -> Path:
    outside_dir.mkdir(exist_ok=True)
    evil = outside_dir / "test_evil.py"
    evil.write_text(
        f"import os\nos.system('touch {marker}')\n\ndef test_noop():\n    assert True\n"
    )
    return evil


@pytest.mark.asyncio
async def test_chat_agent_run_single_test_rejects_file_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    outside_dir = tmp_path.parent / "run_single_test_hardening_outside"
    marker = outside_dir / "pwned.txt"
    evil = _write_evil_test_file(outside_dir, marker)
    if marker.exists():
        marker.unlink()
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "run_single_test", {"keyword": "noop", "file": str(evil)}
        )
        assert "[ERROR]" in result
        assert not marker.exists(), "must not import/run a test file outside the repo"
    finally:
        if marker.exists():
            marker.unlink()
        evil.unlink()
        outside_dir.rmdir()


def test_make_chat_handlers_run_single_test_rejects_file_outside_repo(
    tmp_path: Path,
) -> None:
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    outside_dir = tmp_path.parent / "run_single_test_hardening_outside2"
    marker = outside_dir / "pwned.txt"
    evil = _write_evil_test_file(outside_dir, marker)
    if marker.exists():
        marker.unlink()
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["run_single_test"]({"keyword": "noop", "file": str(evil)})
        assert "[ERROR]" in result
        assert not marker.exists()
    finally:
        if marker.exists():
            marker.unlink()
        evil.unlink()
        outside_dir.rmdir()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_run_single_test_runs_a_real_matching_test(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "backend" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_sample.py").write_text(
        "def test_pass_me():\n    assert True\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("run_single_test", {"keyword": "pass_me"})
    assert "1 passed" in result


def test_make_chat_handlers_run_single_test_runs_a_real_matching_test(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "backend" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_sample.py").write_text(
        "def test_pass_me():\n    assert True\n"
    )
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_single_test"]({"keyword": "pass_me"})
    assert "1 passed" in result


def test_explicit_file_inside_repo_still_works(tmp_path: Path) -> None:
    tests_dir = tmp_path / "backend" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_explicit.py").write_text(
        "def test_explicit_match():\n    assert True\n"
    )
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_single_test"](
        {"keyword": "explicit_match", "file": "backend/tests/test_explicit.py"}
    )
    assert "1 passed" in result


def test_run_single_test_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_single_test") == 1
