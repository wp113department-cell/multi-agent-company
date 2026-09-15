"""loc_stats tool #166 — tool_enhance.md productionization pass
(2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`loc_stats_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine LINE-COUNT-STATISTICS
   DISCLOSURE oracle. `root/directory` was never validated. Proved
   live: real per-file-extension line-count statistics for a
   directory outside the worktree were genuinely disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `loc_stats_handler()` using
`check_path_in_worktree()` on `directory`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.loc_stats import LOC_STATS_TOOL, loc_stats_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_loc_stats_hardening", repo_path=repo)
    return ChatAgent(session)


def test_loc_stats_tool_schema() -> None:
    assert LOC_STATS_TOOL["name"] == "loc_stats"
    assert LOC_STATS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_loc_stats_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("loc_stats") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape line-count-statistics disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("line1\nline2\nline3\n")

        out = loc_stats_handler(worktree, str(worktree), {"directory": str(outside)})
        assert "POLICY DENIED" in out
        assert ".py" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.py").write_text("x\n")

        out = loc_stats_handler(worktree, str(worktree), {"directory": ".."})
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("x\n")

        handlers = make_chat_handlers(str(worktree))
        out = handlers["loc_stats"]({"directory": str(outside)})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("x\n")

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "loc_stats", {"directory": str(outside)}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x\ny\nz\n")
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("loc_stats", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert ".py" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree files, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_stats(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("1\n2\n3\n")
        (tmp_path / "b.txt").write_text("1\n2\n")
        out = loc_stats_handler(tmp_path, str(tmp_path), {})
        assert ".py" in out
        assert ".txt" in out
        assert "5 total" in out

    def test_make_chat_handlers_real_stats(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("1\n2\n3\n4\n")
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["loc_stats"]({})
        assert ".py" in out
        assert "4 total" in out

    def test_subdirectory_scoping_still_works(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("1\n2\n")
        (tmp_path / "outside_sub.py").write_text("1\n2\n3\n")
        out = loc_stats_handler(tmp_path, str(tmp_path), {"directory": "sub"})
        assert "2 total" in out
