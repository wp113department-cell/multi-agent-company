"""summarize_folder tool #202 — tool_enhance.md productionization pass
(2026-09-16).

Two real, empirically-verified findings, on the one real
implementation (`summarize_folder_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape that is a real file-existence/
   absolute-path disclosure oracle — `root / path` was never
   validated. Proved live: a real file's true absolute path outside
   the intended worktree was disclosed via the tool's own
   `relative_to()` ValueError message text (though line/function/class
   counts are not disclosed on this path — a narrower leak than
   siblings' full structured-content leaks, but a real one). A
   pre-existing code comment sitting immediately above this tool's old
   schema location in tools.py claimed "no injection/worktree surface
   exists" for it — that comment actually belongs to the unrelated
   neighboring `_ESTIMATE_COMPLEXITY_TOOL` (tool #110) and does not
   apply here; this turn's own direct investigation (not the comment)
   is what found and proved this finding.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `summarize_folder_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.summarize_folder import (
    SUMMARIZE_FOLDER_TOOL,
    summarize_folder_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_summarize_folder_hardening", repo_path=repo)
    return ChatAgent(session)


def test_summarize_folder_tool_schema() -> None:
    assert SUMMARIZE_FOLDER_TOOL["name"] == "summarize_folder"
    assert SUMMARIZE_FOLDER_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_summarize_folder_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("summarize_folder") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape file-existence/absolute-path disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret_module.py").write_text('API_KEY = "sk-outside-secret"\n')

    handlers = make_chat_handlers(str(repo))
    result = handlers["summarize_folder"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "secret_module" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret_module.py").write_text('API_KEY = "sk-outside-secret"\n')

    agent = _agent(str(repo))
    result = await agent._execute_tool("summarize_folder", {"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "secret_module" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret_module.py").write_text("x = 1\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = summarize_folder_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("summarize_folder", {"path": "."})
    assert "Unknown tool" not in result
    assert "a.py" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_summarizes_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def foo():\n    pass\n\n\nclass Bar:\n    pass\n"
    )
    result = summarize_folder_handler(tmp_path, str(tmp_path), {"path": "."})
    assert "a.py" in result
    assert "1 functions" in result
    assert "1 classes" in result


def test_handler_respects_extensions_filter(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.md").write_text("# heading\n")
    result = summarize_folder_handler(
        tmp_path, str(tmp_path), {"path": ".", "extensions": [".md"]}
    )
    assert "b.md" in result
    assert "a.py" not in result


def test_handler_reports_no_matching_files(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("hi\n")
    result = summarize_folder_handler(tmp_path, str(tmp_path), {"path": "."})
    assert result == "(no matching files)"


def test_handler_errors_cleanly_on_missing_path(tmp_path: Path) -> None:
    result = summarize_folder_handler(
        tmp_path, str(tmp_path), {"path": "does_not_exist"}
    )
    assert "[ERROR] Path not found" in result


def test_handler_truncates_at_20_files(tmp_path: Path) -> None:
    for i in range(25):
        (tmp_path / f"f{i}.py").write_text("x = 1\n")
    result = summarize_folder_handler(tmp_path, str(tmp_path), {"path": "."})
    assert "(truncated — 20 file limit)" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_summarizes_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("summarize_folder", {"path": "."})
    assert "a.py" in result
    assert "1 functions" in result
