"""import_graph tool #95 — tool_enhance.md productionization pass
(2026-08-25).

The exact sibling tool to tool #83's parse_ast — same finding classes,
same underlying app.repo_tools.ast_engine module, same fix shape. Four
real implementations, all thin one-liners sharing the identical bug,
unified into one shared `import_graph_handler()` in
`app.tools.filesystem.import_graph`:

1. Worktree-boundary escape on all four — proved live, a request for a
   file outside the repo genuinely returned a real import list (module
   names and imported symbols).
2. An uncaught PermissionError on all four, same class as tools
   #70/#72/#76/#82/#83/#93 (single-file read, unlike tool #94's
   directory-walk shape which does NOT share this class).

`app.repo_tools.ast_engine.build_import_graph()` itself is untouched
and still does the real AST work — it's reused, not reinvented.

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
    make_chat_handlers,
    make_refactor_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.import_graph import IMPORT_GRAPH_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_import_graph_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_import_graph_tool_schema_requires_path() -> None:
    assert IMPORT_GRAPH_TOOL["name"] == "import_graph"
    assert IMPORT_GRAPH_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_import_graph_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("import_graph") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all four real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "import_graph_hardening_secret.py"
    outside.write_text("import os\nimport sys\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("import_graph", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "os" not in result.split("POLICY DENIED")[0]
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
    ],
)
def test_all_three_factories_reject_path_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"import_graph_hardening_secret_{factory_name}.py"
    outside.write_text("import os\nimport sys\n")
    try:
        handlers = factory(str(tmp_path))
        result = handlers["import_graph"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "import_graph", {"path": "../../../../../../etc/hostname"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 — uncaught PermissionError (all four real implementations)
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_parent_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    inner = restricted / "inner.py"
    inner.write_text("import os\n")
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
    result = await agent._execute_tool("import_graph", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


def test_make_chat_handlers_handles_permission_denied_gracefully(
    tmp_path: Path, restricted_parent_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["import_graph"]({"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_shows_real_import_graph(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "import os\nfrom collections import OrderedDict\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("import_graph", {"path": "target.py"})
    assert "os" in result
    assert "collections" in result
    assert "OrderedDict" in result


@pytest.mark.asyncio
async def test_chat_agent_missing_file_errors_cleanly(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("import_graph", {"path": "ghost.py"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_arch_reviewer_handlers, make_refactor_agent_handlers],
)
def test_all_three_factories_show_real_import_graph(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text("import os\nimport sys\n")
    handlers = factory(str(tmp_path))
    result = handlers["import_graph"]({"path": "target.py"})
    assert "os" in result
    assert "sys" in result
