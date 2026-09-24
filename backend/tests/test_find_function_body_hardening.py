"""find_function_body tool #111 — tool_enhance.md productionization
pass (2026-08-26).

Two real, empirically-verified findings:

1. A real, severe functionality bug: `bf_find_function_body` and
   `rf_find_function_body` both read `inp["name"]` — but the schema
   declares the field as `function_name` — a 100% KeyError crash rate
   on every real, schema-conformant call. They also completely ignored
   `path` and never actually extracted a function body (just raw grep
   match lines).
2. Worktree-boundary escape on the two already-correct
   implementations — proved live, a request for a file outside the
   repo genuinely returned the complete source of a real function from
   that outside file.

Fixed via a shared `find_function_body_handler()` — `check_path_in_
worktree()` closes finding #2; `bf_`/`rf_find_function_body` fully
replaced by the shared, correct handler, closing finding #1.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_bug_fix_handlers,
    make_chat_handlers,
    make_refactor_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_function_body import FIND_FUNCTION_BODY_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(
        session_id="td_find_function_body_hardening", repo_path=str(repo)
    )
    return ChatAgent(session)


def test_find_function_body_tool_schema() -> None:
    assert FIND_FUNCTION_BODY_TOOL["name"] == "find_function_body"
    assert FIND_FUNCTION_BODY_TOOL["input_schema"]["required"] == ["path", "function_name"]  # type: ignore[index]


def test_find_function_body_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_function_body") == 1


# ---------------------------------------------------------------------------
# Finding #1 — bf_/rf_ read a nonexistent `name` field (real crash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("bug_fix", make_bug_fix_handlers),
        ("refactor", make_refactor_agent_handlers),
    ],
)
def test_previously_crashing_factories_now_work(
    tmp_path: Path, factory_name: str, factory
) -> None:
    (tmp_path / "fb.py").write_text(
        "def helper():\n    x = 1\n    return x\n\ndef main():\n    pass\n"
    )
    handlers = factory(str(tmp_path))
    # Previously: str(inp["name"]) raised KeyError on every real,
    # schema-conformant call (the schema only ever provides
    # "function_name"). Must not raise now.
    result = handlers["find_function_body"](
        {"path": "fb.py", "function_name": "helper"}
    )
    assert "def helper" in result, f"{factory_name} did not extract the real body"
    assert "return x" in result
    assert "def main" not in result


# ---------------------------------------------------------------------------
# Finding #2 — worktree-boundary escape (the two already-correct
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "find_function_body_hardening_secret.py"
    outside.write_text(
        "def leaked_secret_function():\n    return 'TOP_SECRET_abc123'\n"
    )
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "find_function_body",
            {"path": str(outside), "function_name": "leaked_secret_function"},
        )
        assert "[POLICY DENIED]" in result
        assert "TOP_SECRET" not in result
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("bug_fix", make_bug_fix_handlers),
        ("refactor", make_refactor_agent_handlers),
    ],
)
def test_all_three_factories_reject_path_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"find_function_body_hardening_secret_{factory_name}.py"
    outside.write_text(
        "def leaked_secret_function():\n    return 'TOP_SECRET_abc123'\n"
    )
    try:
        handlers = factory(str(tmp_path))
        result = handlers["find_function_body"](
            {"path": str(outside), "function_name": "leaked_secret_function"}
        )
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
        assert "TOP_SECRET" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_function_body",
        {"path": "../../../../../../etc/hostname", "function_name": "x"},
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all four real
# access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_extracts_real_function(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def helper():\n    x = 1\n    return x\n\ndef main():\n    pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_function_body", {"path": "target.py", "function_name": "helper"}
    )
    assert "def helper" in result
    assert "return x" in result
    assert "def main" not in result


@pytest.mark.asyncio
async def test_chat_agent_missing_function_errors_cleanly(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("x = 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_function_body", {"path": "target.py", "function_name": "ghost"}
    )
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_bug_fix_handlers, make_refactor_agent_handlers],
)
def test_all_three_factories_extract_real_function(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text("async def fetch_data():\n    return 42\n")
    handlers = factory(str(tmp_path))
    result = handlers["find_function_body"](
        {"path": "target.py", "function_name": "fetch_data"}
    )
    assert "async def fetch_data" in result
    assert "return 42" in result
