"""docker_exec tool #20 — tool_enhance.md productionization pass
(2026-08-17).

Real, empirically-verified findings — chat_agent.py's real dispatch had
THREE gaps at once, all absent from tools.py's own, already-correct
implementations of the same tool:

1. Shell injection via `container` (same bug class as tools
   #8/#16/#18/#19) — only `command` was `shlex.quote()`'d, `container`
   was interpolated raw into an f-string `shell=True` command. Proved
   directly: a `container` value shaped like a shell command created a
   real marker file on the host.
2. No `_docker_container_risk_reason` check at all — both tools.py
   implementations already had this (rejects exec into a
   `--privileged`/host-mounted/dangerous-capability container); the real
   interactive dispatch never had it wired in.
3. No destructive-command check — `make_chat_handlers`'s own
   implementation already ran `command` through `check_command()`;
   chat_agent.py's dispatch had none.

Tests that need a real docker binary/daemon (and a real running
container — reuses gridiron-postgres if present, matching this
project's own dev-environment convention) are skipped otherwise.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession
from app.tools.execution.docker_exec import DOCKER_EXEC_TOOL, build_docker_exec_command

_HAS_DOCKER = shutil.which("docker") is not None


def _real_running_container() -> str | None:
    if not _HAS_DOCKER:
        return None
    r = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    )
    names = [n for n in r.stdout.splitlines() if n.strip()]
    return names[0] if names else None


pytestmark = pytest.mark.skipif(not _HAS_DOCKER, reason="requires a real docker binary")


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_docker_exec_hardening", repo_path=repo)
    return ChatAgent(session)


def test_docker_exec_tool_schema_requires_container_and_command() -> None:
    assert DOCKER_EXEC_TOOL["name"] == "docker_exec"
    assert DOCKER_EXEC_TOOL["input_schema"]["required"] == ["container", "command"]


def test_builder_quotes_a_malicious_container_name() -> None:
    payload = "; touch /tmp/PWNED; echo "
    cmd = build_docker_exec_command(payload, "echo hi")
    import shlex

    tokens = shlex.split(cmd)
    assert payload in tokens
    assert tokens[0:2] == ["docker", "exec"]


def test_builder_quotes_a_malicious_command() -> None:
    payload = "echo hi; touch /tmp/PWNED"
    cmd = build_docker_exec_command("mycontainer", payload)
    import shlex

    tokens = shlex.split(cmd)
    assert payload in tokens


# ---------------------------------------------------------------------------
# The real, proven exploits — verified closed against the real dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_docker_exec_rejects_shell_injection_via_container(
    tmp_path,
) -> None:
    marker = tmp_path / "PWNED_docker_exec.txt"
    payload = f"x; touch {marker}; echo "
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "docker_exec", {"container": payload, "command": "echo hi"}
    )
    assert not marker.exists()
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_docker_exec_rejects_destructive_command(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "docker_exec", {"container": "somecontainer", "command": "rm -rf /"}
    )
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_docker_exec_fails_closed_on_uninspectable_container(
    tmp_path,
) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "docker_exec",
        {"container": "td-nonexistent-container-xyz", "command": "echo hi"},
    )
    assert result.startswith("[POLICY DENIED]")
    assert "could not inspect" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage against a real running container
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_docker_exec_real_command_in_real_container(tmp_path) -> None:
    container = _real_running_container()
    if container is None:
        pytest.skip("no real running container available")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "docker_exec", {"container": container, "command": "echo hello_from_container"}
    )
    assert "hello_from_container" in result
