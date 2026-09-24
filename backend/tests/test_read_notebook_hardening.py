"""read_notebook tool #175 — tool_enhance.md productionization pass
(2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`read_notebook_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine STRUCTURED FILE CONTENT
   DISCLOSURE oracle. `root/path` was never validated. Proved live:
   real code-cell source (including a hardcoded secret-shaped string)
   and markdown-cell content of a notebook outside the worktree were
   genuinely disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `read_notebook_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.read_notebook import (
    READ_NOTEBOOK_TOOL,
    read_notebook_handler,
)

SECRET_NOTEBOOK = json.dumps(
    {
        "cells": [
            {
                "cell_type": "code",
                "source": ["API_KEY = 'sk-supersecretinnotebook1234567890'\n"],
                "outputs": [],
            },
            {
                "cell_type": "markdown",
                "source": ["# Internal admin credentials\n"],
                "outputs": [],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
)

PUBLIC_NOTEBOOK = json.dumps(
    {
        "cells": [
            {"cell_type": "markdown", "source": ["# Hello World\n"], "outputs": []},
            {
                "cell_type": "code",
                "source": ["print('hi')\n"],
                "outputs": [
                    {"output_type": "stream", "text": ["hi\n"]},
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_notebook_hardening", repo_path=repo)
    return ChatAgent(session)


def test_read_notebook_tool_schema() -> None:
    assert READ_NOTEBOOK_TOOL["name"] == "read_notebook"
    assert READ_NOTEBOOK_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_notebook_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_notebook") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape structured content disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_absolute_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.ipynb").write_text(SECRET_NOTEBOOK)

        out = read_notebook_handler(
            worktree, str(worktree), {"path": str(outside / "secret.ipynb")}
        )
        assert "POLICY DENIED" in out
        assert "sk-supersecret" not in out
        assert "admin credentials" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.ipynb").write_text(SECRET_NOTEBOOK)

        out = read_notebook_handler(
            worktree, str(worktree), {"path": "../secret.ipynb"}
        )
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.ipynb").write_text(SECRET_NOTEBOOK)

        handlers = make_chat_handlers(str(worktree))
        out = handlers["read_notebook"]({"path": str(outside / "secret.ipynb")})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.ipynb").write_text(SECRET_NOTEBOOK)

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "read_notebook", {"path": str(outside / "secret.ipynb")}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "nb.ipynb").write_text(PUBLIC_NOTEBOOK)
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("read_notebook", {"path": "nb.ipynb"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Hello World" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree notebook, both paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_notebook(self, tmp_path: Path) -> None:
        (tmp_path / "nb.ipynb").write_text(PUBLIC_NOTEBOOK)
        out = read_notebook_handler(tmp_path, str(tmp_path), {"path": "nb.ipynb"})
        assert "Hello World" in out
        assert "[output] hi" in out

    def test_make_chat_handlers_real_notebook(self, tmp_path: Path) -> None:
        (tmp_path / "nb.ipynb").write_text(PUBLIC_NOTEBOOK)
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_notebook"]({"path": "nb.ipynb"})
        assert "Hello World" in out

    def test_missing_file_error(self, tmp_path: Path) -> None:
        out = read_notebook_handler(tmp_path, str(tmp_path), {"path": "nope.ipynb"})
        assert "[ERROR]" in out

    def test_invalid_json_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.ipynb").write_text("{not valid json")
        out = read_notebook_handler(tmp_path, str(tmp_path), {"path": "bad.ipynb"})
        assert "[ERROR]" in out

    def test_max_cells_truncation(self, tmp_path: Path) -> None:
        cells = [
            {"cell_type": "code", "source": [f"x = {i}\n"], "outputs": []}
            for i in range(5)
        ]
        (tmp_path / "many.ipynb").write_text(
            json.dumps(
                {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
            )
        )
        out = read_notebook_handler(
            tmp_path, str(tmp_path), {"path": "many.ipynb", "max_cells": 2}
        )
        assert "Cell 0" in out
        assert "Cell 1" in out
        assert "Cell 2" not in out
        assert "3 additional cell(s) not shown" in out
