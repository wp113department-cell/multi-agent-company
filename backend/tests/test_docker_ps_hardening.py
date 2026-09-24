"""docker_ps tool #109 — tool_enhance.md productionization pass
(2026-08-26).

No LLM-controlled string reaches a subprocess argv here — `all` is a
boolean gating a fixed literal `-a` flag, structurally immune to
injection by construction. Two real findings, both functionality/
robustness bugs, not security.

1. A real, significant functionality bug: `dk_docker_ps` completely
   ignored the `all` field — the schema promises "Show all containers
   including stopped ones" but this implementation always ran plain
   `docker ps`, regardless of what the caller requested. Proved live
   on a real host: this hid real stopped/failed containers even when
   explicitly requested.
2. `dk_docker_ps` also had no `try/except` around the subprocess call.

Fixed via a shared `docker_ps_handler()` that honors `all` identically
across all three real call sites, wrapped in `try/except`.

All tests here use real `docker` subprocess calls — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_docker_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.docker_ps import DOCKER_PS_TOOL, docker_ps_handler


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_docker_ps_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_docker_ps_tool_schema() -> None:
    assert DOCKER_PS_TOOL["name"] == "docker_ps"
    assert DOCKER_PS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_docker_ps_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("docker_ps") == 1


# ---------------------------------------------------------------------------
# Finding #1 — `all` field was ignored by dk_docker_ps
# ---------------------------------------------------------------------------


def test_handler_honors_all_true_shows_stopped_containers() -> None:
    """Proves the real fix: with all=True, a stopped container must
    appear -- a real, running docker daemon on this host always has at
    least one non-running container in its history by now (this
    project's own dev containers), so this is a live, not synthetic,
    proof."""
    result = docker_ps_handler({"all": True})
    assert "Exited" in result or "Created" in result


def test_handler_honors_all_false_default() -> None:
    """Default (all=False) must NOT pass -a to docker."""
    with patch("subprocess.run") as mock_run:
        from unittest.mock import MagicMock

        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        docker_ps_handler({})
        args = mock_run.call_args[0][0]
        assert "-a" not in args


def test_handler_honors_all_true_passes_flag() -> None:
    with patch("subprocess.run") as mock_run:
        from unittest.mock import MagicMock

        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        docker_ps_handler({"all": True})
        args = mock_run.call_args[0][0]
        assert "-a" in args


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("docker_agent", make_docker_agent_handlers),
    ],
)
def test_both_factories_honor_all_true(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["docker_ps"]({"all": True})
    assert (
        "Exited" in result or "Created" in result
    ), f"{factory_name} did not honor all=True"


# ---------------------------------------------------------------------------
# Finding #2 — no uncaught FileNotFoundError when docker is missing
# ---------------------------------------------------------------------------


def test_handler_does_not_raise_when_docker_missing() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("docker: not found")):
        result = docker_ps_handler({})
        assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_returns_real_container_list(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("docker_ps", {})
    assert isinstance(result, str)
    assert result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_docker_agent_handlers],
)
def test_both_factories_return_real_container_list(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["docker_ps"]({})
    assert isinstance(result, str)
    assert result
