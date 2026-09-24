"""type_check tool #205 — tool_enhance.md productionization pass
(2026-09-16).

One real, SEVERE finding (same class as tools #8/#16/#18/#19/#20/#21):
`app/agents/chat_agent.py`'s own separate `_execute_tool()` dispatch
built its mypy shell command with `path` interpolated COMPLETELY
UNQUOTED into an f-string handed to `subprocess.run(shell=True, ...)`.
Proved live: a real payload injected and executed an arbitrary
command. The sibling `make_chat_handlers()` implementation was ALREADY
safe (`shlex.quote()`'d) — chat_agent.py's dispatch simply never had
that protection wired in.

Fixed via a shared `type_check_handler()` that both real call sites
now delegate to — `path` is always `shlex.quote()`'d.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.type_check import TYPE_CHECK_TOOL, type_check_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_type_check_hardening", repo_path=repo)
    return ChatAgent(session)


def test_type_check_tool_schema() -> None:
    assert TYPE_CHECK_TOOL["name"] == "type_check"
    assert TYPE_CHECK_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_type_check_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("type_check") == 1


# ---------------------------------------------------------------------------
# Finding — shell injection closed on chat_agent.py's real dispatch
# ---------------------------------------------------------------------------


def test_handler_blocks_shell_injection_directly(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_MARKER"
    payload = f"; touch {marker}; echo x"
    result = type_check_handler(
        tmp_path, str(tmp_path), {"path": payload, "language": "python"}
    )
    assert not marker.exists()
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_chat_agent_dispatch_blocks_shell_injection(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_MARKER"
    payload = f"; touch {marker}; echo x"
    agent = _agent(str(tmp_path))
    await agent._execute_tool("type_check", {"path": payload, "language": "python"})
    assert not marker.exists()


def test_make_chat_handlers_blocks_shell_injection(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED_MARKER"
    payload = f"; touch {marker}; echo x"
    handlers = make_chat_handlers(str(tmp_path))
    handlers["type_check"]({"path": payload, "language": "python"})
    assert not marker.exists()


def test_proves_the_original_vulnerability_shape_is_real(tmp_path: Path) -> None:
    """Sanity check that the injection primitive itself is real against
    an UNquoted shell=True command (i.e. this isn't a vacuous test) —
    mirrors exactly what chat_agent.py's old dispatch built."""
    import subprocess

    marker = tmp_path / "UNQUOTED_MARKER"
    py_path = f"; touch {marker}; echo x"
    cmd = f"true && python -m mypy {py_path} --ignore-missing-imports 2>&1 | head -60"
    subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=str(tmp_path), timeout=30
    )
    assert marker.exists()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_runs_real_mypy_and_returns_string(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("x: int = 1\n")
    result = type_check_handler(
        tmp_path, str(tmp_path), {"path": "clean.py", "language": "python"}
    )
    assert isinstance(result, str)
    assert "mypy" in result.lower()


def test_handler_errors_cleanly_with_no_language(tmp_path: Path) -> None:
    result = type_check_handler(tmp_path, str(tmp_path), {"language": "nonexistent"})
    assert result == "[ERROR] No language selected"


@pytest.mark.asyncio
async def test_chat_agent_dispatch_runs_real_mypy(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("x: int = 1\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "type_check", {"path": "clean.py", "language": "python"}
    )
    assert "mypy" in result.lower()


def test_make_chat_handlers_type_check_still_works(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["type_check"]({"language": "python"})
    assert isinstance(result, str)
    assert "mypy" in result.lower()
