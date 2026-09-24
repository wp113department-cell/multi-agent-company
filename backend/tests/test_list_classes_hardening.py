"""list_classes tool #87 — tool_enhance.md productionization pass
(2026-08-24).

The exact sibling tool to tool #82's `list_functions`, sharing the
identical bug shapes across seven real implementations, all now
delegating to one shared `list_classes_handler()` in
`app.tools.filesystem.list_classes`:

1. Worktree-boundary escape + uncaught PermissionError on the two
   single-file implementations (`chat_agent.py`'s dispatch,
   `make_chat_handlers()`'s own closure).
2. A field-name mismatch (`ar_list_classes`/`rf_list_classes`/
   `rm_list_classes` read `inp.get("file", "")` while the schema
   declares `path`) that made every real call silently ignore the
   requested path and grep the entire repo instead.
3. Worktree escape via relative `../` traversal in two rglob-based
   implementations (`sr_list_classes`, `td_list_classes`) — an
   absolute-path escape was only accidentally masked by a swallowed
   ValueError from relative_to(), not genuinely blocked.

All tests here use real files on disk — nothing is mocked.
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
    make_readme_agent_handlers,
    make_refactor_agent_handlers,
    make_style_reviewer_handlers,
    make_tech_debt_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.list_classes import LIST_CLASSES_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_list_classes_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_list_classes_tool_schema_requires_path() -> None:
    assert LIST_CLASSES_TOOL["name"] == "list_classes"
    assert LIST_CLASSES_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_list_classes_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_classes") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree escape + uncaught PermissionError (single-file
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "list_classes_hardening_secret.py"
    outside.write_text("class SecretClass:\n    pass\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("list_classes", {"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "SecretClass" not in result
    finally:
        outside.unlink()


def test_make_chat_handlers_rejects_path_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "list_classes_hardening_secret2.py"
    outside.write_text("class SecretClass:\n    pass\n")
    try:
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["list_classes"]({"path": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "SecretClass" not in result
    finally:
        outside.unlink()


@pytest.fixture
def restricted_parent_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    inner = restricted / "inner.py"
    inner.write_text("class X:\n    pass\n")
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
    result = await agent._execute_tool("list_classes", {"path": restricted_parent_dir})
    assert result.startswith("[ERROR]")  # must not raise


# ---------------------------------------------------------------------------
# Finding #2 — field-name mismatch (ar_/rf_/rm_)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("refactor_agent", make_refactor_agent_handlers),
        ("readme_agent", make_readme_agent_handlers),
    ],
)
def test_field_name_mismatch_factories_now_respect_requested_path(
    tmp_path: Path, factory_name: str, factory
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.py").write_text("class RealTargetClass:\n    pass\n")
    (tmp_path / "unrelated.py").write_text("class UnrelatedClass:\n    pass\n")

    handlers = factory(str(tmp_path))
    result = handlers["list_classes"]({"path": "src/target.py"})
    assert "RealTargetClass" in result, f"{factory_name}: expected class missing"
    assert (
        "UnrelatedClass" not in result
    ), f"{factory_name}: path scoping still broken — leaked unrelated.py's contents"


# ---------------------------------------------------------------------------
# Finding #3 — worktree escape via relative traversal (sr_/td_)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("style_reviewer", make_style_reviewer_handlers),
        ("tech_debt_agent", make_tech_debt_agent_handlers),
    ],
)
def test_rglob_factories_reject_relative_traversal_escape(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / "list_classes_hardening_traversal.py"
    outside.write_text("class SecretTraversalClass:\n    pass\n")
    try:
        depth = len(tmp_path.parts) - 1
        traversal = "../" * (depth + 2) + str(outside).lstrip("/")
        handlers = factory(str(tmp_path))
        result = handlers["list_classes"]({"path": traversal})
        assert (
            "SecretTraversalClass" not in result
        ), f"{factory_name}: relative-traversal worktree escape still works"
    finally:
        outside.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all seven real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_finds_real_class_with_methods(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "class RealClass:\n    def real_method(self):\n        pass\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_classes", {"path": "target.py"})
    assert "RealClass" in result
    assert "real_method" in result


@pytest.mark.asyncio
async def test_chat_agent_missing_file_errors_cleanly(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_classes", {"path": "ghost.py"})
    assert "[ERROR]" in result


@pytest.mark.parametrize(
    "factory",
    [
        make_chat_handlers,
        make_arch_reviewer_handlers,
        make_refactor_agent_handlers,
        make_readme_agent_handlers,
        make_style_reviewer_handlers,
        make_tech_debt_agent_handlers,
    ],
)
def test_all_six_factories_find_real_class(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text("class RealClass:\n    pass\n")
    handlers = factory(str(tmp_path))
    result = handlers["list_classes"]({"path": "target.py"})
    assert "RealClass" in result
