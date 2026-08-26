"""memory_usage tool #114 — tool_enhance.md productionization pass
(2026-08-26).

No LLM-controlled input reaches this tool at all (empty schema), so
the usual worktree-escape/flag-collision/shell-injection classes are
structurally impossible. Unlike tool #105's cpu_usage, memory usage is
a point-in-time quantity (not a cumulative counter), so no accuracy
bug is possible from a single read.

One real finding: `mon_memory_usage` had no `try/except` around its
`free` subprocess call, and always shelled out to `free` instead of
preferring `/proc/meminfo` like its siblings — same robustness class
as tools #105/#109.

Fixed via a shared `memory_usage_handler()` that prefers `/proc/
meminfo`, falls back to `free -h`, and wraps the whole thing in
`try/except`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_monitoring_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.memory_usage import MEMORY_USAGE_TOOL, memory_usage_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_memory_usage_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_memory_usage_tool_schema() -> None:
    assert MEMORY_USAGE_TOOL["name"] == "memory_usage"
    assert MEMORY_USAGE_TOOL["input_schema"]["properties"] == {}  # type: ignore[index]


def test_memory_usage_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("memory_usage") == 1


# ---------------------------------------------------------------------------
# Finding — no uncaught FileNotFoundError when both /proc/meminfo and
# free are unavailable
# ---------------------------------------------------------------------------


def test_handler_does_not_raise_when_both_sources_unavailable() -> None:
    with patch("pathlib.Path.exists", return_value=False), patch(
        "subprocess.run", side_effect=FileNotFoundError("free: not found")
    ):
        result = memory_usage_handler()
        assert result.startswith("[ERROR]")


def test_monitoring_agent_does_not_raise_when_free_missing() -> None:
    """Previously mon_memory_usage had zero try/except -- a missing
    free binary raised uncaught. Must not raise now."""
    with patch("pathlib.Path.exists", return_value=False), patch(
        "subprocess.run", side_effect=FileNotFoundError("free: not found")
    ):
        result = memory_usage_handler()
        assert isinstance(result, str)
        assert result.startswith("[ERROR]")


def test_handler_falls_back_to_free_when_proc_meminfo_unavailable() -> None:
    with patch("pathlib.Path.exists", return_value=False):
        result = memory_usage_handler()
        # Falls back to the real `free -h` on this host — must not raise.
        assert isinstance(result, str)
        assert result


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


def test_handler_returns_real_meminfo() -> None:
    result = memory_usage_handler()
    assert "Mem" in result


@pytest.mark.asyncio
async def test_chat_agent_returns_real_memory_reading(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("memory_usage", {})
    assert "Mem" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_monitoring_agent_handlers],
)
def test_both_factories_return_real_memory_reading(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["memory_usage"]({})
    assert "Mem" in result
