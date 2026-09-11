"""export_markdown tool #137 — tool_enhance.md productionization pass
(2026-09-11).

Two real, empirically-verified findings, on the one real
implementation (`export_markdown_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. Most severe: a worktree-boundary escape on both `path` and
   `output` — a genuine ARBITRARY FILE WRITE, not just a read. When
   `output` is omitted, the default is derived from `path`, so an
   absolute `path` alone (no malicious `output` needed) also writes
   outside the worktree. Proved live, in isolated `/tmp` directories:
   both an explicit absolute `output` and an absolute `path` with no
   `output` genuinely wrote a real file outside the intended worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".

Both are now closed via a shared `export_markdown_handler()` using
`check_path_in_worktree()` on both `path` and the resolved `output`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.export_markdown import (
    EXPORT_MARKDOWN_TOOL,
    export_markdown_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_export_markdown_hardening", repo_path=repo)
    return ChatAgent(session)


def test_export_markdown_tool_schema() -> None:
    assert EXPORT_MARKDOWN_TOOL["name"] == "export_markdown"
    assert EXPORT_MARKDOWN_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_export_markdown_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("export_markdown") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file WRITE
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_explicit_output_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "doc.md").write_text("# Hello\n")
    outside_target = tmp_path / "pwned.html"

    handlers = make_chat_handlers(str(repo))
    result = handlers["export_markdown"](
        {"path": "doc.md", "output": str(outside_target)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_target.exists()


def test_make_chat_handlers_closes_default_output_escape_via_absolute_path(
    tmp_path: Path,
) -> None:
    """The severe, live-proven case: no malicious `output` needed at
    all -- an absolute `path` alone escapes via the derived default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_md = tmp_path / "outside.md"
    outside_md.write_text("# Secret\n")
    expected_default_html = tmp_path / "outside.html"

    handlers = make_chat_handlers(str(repo))
    result = handlers["export_markdown"]({"path": str(outside_md)})
    assert "[POLICY DENIED]" in result
    assert not expected_default_html.exists()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "doc.md").write_text("# Hello\n")
    outside_target = tmp_path / "pwned.html"

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "export_markdown", {"path": "doc.md", "output": str(outside_target)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_target.exists()


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "doc.md").write_text("# Hello\n")
    outside_target = tmp_path / "pwned.html"

    result = export_markdown_handler(
        repo, str(repo), {"path": "doc.md", "output": str(outside_target)}
    )
    assert "[POLICY DENIED]" in result
    assert not outside_target.exists()


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Hello\n\nBody text.\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("export_markdown", {"path": "doc.md"})
    assert "Unknown tool" not in result
    assert result == "Exported to doc.html"
    assert (tmp_path / "doc.html").exists()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, with and without an explicit output
# ---------------------------------------------------------------------------


def test_handler_exports_with_default_output_name(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Title\n\nBody.\n")
    result = export_markdown_handler(tmp_path, str(tmp_path), {"path": "doc.md"})
    assert result == "Exported to doc.html"
    html = (tmp_path / "doc.html").read_text()
    assert "<h1>Title</h1>" in html
    assert "<p>Body.</p>" in html


def test_handler_exports_with_explicit_output_name(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Title\n")
    result = export_markdown_handler(
        tmp_path, str(tmp_path), {"path": "doc.md", "output": "custom.html"}
    )
    assert result == "Exported to custom.html"
    assert (tmp_path / "custom.html").exists()


def test_handler_errors_cleanly_on_missing_source(tmp_path: Path) -> None:
    result = export_markdown_handler(tmp_path, str(tmp_path), {"path": "ghost.md"})
    assert result.startswith("[ERROR]")


@pytest.mark.asyncio
async def test_chat_agent_dispatch_exports_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Title\n\nBody.\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "export_markdown", {"path": "doc.md", "output": "out.html"}
    )
    assert result == "Exported to out.html"
    assert (tmp_path / "out.html").exists()
