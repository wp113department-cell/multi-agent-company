"""list_functions tool #82 — tool_enhance.md productionization pass
(2026-08-24).

The widest consolidation in the low-risk tier so far: NINE real
implementations across 32 agents, all now delegating to one shared
`list_functions_handler()` in `app.tools.filesystem.list_functions`.

Four real, empirically-verified findings, all closed by the unified
handler:

1. Worktree-boundary escape + uncaught PermissionError on the two
   single-file implementations (`chat_agent.py`'s dispatch and
   `make_chat_handlers()`'s own `list_functions`) — same class as tool
   #76's `analyze_file`.
2. A field-name mismatch (`ar_list_functions`, `rf_list_functions`,
   `rm_list_functions`, `ad_list_functions` read `inp.get("file", "")`
   while the schema they actually advertise declares `path`) that made
   every real call silently ignore the requested path and grep the
   entire repo instead.
3. Worktree-boundary escape via relative `../` traversal in three
   rglob-based implementations (`pr_list_functions`,
   `sr_list_functions`, `td_list_functions`) — an absolute outside-repo
   path was only accidentally masked (a swallowed `ValueError` from
   `relative_to()`), not genuinely blocked; a traversal path defeated
   that accident entirely.
4. A design mismatch: seven agent-specific implementations diverged
   from the tool's own documented single-file contract by scanning an
   entire subtree instead.

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
    make_chat_handlers,
    make_performance_reviewer_handlers,
    make_readme_agent_handlers,
    make_refactor_agent_handlers,
    make_style_reviewer_handlers,
    make_tech_debt_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.list_functions import LIST_FUNCTIONS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_list_functions_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_list_functions_tool_schema_requires_path() -> None:
    assert LIST_FUNCTIONS_TOOL["name"] == "list_functions"
    assert LIST_FUNCTIONS_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_list_functions_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_functions") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree escape + uncaught PermissionError (single-file
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "list_functions_hardening_secret.py"
    outside.write_text("def secret_function():\n    pass\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("list_functions", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_function" not in result
    finally:
        outside.unlink()


def test_make_chat_handlers_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "list_functions_hardening_secret2.py"
    outside.write_text("def secret_function():\n    pass\n")
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["list_functions"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "secret_function" not in result
    finally:
        outside.unlink()


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
    result = await agent._execute_tool(
        "list_functions", {"path": restricted_parent_dir}
    )
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Finding #2 — field-name mismatch (ar_/rf_/rm_/ad_)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
        ("readme_agent", make_readme_agent_handlers),
        ("api_docs_agent", make_api_docs_agent_handlers),
    ],
)
def test_field_name_mismatch_factories_now_respect_requested_path(
    tmp_path: Path, factory_name: str, factory
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.py").write_text(
        "def real_target_function():\n    pass\n"
    )
    (tmp_path / "unrelated.py").write_text("def unrelated_function():\n    pass\n")

    handlers = factory(str(tmp_path))
    result = handlers["list_functions"]({"path": "src/target.py"})
    assert (
        "real_target_function" in result
    ), f"{factory_name}: expected function missing"
    assert (
        "unrelated_function" not in result
    ), f"{factory_name}: path scoping still broken — leaked unrelated.py's contents"


# ---------------------------------------------------------------------------
# Finding #3 — worktree escape via relative traversal (pr_/sr_/td_)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("performance_reviewer", make_performance_reviewer_handlers),
        ("style_reviewer", make_style_reviewer_handlers),
        ("tech_debt_agent", make_tech_debt_agent_handlers),
    ],
)
def test_rglob_factories_reject_relative_traversal_escape(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / "list_functions_hardening_traversal.py"
    outside.write_text("def secret_traversal_function():\n    pass\n")
    try:
        depth = len(tmp_path.parts) - 1
        traversal = "../" * (depth + 2) + str(outside).lstrip("/")
        handlers = factory(str(tmp_path))
        result = handlers["list_functions"]({"path": traversal})
        assert (
            "secret_traversal_function" not in result
        ), f"{factory_name}: relative-traversal worktree escape still works"
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all nine real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_finds_real_python_functions(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def real_function():\n    pass\n\n\nasync def async_function():\n    pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_functions", {"path": "target.py"})
    assert "real_function" in result
    assert "async_function" in result


@pytest.mark.asyncio
async def test_chat_agent_finds_real_ts_functions(tmp_path: Path) -> None:
    (tmp_path / "target.ts").write_text(
        "export function realExported() {}\nconst realArrow = () => {};\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_functions", {"path": "target.ts"})
    assert "realExported" in result
    assert "realArrow" in result


@pytest.mark.asyncio
async def test_chat_agent_missing_file_errors_cleanly(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_functions", {"path": "ghost.py"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_arch_reviewer_handlers,
        make_refactor_agent_handlers,
        make_readme_agent_handlers,
        make_api_docs_agent_handlers,
        make_performance_reviewer_handlers,
        make_style_reviewer_handlers,
        make_tech_debt_agent_handlers,
    ],
)
def test_all_nine_factories_find_real_python_function(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text("def real_function():\n    pass\n")
    handlers = factory(str(tmp_path))
    result = handlers["list_functions"]({"path": "target.py"})
    assert "real_function" in result
