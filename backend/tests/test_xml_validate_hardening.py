"""xml_validate tool #208 — tool_enhance.md productionization pass
(2026-09-16). Same shape as sibling tool #175 (read_notebook).

Two real, empirically-verified findings, on the one real
implementation (`xml_validate_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. Worktree-boundary escape — `root / path` was never validated.
   Proved live: a real out-of-worktree XML file's well-formedness (and
   parse-error detail, for malformed files) was disclosed.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as many prior tools) — every real interactive-chat call
   fell through to "[ERROR] Unknown tool".

Investigated and REFUTED, not treated as a finding: XXE (XML External
Entity) injection. Proved live against this project's real
xml.etree.ElementTree.parse() — does not expand external entities by
default.

Both real findings closed via a shared `xml_validate_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.xml_validate import XML_VALIDATE_TOOL, xml_validate_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_xml_validate_hardening", repo_path=repo)
    return ChatAgent(session)


def test_xml_validate_tool_schema() -> None:
    assert XML_VALIDATE_TOOL["name"] == "xml_validate"
    assert XML_VALIDATE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_xml_validate_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("xml_validate") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.xml"
    outside.write_text("<not><well_formed>")

    handlers = make_chat_handlers(str(repo))
    result = handlers["xml_validate"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_the_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.xml"
    outside.write_text("<root>ok</root>")

    agent = _agent(str(repo))
    result = await agent._execute_tool("xml_validate", {"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "secret.xml"
    outside.write_text("<root>ok</root>")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = xml_validate_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    (tmp_path / "good.xml").write_text("<root><child/></root>")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("xml_validate", {"path": "good.xml"})
    assert "Unknown tool" not in result
    assert "well-formed" in result


# ---------------------------------------------------------------------------
# Investigated and refuted — XXE
# ---------------------------------------------------------------------------


def test_xxe_entity_expansion_is_refuted(tmp_path: Path) -> None:
    """Not a real vulnerability on this project's real ElementTree/expat
    parser — external entities are not expanded by default. Kept as a
    regression guard, not a security fix."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET sk-12345")
    xxe = tmp_path / "xxe.xml"
    xxe.write_text(
        f'<?xml version="1.0"?>\n'
        f'<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file://{secret}"> ]>\n'
        f"<root>&xxe;</root>"
    )

    result = xml_validate_handler(tmp_path, str(tmp_path), {"path": "xxe.xml"})
    assert "TOP SECRET" not in result
    assert "[INVALID XML]" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_validates_a_real_well_formed_file(tmp_path: Path) -> None:
    (tmp_path / "good.xml").write_text("<root><child attr='x'/></root>")
    result = xml_validate_handler(tmp_path, str(tmp_path), {"path": "good.xml"})
    assert "✅" in result
    assert "well-formed" in result


def test_handler_reports_a_real_malformed_file(tmp_path: Path) -> None:
    (tmp_path / "bad.xml").write_text("<root><unclosed></root>")
    result = xml_validate_handler(tmp_path, str(tmp_path), {"path": "bad.xml"})
    assert "[INVALID XML]" in result


def test_handler_errors_cleanly_on_missing_file(tmp_path: Path) -> None:
    result = xml_validate_handler(tmp_path, str(tmp_path), {"path": "ghost.xml"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_validates_a_real_well_formed_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "good.xml").write_text("<root/>")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("xml_validate", {"path": "good.xml"})
    assert "✅" in result
