"""json_validate tool #159 — tool_enhance.md productionization pass
(2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`json_validate_h` inside `make_chat_handlers`) — the
identical bug class already found and fixed for sibling tool #120's
`yaml_validate`, explicitly deferred to this tool's own turn.

1. Worktree-boundary escape — a genuine ARBITRARY FILE READ, on both
   `path` and `schema_path`. `root/path` (and, via the old
   `_load_schema_doc`, `root/schema_path`) was never validated. Proved
   live: a deliberately malformed file outside the worktree was
   genuinely parsed, confirmed via a parse-position-derived error
   message unique to that file's real content.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Both are now closed via a shared `json_validate_handler()`, reusing
the same worktree-validated `load_schema_doc`/`validate_against_schema`
helpers already proven correct for `yaml_validate` (now extracted to
app/tools/filesystem/json_schema_validation.py so both tools share
one implementation instead of two independent copies).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.json_validate import JSON_VALIDATE_TOOL, json_validate_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_json_validate_hardening", repo_path=repo)
    return ChatAgent(session)


def test_json_validate_tool_schema() -> None:
    assert JSON_VALIDATE_TOOL["name"] == "json_validate"
    assert JSON_VALIDATE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_json_validate_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("json_validate") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape arbitrary file read (path and schema_path)
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_path_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        broken = outside / "broken.json"
        broken.write_text('{"SECRET_TOKEN": "abc123xyz"\n')

        out = json_validate_handler(worktree, str(worktree), {"path": str(broken)})
        assert "POLICY DENIED" in out
        assert "abc123xyz" not in out

    def test_direct_handler_schema_path_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "data.json").write_text('{"name": "widget"}\n')
        outside = tmp_path / "outside"
        outside.mkdir()
        secret_schema = outside / "secret_schema.json"
        secret_schema.write_text('{"SECRET": "leak"}\n')

        out = json_validate_handler(
            worktree,
            str(worktree),
            {"path": "data.json", "schema_path": str(secret_schema)},
        )
        assert "ERROR" in out
        assert "policy denied" in out.lower()
        assert "leak" not in out

    def test_relative_traversal_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / "secret.json").write_text('{"k": "v"}\n')

        out = json_validate_handler(worktree, str(worktree), {"path": "../secret.json"})
        assert "POLICY DENIED" in out

    def test_make_chat_handlers_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        broken = outside / "broken.json"
        broken.write_text('{"bad": \n')

        handlers = make_chat_handlers(str(worktree))
        out = handlers["json_validate"]({"path": str(broken)})
        assert "POLICY DENIED" in out

    def test_chat_agent_dispatch_escape_blocked(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        broken = outside / "broken.json"
        broken.write_text('{"bad": \n')

        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool("json_validate", {"path": str(broken)})

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"count": 42}\n')
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("json_validate", {"path": "data.json"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "valid JSON" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree files, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_valid_json(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        out = json_validate_handler(tmp_path, str(tmp_path), {"path": "data.json"})
        assert out == "✅ data.json is valid JSON"

    def test_direct_handler_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text('{"name": \n')
        out = json_validate_handler(tmp_path, str(tmp_path), {"path": "bad.json"})
        assert "[INVALID JSON]" in out

    def test_direct_handler_schema_match(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        (tmp_path / "schema.json").write_text(
            '{"type": "object", "required": ["name"]}\n'
        )
        out = json_validate_handler(
            tmp_path, str(tmp_path), {"path": "data.json", "schema_path": "schema.json"}
        )
        assert "matches schema" in out

    def test_direct_handler_schema_violation(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"other": "field"}\n')
        (tmp_path / "schema.json").write_text(
            '{"type": "object", "required": ["name"]}\n'
        )
        out = json_validate_handler(
            tmp_path, str(tmp_path), {"path": "data.json", "schema_path": "schema.json"}
        )
        assert "[SCHEMA VIOLATION]" in out

    def test_make_chat_handlers_valid_json(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"a": 1}\n')
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["json_validate"]({"path": "data.json"})
        assert "valid JSON" in out

    def test_yaml_schema_still_supported_for_json_document(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "data.json").write_text('{"name": "widget"}\n')
        (tmp_path / "schema.yaml").write_text("type: object\nrequired: [name]\n")
        out = json_validate_handler(
            tmp_path, str(tmp_path), {"path": "data.json", "schema_path": "schema.yaml"}
        )
        assert "matches schema" in out
