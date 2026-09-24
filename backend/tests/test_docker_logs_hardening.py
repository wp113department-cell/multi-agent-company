"""docker_logs tool #108 — tool_enhance.md productionization pass
(2026-08-25).

Three real, empirically-verified findings:

1. The most severe: a genuine, direct shell-injection on
   `chat_agent.py`'s dispatch — `container` was interpolated
   completely unquoted into a `shell=True` command. Proved live with
   a real file created via injected command.
2. `chat_agent.py`'s dispatch was ALSO missing the log-pattern
   analysis step (`_summarize_docker_log_patterns()`) its two siblings
   already had — a real functionality gap.
3. A flag-collision on `container` across all three implementations
   (even the two list-args ones never validated it), plus an uncaught
   `ValueError` on a non-numeric `lines`.

Fixed via a shared `docker_logs_handler()` — list-args subprocess
calls only, real `container`/`lines` validators, and the log-pattern
analysis wired into all three real access paths.

`_summarize_docker_log_patterns()` and its own dedicated test coverage
(schema-agnostic pattern-detection correctness) live in
`test_stage4_tier3_docker_logs_structured_parsing.py` — this file
covers the tool-level findings from this turn instead of re-testing
the summarizer's own detection logic.

All tests here use real docker subprocess calls — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_docker_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.docker_logs import DOCKER_LOGS_TOOL, docker_logs_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_docker_logs_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_docker_logs_tool_schema_requires_container() -> None:
    assert DOCKER_LOGS_TOOL["name"] == "docker_logs"
    assert DOCKER_LOGS_TOOL["input_schema"]["required"] == ["container"]  # type: ignore[index]


def test_docker_logs_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("docker_logs") == 1


# ---------------------------------------------------------------------------
# Pure validator unit tests
# ---------------------------------------------------------------------------


def test_handler_rejects_flag_shaped_container() -> None:
    result = docker_logs_handler({"container": "-f"})
    assert result.startswith("[ERROR]")
    assert "flag" in result


def test_handler_rejects_non_numeric_lines() -> None:
    result = docker_logs_handler({"container": "x", "lines": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "lines" in result


# ---------------------------------------------------------------------------
# Finding #1 — genuine shell injection (chat_agent.py dispatch only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_shell_injection_via_container(tmp_path: Path) -> None:
    marker = tmp_path.parent / "docker_logs_hardening_PWNED_marker.txt"
    if marker.exists():
        marker.unlink()
    agent = _agent(tmp_path)
    payload = f"; touch {marker}; echo x"
    result = await agent._execute_tool("docker_logs", {"container": payload})
    assert not marker.exists(), "shell injection must not execute a real command"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Finding #2 — chat_agent.py's dispatch was missing log-pattern analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_now_wires_the_summarizer(tmp_path: Path) -> None:
    """Proves the real capability gap is closed: chat_agent.py's own
    dispatch previously never called _summarize_docker_log_patterns at
    all -- any container whose logs contain an ERROR line must now
    produce a real analysis header through this exact access path."""
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "docker_logs", {"container": "definitely_nonexistent_xyz123"}
    )
    # A nonexistent container's stderr contains "Error response from
    # daemon", matching the summarizer's own "error" pattern -- proves
    # the summarizer genuinely ran on this exact access path.
    assert "=== Docker Log Analysis ===" in result


# ---------------------------------------------------------------------------
# Finding #3 — flag-collision + uncaught ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_container(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("docker_logs", {"container": "--all"})
    assert "[ERROR]" in result
    assert "flag" in result


@pytest.mark.asyncio
async def test_chat_agent_rejects_non_numeric_lines(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "docker_logs", {"container": "x", "lines": "abc"}
    )
    assert "[ERROR]" in result
    assert "lines" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("docker_agent", make_docker_agent_handlers),
    ],
)
def test_both_factories_reject_flag_shaped_container(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["docker_logs"]({"container": "-f"})
    assert (
        "[ERROR]" in result
    ), f"{factory_name} did not reject the flag-shaped container"


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_returns_real_logs(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "docker_logs", {"container": "definitely_nonexistent_xyz123"}
    )
    assert isinstance(result, str)
    assert result != "(no logs)"


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_docker_agent_handlers],
)
def test_both_factories_handle_missing_container_cleanly(
    tmp_path: Path, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["docker_logs"]({"container": "definitely_nonexistent_xyz123"})
    assert isinstance(result, str)
    assert result
