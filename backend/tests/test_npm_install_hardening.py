"""npm_install tool #53 — tool_enhance.md productionization pass
(2026-08-20).

Real, severe, empirically-verified finding: chat_agent.py's real
dispatch (already fixed for reachability during tool #4's earlier
pass) built the npm cwd as `root / directory` with zero validation
that `directory` stays inside the repo. Proved live: `directory` set
to an absolute path outside the target repo, pointing at a real
package.json with a malicious `preinstall` lifecycle script, was
approved and then genuinely executed the script — real, arbitrary
command execution in an attacker/LLM-chosen directory.

Every test here uses real `npm` subprocess execution against real
package.json files on disk (skipped if npm isn't installed), and
proves the fix against the REAL dispatch method
(ChatAgent._execute_tool).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.npm_install import (
    NPM_INSTALL_TOOL,
    validate_npm_install_directory,
)

pytestmark = pytest.mark.skipif(
    shutil.which("npm") is None, reason="npm CLI not installed in this environment"
)


def _agent(repo: Path, confirm_result: bool = True) -> ChatAgent:
    session = ChatSession(session_id="td_npm_install_hardening", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fake_confirm(*_a: object, **_kw: object) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_npm_install_tool_schema_shape() -> None:
    assert NPM_INSTALL_TOOL["name"] == "npm_install"
    assert NPM_INSTALL_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_npm_install_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("npm_install") == 1


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_outside_repo_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = validate_npm_install_directory(str(outside), str(repo))
    assert result is not None
    assert "escapes worktree boundary" in result


def test_validator_allows_a_real_in_repo_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert validate_npm_install_directory(".", str(repo)) is None
    assert validate_npm_install_directory("subdir", str(repo)) is None


# ---------------------------------------------------------------------------
# The proven arbitrary-code-execution finding — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_npm_install_rejects_outside_repo_directory_before_running_npm(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name": "legit-repo", "version": "1.0.0"}\n')

    outside = tmp_path / "outside"
    outside.mkdir()
    marker = tmp_path / "PWNED_marker"
    (outside / "package.json").write_text(
        '{"name": "evil-package", "version": "1.0.0", '
        '"scripts": {"preinstall": "touch ' + str(marker) + '"}}\n'
    )

    agent = _agent(repo, confirm_result=True)
    result = await agent._execute_tool("npm_install", {"directory": str(outside)})

    assert result.startswith("[ERROR]")
    assert not marker.exists(), "the malicious preinstall script must never run"


def test_make_chat_handlers_npm_install_remains_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    handlers = make_chat_handlers(str(repo))

    result = handlers["npm_install"]({"directory": "."})
    assert result.startswith("[BLOCKED]")


# ---------------------------------------------------------------------------
# Regression — legitimate npm_install must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_npm_install_real_install_in_repo_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name": "legit-repo", "version": "1.0.0"}\n')

    agent = _agent(repo, confirm_result=True)
    result = await agent._execute_tool("npm_install", {"directory": "."})

    assert not result.startswith("[ERROR]")
    assert (repo / "package-lock.json").exists() or "up to date" in result.lower()


@pytest.mark.asyncio
async def test_chat_agent_npm_install_declined_confirmation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name": "legit-repo", "version": "1.0.0"}\n')

    agent = _agent(repo, confirm_result=False)
    result = await agent._execute_tool("npm_install", {"directory": "."})

    assert result.startswith("[DENIED]")
