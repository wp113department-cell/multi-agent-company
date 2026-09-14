"""generate_api_docs_text tool #144 — tool_enhance.md
productionization pass (2026-09-14).

Two real, empirically-verified findings, on the one real
implementation (`generate_api_docs_text_h` inside `make_chat_handlers`,
plus `app/agents/chat_agent.py`'s dispatch, which never existed until
this turn):

1. A worktree-boundary escape that is a genuine ROUTE/FUNCTION-NAME
   disclosure oracle — `root / route_path` was never validated.
   Proved live: a real route decorator's path AND the handler
   function's name were genuinely disclosed from a file outside the
   intended worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `generate_api_docs_text_handler()`
using `check_path_in_worktree()` on `route_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.generate_api_docs_text import (
    GENERATE_API_DOCS_TEXT_TOOL,
    generate_api_docs_text_handler,
)

ROUTE_FILE = '@app.get("/users/{id}")\ndef get_user(id: int):\n    pass\n'


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(
        session_id="td_generate_api_docs_text_hardening", repo_path=repo
    )
    return ChatAgent(session)


def test_generate_api_docs_text_tool_schema() -> None:
    assert GENERATE_API_DOCS_TEXT_TOOL["name"] == "generate_api_docs_text"
    assert GENERATE_API_DOCS_TEXT_TOOL["input_schema"]["required"] == ["route_path"]  # type: ignore[index]


def test_generate_api_docs_text_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("generate_api_docs_text") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape route/function-name disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(
        '@app.get("/secret/internal-admin-endpoint")\n'
        "def secret_admin_handler():\n    pass\n"
    )

    handlers = make_chat_handlers(str(repo))
    result = handlers["generate_api_docs_text"]({"route_path": str(outside)})
    assert "[POLICY DENIED]" in result
    assert "secret_admin_handler" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(
        '@app.get("/secret/internal-admin-endpoint")\n'
        "def secret_admin_handler():\n    pass\n"
    )

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "generate_api_docs_text", {"route_path": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert "secret_admin_handler" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text(
        '@app.get("/secret")\ndef secret_handler():\n    pass\n'
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    result = generate_api_docs_text_handler(
        repo, str(repo), {"route_path": str(outside)}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "routes.py").write_text(ROUTE_FILE)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "generate_api_docs_text", {"route_path": "routes.py"}
    )
    assert "Unknown tool" not in result
    assert "get_user" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_extracts_a_real_endpoint(tmp_path: Path) -> None:
    (tmp_path / "routes.py").write_text(ROUTE_FILE)
    result = generate_api_docs_text_handler(
        tmp_path, str(tmp_path), {"route_path": "routes.py"}
    )
    assert "### GET /users/{id}" in result
    assert "**Function:** `get_user`" in result


def test_handler_reports_no_routes_found(tmp_path: Path) -> None:
    (tmp_path / "plain.py").write_text("x = 1\n")
    result = generate_api_docs_text_handler(
        tmp_path, str(tmp_path), {"route_path": "plain.py"}
    )
    assert result == "(no FastAPI route decorators found)"


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = generate_api_docs_text_handler(
        tmp_path, str(tmp_path), {"route_path": "ghost.py"}
    )
    assert result == "[ERROR] File not found: ghost.py"


def test_handler_extracts_multiple_endpoints(tmp_path: Path) -> None:
    (tmp_path / "routes.py").write_text(
        '@app.get("/a")\ndef get_a():\n    pass\n\n'
        '@app.post("/b")\ndef post_b():\n    pass\n'
    )
    result = generate_api_docs_text_handler(
        tmp_path, str(tmp_path), {"route_path": "routes.py"}
    )
    assert "### GET /a" in result
    assert "### POST /b" in result
    assert "`get_a`" in result
    assert "`post_b`" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_extracts_a_real_endpoint(tmp_path: Path) -> None:
    (tmp_path / "routes.py").write_text(ROUTE_FILE)
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "generate_api_docs_text", {"route_path": "routes.py"}
    )
    assert "### GET /users/{id}" in result
