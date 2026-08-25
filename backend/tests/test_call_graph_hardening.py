"""call_graph tool #93 — tool_enhance.md productionization pass
(2026-08-25).

The exact sibling tool to tool #83's parse_ast — same finding classes,
same underlying app.repo_tools.ast_engine module, same fix shape.
Five real implementations, all thin one-liners sharing the identical
bug, unified into one shared `call_graph_handler()` in
`app.tools.filesystem.call_graph`:

1. Worktree-boundary escape on all five — proved live, a request for a
   file outside the repo genuinely returned a real call graph (caller
   names, line numbers, and every function each one calls).
2. An uncaught PermissionError on all five, same class as tools
   #70/#72/#76/#82/#83.

`app.repo_tools.ast_engine.build_call_graph()` itself is untouched and
still does the real AST work — it's reused, not reinvented, and
`get_call_edges()` is also used by another out-of-scope tool
(`generate_diagram_h`).

All tests here use real files/permissions on disk — nothing is mocked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_arch_reviewer_handlers,
    make_bug_fix_handlers,
    make_chat_handlers,
    make_refactor_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.call_graph import CALL_GRAPH_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_call_graph_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_call_graph_tool_schema_requires_path() -> None:
    assert CALL_GRAPH_TOOL["name"] == "call_graph"
    assert CALL_GRAPH_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_call_graph_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("call_graph") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all five real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "call_graph_hardening_secret.py"
    outside.write_text("def secret_caller():\n    secret_helper()\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("call_graph", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_caller" not in result
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("bug_fix_agent", make_bug_fix_handlers),
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
    ],
)
def test_all_four_factories_reject_path_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"call_graph_hardening_secret_{factory_name}.py"
    outside.write_text("def secret_caller():\n    secret_helper()\n")
    try:
        handlers = factory(str(tmp_path))
        result = handlers["call_graph"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
        assert "secret_caller" not in result
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "call_graph", {"path": "../../../../../../etc/hostname"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (all five real implementations)
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
    result = await agent._execute_tool("call_graph", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


def test_make_chat_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["call_graph"]({"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all five real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_shows_real_call_graph(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def real_caller():\n    real_helper()\n\n\ndef real_helper():\n    pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("call_graph", {"path": "target.py"})
    assert "real_caller" in result
    assert "real_helper" in result


@pytest.mark.asyncio
async def test_chat_agent_filters_by_function_name(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def caller_a():\n    helper_a()\n\n\ndef caller_b():\n    helper_b()\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "call_graph", {"path": "target.py", "function_name": "caller_a"}
    )
    assert "caller_a" in result
    assert "helper_a" in result
    assert "caller_b" not in result


@pytest.mark.asyncio
async def test_chat_agent_missing_file_errors_cleanly(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("call_graph", {"path": "ghost.py"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_bug_fix_handlers,
        make_arch_reviewer_handlers,
        make_refactor_agent_handlers,
    ],
)
def test_all_four_factories_show_real_call_graph(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text(
        "def real_caller():\n    real_helper()\n\n\ndef real_helper():\n    pass\n"
    )
    handlers = factory(str(tmp_path))
    result = handlers["call_graph"]({"path": "target.py"})
    assert "real_caller" in result
    assert "real_helper" in result
