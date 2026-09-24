"""npm_run tool #54 — tool_enhance.md productionization pass
(2026-08-20).

Real, severe, empirically-verified finding, identical shape to tool
#53's npm_install finding but worse — neither real implementation had
a confirmation gate at all. Proved live through make_chat_handlers (no
confirmation gate anywhere): a real malicious package.json script,
placed outside the repo, was genuinely executed.

Also found and fixed a real inconsistency: make_chat_handlers' own
npm_run_h had no real one-shot caller and produced a real side effect
(arbitrary script execution) — the exact shape npm_install_h/
pip_install_h already handle by being unconditionally blocked; npm_run_h
was apparently missed. Brought in line with its siblings.

Every test here uses real `npm` subprocess execution against real
package.json files on disk (skipped if npm isn't installed), and
proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.npm_run import NPM_RUN_TOOL, validate_npm_run_directory

pytestmark = pytest.mark.skipif(
    shutil.which("npm") is None, reason="npm CLI not installed in this environment"
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_npm_run_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_npm_run_tool_schema_requires_script() -> None:
    assert NPM_RUN_TOOL["name"] == "npm_run"
    assert NPM_RUN_TOOL["input_schema"]["required"] == ["script"]  # type: ignore[index]


def test_npm_run_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("npm_run") == 1


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_outside_repo_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = validate_npm_run_directory(str(outside), str(repo))
    assert result is not None
    assert "escapes worktree boundary" in result


def test_validator_allows_a_real_in_repo_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert validate_npm_run_directory(".", str(repo)) is None


# ---------------------------------------------------------------------------
# The proven arbitrary-code-execution finding — verified closed on both
# real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_npm_run_rejects_outside_repo_directory_before_running_npm(
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
        '"scripts": {"build": "touch ' + str(marker) + '"}}\n'
    )

    agent = _agent(repo)
    result = await agent._execute_tool(
        "npm_run", {"script": "build", "directory": str(outside)}
    )

    assert result.startswith("[ERROR]")
    assert not marker.exists(), "the malicious script must never run"


def test_make_chat_handlers_npm_run_rejects_outside_repo_directory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    outside = tmp_path / "outside2"
    outside.mkdir()
    marker = tmp_path / "PWNED_marker2"
    (outside / "package.json").write_text(
        '{"name": "evil-package-2", "version": "1.0.0", '
        '"scripts": {"build": "touch ' + str(marker) + '"}}\n'
    )

    handlers = make_chat_handlers(str(repo))
    result = handlers["npm_run"]({"script": "build", "directory": str(outside)})

    assert result.startswith("[BLOCKED]")
    assert not marker.exists(), "the malicious script must never run"


# ---------------------------------------------------------------------------
# Regression — legitimate npm_run must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_npm_run_real_script_execution(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(
        '{"name": "legit-repo", "version": "1.0.0", '
        '"scripts": {"hello": "echo hello-from-npm-run"}}\n'
    )

    agent = _agent(repo)
    result = await agent._execute_tool("npm_run", {"script": "hello", "directory": "."})

    assert "hello-from-npm-run" in result
