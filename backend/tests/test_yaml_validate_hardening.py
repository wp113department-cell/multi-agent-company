"""yaml_validate tool #120 — tool_enhance.md productionization pass
(2026-08-26).

Two real, empirically-verified findings, on the one real
implementation (`yaml_validate_h` inside `make_chat_handlers`, plus
`app/agents/chat_agent.py`'s dispatch, which never existed until this
turn):

1. A worktree-boundary escape that is a genuine ARBITRARY FILE READ,
   on both `path` and `schema_path` — `root / ...` was never validated
   for either field.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools #100/#103/#110/#112/#118) — every real
   interactive-chat call fell through to "[ERROR] Unknown tool".

Both are now closed via a shared `yaml_validate_handler()` using
`check_path_in_worktree()` on both fields, used by both real access
paths (`make_chat_handlers` and the new `chat_agent.py` dispatch).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.yaml_validate import YAML_VALIDATE_TOOL, yaml_validate_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_yaml_validate_hardening", repo_path=repo)
    return ChatAgent(session)


def test_yaml_validate_tool_schema() -> None:
    assert YAML_VALIDATE_TOOL["name"] == "yaml_validate"
    assert YAML_VALIDATE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_yaml_validate_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("yaml_validate") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file read (path + schema_path)
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")

    handlers = make_chat_handlers(str(repo))
    result = handlers["yaml_validate"]({"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_make_chat_handlers_closes_schema_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    good = repo / "good.yaml"
    good.write_text("key: value\n")
    outside_schema = tmp_path / "outside_schema.json"
    outside_schema.write_text('{"type": "object"}')

    handlers = make_chat_handlers(str(repo))
    result = handlers["yaml_validate"](
        {"path": "good.yaml", "schema_path": str(outside_schema)}
    )
    assert "policy denied" in result.lower()


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")

    agent = _agent(str(repo))
    result = await agent._execute_tool("yaml_validate", {"path": str(outside)})
    assert "[POLICY DENIED]" in result


def test_handler_closes_path_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text("SECRET_OUTSIDE_WORKTREE\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = yaml_validate_handler(repo, str(repo), {"path": str(outside)})
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path: Path) -> None:
    target = tmp_path / "good.yaml"
    target.write_text("key: value\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("yaml_validate", {"path": "good.yaml"})
    assert "Unknown tool" not in result
    assert "valid YAML" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, including real schema validation
# ---------------------------------------------------------------------------


def test_handler_validates_a_real_yaml_file(tmp_path: Path) -> None:
    target = tmp_path / "good.yaml"
    target.write_text("key: value\n")
    result = yaml_validate_handler(tmp_path, str(tmp_path), {"path": "good.yaml"})
    assert result == "✅ good.yaml is valid YAML"


def test_handler_reports_invalid_yaml(tmp_path: Path) -> None:
    target = tmp_path / "bad.yaml"
    target.write_text("key: [unterminated\n")
    result = yaml_validate_handler(tmp_path, str(tmp_path), {"path": "bad.yaml"})
    assert "[INVALID YAML]" in result


def test_handler_validates_against_a_real_schema(tmp_path: Path) -> None:
    target = tmp_path / "good.yaml"
    target.write_text("key: value\n")
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}'
    )
    result = yaml_validate_handler(
        tmp_path, str(tmp_path), {"path": "good.yaml", "schema_path": "schema.json"}
    )
    assert "matches schema" in result


def test_handler_reports_schema_violation(tmp_path: Path) -> None:
    target = tmp_path / "bad.yaml"
    target.write_text("key: 123\n")
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}'
    )
    result = yaml_validate_handler(
        tmp_path, str(tmp_path), {"path": "bad.yaml", "schema_path": "schema.json"}
    )
    assert "[SCHEMA VIOLATION]" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_validates_a_real_yaml_file(tmp_path: Path) -> None:
    target = tmp_path / "good.yaml"
    target.write_text("key: value\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("yaml_validate", {"path": "good.yaml"})
    assert result == "✅ good.yaml is valid YAML"
