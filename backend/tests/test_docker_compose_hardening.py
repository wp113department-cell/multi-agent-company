"""docker_compose tool #19 — tool_enhance.md productionization pass
(2026-08-17).

Real, empirically-verified finding (same bug class as tools #8/#16/#18's
siblings): chat_agent.py's real dispatch joined `services` (LLM-
controlled) with `" ".join(...)` and interpolated the result directly
into an f-string `shell=True` command with zero quoting. Proved directly:
a `services` value of `["; touch /tmp/PWNED...; echo "]` created a real
marker file on the host, outside the intended docker compose invocation.

`make_chat_handlers`'s own docker_compose was already safe (list-args
subprocess.run, no shell=True) and needed no fix.

Every test here proves the fix against the REAL dispatch method
(ChatAgent._execute_tool), not a reimplementation.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession
from app.tools.execution.docker_compose import (
    DOCKER_COMPOSE_TOOL,
    build_docker_compose_command,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_docker_compose_hardening", repo_path=repo)
    return ChatAgent(session)


def test_docker_compose_tool_schema_has_action_enum() -> None:
    assert DOCKER_COMPOSE_TOOL["name"] == "docker_compose"
    assert "up" in DOCKER_COMPOSE_TOOL["input_schema"]["properties"]["action"]["enum"]


# ---------------------------------------------------------------------------
# Pure command-builder tests
# ---------------------------------------------------------------------------


def test_builder_quotes_a_malicious_service_name() -> None:
    payload = "; touch /tmp/PWNED; echo "
    cmd, error = build_docker_compose_command("ps", [payload], True)
    assert error is None
    assert cmd is not None
    # The payload must appear as a single shell-quoted token, not break
    # out into a real second command.
    assert "touch /tmp/PWNED" not in cmd or "'" in cmd
    import shlex

    tokens = shlex.split(cmd)
    assert payload in tokens


def test_builder_up_includes_detach_flag() -> None:
    cmd, error = build_docker_compose_command("up", [], True)
    assert error is None
    assert cmd == "docker compose up -d"


def test_builder_up_without_detach() -> None:
    cmd, error = build_docker_compose_command("up", [], False)
    assert error is None
    assert cmd == "docker compose up"


def test_builder_logs_uses_tail_flag() -> None:
    cmd, error = build_docker_compose_command("logs", ["web"], True)
    assert error is None
    assert cmd == "docker compose logs --tail=50 web"


def test_builder_unknown_action_is_an_error() -> None:
    cmd, error = build_docker_compose_command("bogus", [], True)
    assert cmd is None
    assert error is not None
    assert "bogus" in error


def test_builder_quotes_every_action_variant() -> None:
    payload = "$(touch /tmp/pwned)"
    for action in ("down", "restart", "build", "ps", "pull"):
        cmd, error = build_docker_compose_command(action, [payload], True)
        assert error is None
        import shlex

        assert shlex.split(cmd)[-1] == payload


# ---------------------------------------------------------------------------
# The real, proven exploit — verified closed against the real dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_rejects_shell_injection_via_services(
    tmp_path,
) -> None:
    marker = tmp_path / "PWNED_docker_compose.txt"
    payload = f"; touch {marker}; echo "
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "docker_compose", {"action": "ps", "services": [payload]}
    )
    assert not marker.exists()
    # The malicious "service name" is passed to docker compose as a
    # literal (nonexistent) service — docker/compose itself errors on it,
    # it does not get executed as a shell command.
    assert "PWNED" not in result


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_up_still_confirms_and_quotes(tmp_path) -> None:
    marker = tmp_path / "PWNED_up.txt"
    payload = f"; touch {marker}; echo "
    agent = _agent(str(tmp_path))
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=True)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "docker_compose", {"action": "up", "services": [payload]}
        )
    mock_confirm.assert_awaited_once()
    assert not marker.exists()
    assert "PWNED" not in result


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_up_declined_by_user(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    with patch.object(agent, "_confirm", new=AsyncMock(return_value=False)):
        result = await agent._execute_tool("docker_compose", {"action": "up"})
    assert result == "[DENIED] User declined docker compose up."


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_ps_real_execution(tmp_path) -> None:
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: alpine\n"
    )
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("docker_compose", {"action": "ps"})
    # A valid compose file with a real `ps` invocation must reach docker
    # compose itself, not fail with "no configuration file provided" (the
    # error a broken/missing command would produce).
    assert "no configuration file provided" not in result


@pytest.mark.asyncio
async def test_chat_agent_docker_compose_unknown_action_still_errors(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("docker_compose", {"action": "bogus"})
    assert result == "[ERROR] Unknown action: bogus"
