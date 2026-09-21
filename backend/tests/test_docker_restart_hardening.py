"""docker_restart tool #21 — tool_enhance.md productionization pass
(2026-08-17).

Real, empirically-verified finding (same bug class as tools
#8/#16/#18/#19/#20): chat_agent.py's real dispatch interpolated
`container` (LLM-controlled) directly into an f-string `shell=True`
command with zero quoting. Proved directly: a `container` value shaped
like a shell command created a real marker file on the host.

Both tools.py implementations were already safe (list-args, no
`shell=True`) and needed no change.

The regression test uses a disposable container it creates and removes
itself (never touches real, already-running infrastructure — restarting
a container has a real, if brief, disruptive side effect).
"""

from __future__ import annotations

import shutil
import subprocess
import uuid

from unittest.mock import AsyncMock

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession
from app.tools.execution.docker_restart import (
    DOCKER_RESTART_TOOL,
    build_docker_restart_command,
)

_HAS_DOCKER = shutil.which("docker") is not None

pytestmark = pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_docker_restart_hardening", repo_path=repo)
    return ChatAgent(session)


def test_docker_restart_tool_schema_requires_container() -> None:
    assert DOCKER_RESTART_TOOL["name"] == "docker_restart"
    assert DOCKER_RESTART_TOOL["input_schema"]["required"] == ["container"]


def test_builder_quotes_a_malicious_container_name() -> None:
    payload = "; touch /tmp/PWNED; echo "
    cmd = build_docker_restart_command(payload)
    import shlex

    tokens = shlex.split(cmd)
    assert payload in tokens
    assert tokens[0:2] == ["docker", "restart"]


@pytest.mark.asyncio
async def test_chat_agent_docker_restart_rejects_shell_injection(tmp_path) -> None:
    marker = tmp_path / "PWNED_docker_restart.txt"
    payload = f"x; touch {marker}; echo "
    agent = _agent(str(tmp_path))
    agent._confirm = AsyncMock(return_value=True)  # restart now asks first (B3)
    result = await agent._execute_tool("docker_restart", {"container": payload})
    assert not marker.exists()
    assert "No such container" in result


@pytest.fixture
def disposable_container():
    name = f"td-docker-restart-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "alpine", "sleep", "300"],
        capture_output=True,
        check=True,
    )
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.mark.asyncio
async def test_chat_agent_docker_restart_real_container(
    tmp_path, disposable_container
) -> None:
    agent = _agent(str(tmp_path))
    agent._confirm = AsyncMock(return_value=True)  # restart now asks first (B3)
    result = await agent._execute_tool(
        "docker_restart", {"container": disposable_container}
    )
    assert disposable_container in result
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", disposable_container],
        capture_output=True,
        text=True,
    )
    assert inspect.stdout.strip() == "true"
