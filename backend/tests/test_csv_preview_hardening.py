"""csv_preview tool #132 — tool_enhance.md productionization pass
(2026-09-11).

Three real, empirically-verified findings, on the one real
implementation (`csv_preview_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape that is a genuine ARBITRARY FILE READ —
   `root / path` was never validated. Proved live: a `path` value
   outside the intended worktree was genuinely read, its real CSV
   content returned.
2. A real robustness gap — an uncaught crash on a non-numeric `rows`.
   Proved live: `rows="not_a_number"` raised an unhandled `ValueError`.
3. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131) — every
   real interactive-chat call fell through to "[ERROR] Unknown tool".

All three are now closed via a shared `csv_preview_handler()` using
`check_path_in_worktree()` on `path` and a `try/except` + `[1, 200]`
clamp on `rows`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.csv_preview import CSV_PREVIEW_TOOL, csv_preview_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_csv_preview_hardening", repo_path=repo)
    return ChatAgent(session)


def test_csv_preview_tool_schema() -> None:
    assert CSV_PREVIEW_TOOL["name"] == "csv_preview"
    assert CSV_PREVIEW_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_csv_preview_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("csv_preview") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file read
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\nSECRET1,SECRET2\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["csv_preview"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "SECRET1" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\nSECRET1,SECRET2\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("csv_preview", {"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_path_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\nSECRET1,SECRET2\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = csv_preview_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught crash on non-numeric rows
# ---------------------------------------------------------------------------


def test_handler_no_longer_crashes_on_non_numeric_rows(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    result = csv_preview_handler(
        tmp_path, str(tmp_path), {"path": "data.csv", "rows": "not_a_number"}
    )
    assert result == "[ERROR] rows must be an integer, got 'not_a_number'"


def test_handler_clamps_out_of_range_rows(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    result = csv_preview_handler(
        tmp_path, str(tmp_path), {"path": "data.csv", "rows": -5}
    )
    assert "[ERROR]" not in result


# ---------------------------------------------------------------------------
# Finding #3 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("csv_preview", {"path": "data.csv"})
    assert "Unknown tool" not in result
    assert "Columns: a, b" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_previews_a_real_csv(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n4,5,6\n")
    result = csv_preview_handler(tmp_path, str(tmp_path), {"path": "data.csv"})
    assert result == "Columns: a, b, c\n1 | 2 | 3\n4 | 5 | 6"


def test_handler_reports_empty_csv(tmp_path: Path) -> None:
    (tmp_path / "empty.csv").write_text("")
    result = csv_preview_handler(tmp_path, str(tmp_path), {"path": "empty.csv"})
    assert result == "(empty CSV)"


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = csv_preview_handler(tmp_path, str(tmp_path), {"path": "ghost.csv"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_previews_a_real_csv(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n4,5,6\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("csv_preview", {"path": "data.csv"})
    assert result == "Columns: a, b, c\n1 | 2 | 3\n4 | 5 | 6"
