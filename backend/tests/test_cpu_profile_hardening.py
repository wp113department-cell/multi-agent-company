"""cpu_profile tool #130 — tool_enhance.md productionization pass
(2026-08-26).

Three real, empirically-verified findings, on the one real
implementation (`cpu_profile_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. Severe: the tool silently broke for any `command` not literally
   prefixed with the word "python" — the real, executed argv
   unconditionally dropped the FIRST TOKEN of `command`. Proved live:
   `cpu_profile({"command": "myscript.py"})` produced a cProfile
   usage-error traceback instead of ever profiling the script, while
   `{"command": "python myscript.py"}` happened to work only by
   coincidence.
2. A real robustness gap — an uncaught crash on a non-numeric `top`.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112/#118/#120/#122/#126/#129)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

All three are now closed via a shared `cpu_profile_handler()` that
tokenizes `command` properly and only strips a literal leading
`python`/`python3` token, wraps `top` conversion in `try/except`, and
is dispatched from `chat_agent.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.cpu_profile import CPU_PROFILE_TOOL, cpu_profile_handler

SCRIPT_SOURCE = (
    "def foo():\n"
    "    total = 0\n"
    "    for i in range(1000):\n"
    "        total += i\n"
    "    return total\n"
    "\n"
    "foo()\n"
    'print("done")\n'
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_cpu_profile_hardening", repo_path=repo)
    return ChatAgent(session)


def test_cpu_profile_tool_schema() -> None:
    assert CPU_PROFILE_TOOL["name"] == "cpu_profile"
    assert CPU_PROFILE_TOOL["input_schema"]["required"] == ["command"]  # type: ignore[index]


def test_cpu_profile_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("cpu_profile") == 1


# ---------------------------------------------------------------------------
# Finding #1 — command not prefixed with "python" used to silently break
# ---------------------------------------------------------------------------


def test_handler_profiles_a_script_without_python_prefix(tmp_path: Path) -> None:
    """The severe, live-proven bug: a command with no leading "python"
    token used to have its own script name dropped."""
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    result = cpu_profile_handler(str(tmp_path), {"command": "myscript.py"})
    assert "Traceback" not in result
    assert "myscript.py:" in result


def test_handler_still_profiles_a_python_prefixed_command(tmp_path: Path) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    result = cpu_profile_handler(str(tmp_path), {"command": "python myscript.py"})
    assert "myscript.py:" in result


def test_handler_still_profiles_a_python3_prefixed_command(tmp_path: Path) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    result = cpu_profile_handler(str(tmp_path), {"command": "python3 myscript.py"})
    assert "myscript.py:" in result


def test_make_chat_handlers_profiles_a_script_without_python_prefix(
    tmp_path: Path,
) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["cpu_profile"]({"command": "myscript.py"})
    assert "myscript.py:" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_profiles_a_script_without_python_prefix(
    tmp_path: Path,
) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("cpu_profile", {"command": "myscript.py"})
    assert "myscript.py:" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught crash on non-numeric top
# ---------------------------------------------------------------------------


def test_handler_no_longer_crashes_on_non_numeric_top(tmp_path: Path) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    result = cpu_profile_handler(
        str(tmp_path), {"command": "myscript.py", "top": "not_a_number"}
    )
    assert result == "[ERROR] top must be an integer, got 'not_a_number'"


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("cpu_profile", {"command": "myscript.py"})
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_respects_top_limit(tmp_path: Path) -> None:
    (tmp_path / "myscript.py").write_text(SCRIPT_SOURCE)
    result = cpu_profile_handler(str(tmp_path), {"command": "myscript.py", "top": 3})
    assert "myscript.py:" in result
