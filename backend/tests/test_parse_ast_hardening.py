"""parse_ast tool #83 — tool_enhance.md productionization pass
(2026-08-24).

Seven real implementations across 32 agents, all thin one-liners
sharing the identical bug, unified into one shared
`parse_ast_handler()` in `app.tools.filesystem.parse_ast`:

1. Worktree-boundary escape — proved live, a request for a file
   outside the repo genuinely returned a real structured AST dump
   (function names, args, decorators) through multiple real call
   sites.
2. An uncaught PermissionError — proved live with a real `chmod 000`
   parent directory.

`app.repo_tools.ast_engine.parse_file_ast()` itself is untouched and
still does the real AST parsing — it's reused, not reinvented, and is
also used by other out-of-scope tools (import_graph, call_graph, etc).

All tests here use real files/permissions on disk — nothing is mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_api_docs_agent_handlers,
    make_arch_reviewer_handlers,
    make_bug_fix_handlers,
    make_chat_handlers,
    make_readme_agent_handlers,
    make_refactor_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.parse_ast import PARSE_AST_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_parse_ast_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_parse_ast_tool_schema_requires_path() -> None:
    assert PARSE_AST_TOOL["name"] == "parse_ast"
    assert PARSE_AST_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_parse_ast_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("parse_ast") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all seven real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "parse_ast_hardening_secret.py"
    outside.write_text("def secret_function(a, b):\n    pass\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("parse_ast", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_function" not in result
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("bug_fix_agent", make_bug_fix_handlers),
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
        ("readme_agent", make_readme_agent_handlers),
        ("api_docs_agent", make_api_docs_agent_handlers),
    ],
)
def test_all_six_factories_reject_path_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"parse_ast_hardening_secret_{factory_name}.py"
    outside.write_text("def secret_function(a, b):\n    pass\n")
    try:
        handlers = factory(str(tmp_path))
        result = handlers["parse_ast"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
        assert "secret_function" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "parse_ast", {"path": "../../../../../../etc/hostname"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (all seven real implementations)
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_parent_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    inner = restricted / "inner.py"
    inner.write_text("def x():\n    pass\n")
    original_mode = restricted.stat().st_mode
    restricted.chmod(0)
    try:
        yield "restricted_dir/inner.py"
    finally:
        restricted.chmod(original_mode)


@pytest.mark.asyncio
async def test_chat_agent_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("parse_ast", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


def test_make_chat_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["parse_ast"]({"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all seven real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_parses_real_python_file(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def real_function(a, b):\n    pass\n\n\nclass RealClass:\n    pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("parse_ast", {"path": "target.py"})
    assert "real_function" in result
    assert "RealClass" in result


@pytest.mark.asyncio
async def test_chat_agent_missing_file_errors_cleanly(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("parse_ast", {"path": "ghost.py"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_non_python_file_errors_cleanly(tmp_path: Path) -> None:
    (tmp_path / "target.ts").write_text("function foo() {}\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("parse_ast", {"path": "target.ts"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_bug_fix_handlers,
        make_arch_reviewer_handlers,
        make_refactor_agent_handlers,
        make_readme_agent_handlers,
        make_api_docs_agent_handlers,
    ],
)
def test_all_six_factories_parse_real_python_file(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text("def real_function():\n    pass\n")
    handlers = factory(str(tmp_path))
    result = handlers["parse_ast"]({"path": "target.py"})
    assert "real_function" in result
