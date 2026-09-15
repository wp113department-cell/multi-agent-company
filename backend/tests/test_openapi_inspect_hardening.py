"""openapi_inspect tool #169 — tool_enhance.md productionization
pass (2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`openapi_inspect_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle. `root/path` was never validated. Proved live:
   real title, API version, endpoint paths, HTTP methods, and
   operation summaries of a file outside the worktree were genuinely
   disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `openapi_inspect_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.openapi_inspect import (
    OPENAPI_INSPECT_TOOL,
    openapi_inspect_handler,
)

SECRET_SPEC = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Secret Internal API", "version": "9.9.9"},
        "paths": {
            "/internal/secret": {
                "get": {"summary": "secret endpoint", "parameters": []}
            }
        },
    }
)

PUBLIC_SPEC = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Public API", "version": "1.0"},
        "paths": {"/widgets": {"get": {"summary": "list widgets", "parameters": []}}},
    }
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_openapi_inspect_hardening", repo_path=repo)
    return ChatAgent(session)


def test_openapi_inspect_tool_schema() -> None:
    assert OPENAPI_INSPECT_TOOL["name"] == "openapi_inspect"
    assert OPENAPI_INSPECT_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_openapi_inspect_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("openapi_inspect") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape structured content disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text(SECRET_SPEC)

        out = openapi_inspect_handler(
            worktree, str(worktree), {"path": str(outside / "secret.json")}
        )
        assert "POLICY DENIED" in out
        assert "Secret Internal API" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.json").write_text(SECRET_SPEC)

        out = openapi_inspect_handler(
            worktree, str(worktree), {"path": "../secret.json"}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text(SECRET_SPEC)

        handlers = make_chat_handlers(str(worktree))
        out = handlers["openapi_inspect"]({"path": str(outside / "secret.json")})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text(SECRET_SPEC)

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "openapi_inspect", {"path": str(outside / "secret.json")}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "spec.json").write_text(PUBLIC_SPEC)
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("openapi_inspect", {"path": "spec.json"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Public API" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree spec, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_spec(self, tmp_path: Path) -> None:
        (tmp_path / "spec.json").write_text(PUBLIC_SPEC)
        out = openapi_inspect_handler(tmp_path, str(tmp_path), {"path": "spec.json"})
        assert "Public API" in out
        assert "GET" in out and "/widgets" in out

    def test_make_chat_handlers_real_spec(self, tmp_path: Path) -> None:
        (tmp_path / "spec.json").write_text(PUBLIC_SPEC)
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["openapi_inspect"]({"path": "spec.json"})
        assert "Public API" in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = openapi_inspect_handler(tmp_path, str(tmp_path), {"path": "nope.json"})
        assert "[ERROR] File not found" in out

    def test_non_openapi_file_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "notaspec.json").write_text('{"foo": "bar"}')
        out = openapi_inspect_handler(
            tmp_path, str(tmp_path), {"path": "notaspec.json"}
        )
        assert "[ERROR]" in out
