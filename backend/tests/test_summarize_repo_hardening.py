"""summarize_repo tool #203 — tool_enhance.md productionization pass
(2026-09-16). Closes the deferred item logged in tool #100's
(generate_changelog) own docstring.

Two real, empirically-verified findings, on the one real
implementation (`summarize_repo_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. `repo_path` was an LLM-controlled field that let the caller
   redirect the entire summary at an arbitrary host directory,
   completely outside the intended worktree — `os.walk()` and the
   README-excerpt read both operated directly on the unvalidated
   override. Proved live: an arbitrary outside directory's real file
   tree, extension breakdown, and README content were genuinely
   disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `summarize_repo_handler()` that
IGNORES `repo_path` entirely and always operates on the handler's own
configured `root` — mirroring `generate_changelog_handler`'s exact
precedent (tool #100).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.summarize_repo import (
    SUMMARIZE_REPO_TOOL,
    summarize_repo_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_summarize_repo_hardening", repo_path=repo)
    return ChatAgent(session)


def test_summarize_repo_tool_schema() -> None:
    assert SUMMARIZE_REPO_TOOL["name"] == "summarize_repo"
    assert SUMMARIZE_REPO_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_summarize_repo_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("summarize_repo") == 1


# ---------------------------------------------------------------------------
# Finding #1 — repo_path override ignored, arbitrary-directory escape closed
# ---------------------------------------------------------------------------


def test_make_chat_handlers_ignores_repo_path_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real_file.py").write_text("x = 1\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SECRET_CONFIG.py").write_text("API_KEY = 'sk-outside-secret'\n")
    (outside / "README.md").write_text("# Outside Secret Project\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["summarize_repo"]({"repo_path": str(outside)})
    assert "SECRET_CONFIG" not in result
    assert "Outside Secret Project" not in result
    assert "real_file.py" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_ignores_repo_path_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real_file.py").write_text("x = 1\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SECRET_CONFIG.py").write_text("API_KEY = 'sk-outside-secret'\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "summarize_repo", {"repo_path": str(outside)}
    )
    assert "SECRET_CONFIG" not in result
    assert "real_file.py" in result


def test_handler_ignores_repo_path_override_directly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real_file.py").write_text("x = 1\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SECRET_CONFIG.py").write_text("x = 1\n")

    result = summarize_repo_handler(repo, {"repo_path": str(outside)})
    assert "SECRET_CONFIG" not in result
    assert "real_file.py" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("summarize_repo", {})
    assert "Unknown tool" not in result
    assert "Repository Summary" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_summarizes_a_real_repo(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.ts").write_text("const x = 1;\n")
    (tmp_path / "README.md").write_text("# My Project\nHello world.\n")

    result = summarize_repo_handler(tmp_path, {})
    assert "## Repository Summary" in result
    assert "Total files: 3" in result
    assert "### Top file types" in result
    assert "### Directory tree (3 levels)" in result
    assert "My Project" in result


def test_handler_works_with_no_readme(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    result = summarize_repo_handler(tmp_path, {})
    assert "README" not in result
    assert "Total files: 1" in result


def test_handler_excludes_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("junk\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    result = summarize_repo_handler(tmp_path, {})
    assert ".git" not in result
    assert "Total files: 1" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_summarizes_a_real_repo(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("summarize_repo", {})
    assert "Total files: 1" in result
