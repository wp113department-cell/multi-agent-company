"""AUDIT_Q_BATCH11 §21 "Sandboxing" — proves ChatAgent._execute_tool's own
`bash` branch (the interactive chat session's real dispatch, distinct from
app.agents.tools.make_chat_handlers used by the ~32 one-shot task agents and
already covered by test_bash_sandbox_wiring.py) now actually runs through
app.policy.sandbox.run_sandboxed instead of a raw host subprocess.

Mirrors test_bash_sandbox_wiring.py's own denylist-bypass containment proof,
at the specific code path (ChatAgent._execute_tool) that was confirmed
bypassing the sandbox entirely across three separate audit batches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession

_BYPASS_CMD = "find . -mindepth 1 -delete"


@pytest.mark.asyncio
async def test_chat_agent_bash_runs_a_real_command_through_the_sandbox(
    tmp_path: Path,
) -> None:
    session = ChatSession(
        session_id="batch11_bash_sandbox_real", repo_path=str(tmp_path)
    )
    agent = ChatAgent(session)
    out = await agent._execute_tool(
        "bash", {"command": "echo hello-chatagent-sandboxed"}
    )
    assert "hello-chatagent-sandboxed" in out


@pytest.mark.asyncio
async def test_chat_agent_bash_denylist_bypass_is_contained(tmp_path: Path) -> None:
    """Same proof as test_bash_sandbox_wiring.py: `find . -mindepth 1 -delete`
    isn't `rm -rf` so the plain command denylist alone lets it through — only
    real container isolation stops it from reaching anything outside the
    mounted workspace."""
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside_secret"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "real_file.txt").write_text("must be deleted for real")
    secret = outside / "secret.txt"
    secret.write_text("must never be touched")

    session = ChatSession(
        session_id="batch11_bash_sandbox_contained", repo_path=str(workspace)
    )
    agent = ChatAgent(session)
    await agent._execute_tool("bash", {"command": _BYPASS_CMD})

    assert not any(workspace.iterdir())
    assert secret.read_text() == "must never be touched"
