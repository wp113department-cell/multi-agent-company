"""circular_dep_detect tool #97 — tool_enhance.md productionization
pass (2026-08-25).

The exact sibling tool to tool #94's dead_code_detect — same finding
classes, same underlying app.repo_tools.ast_engine module, same
directory-rglob-walk shape. Three real implementations, all thin
one-liners sharing the identical bug, unified into one shared
`circular_dep_detect_handler()` in
`app.tools.filesystem.circular_dep_detect`:

1. Worktree-boundary escape on all three — proved live, a request for
   a directory outside the repo containing a real circular-import pair
   genuinely returned a real, correctly-detected cycle report.
2. Checked for the sibling class established by tool #94 (an uncaught
   PermissionError does NOT reproduce for this directory-rglob shape,
   unlike tools #83/#93's single-file-read shape) — confirmed it
   reproduces here too: pathlib's rglob() silently swallows
   PermissionError during traversal.

`app.repo_tools.ast_engine.detect_circular_imports()` itself is
untouched and still does the real cycle-detection work — it's reused,
not reinvented.

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
)
from app.models.chat import ChatSession
from app.tools.filesystem.circular_dep_detect import CIRCULAR_DEP_DETECT_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_circular_dep_detect_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_circular_dep_detect_tool_schema() -> None:
    assert CIRCULAR_DEP_DETECT_TOOL["name"] == "circular_dep_detect"
    assert CIRCULAR_DEP_DETECT_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_circular_dep_detect_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("circular_dep_detect") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all three real implementations)
# ---------------------------------------------------------------------------


def _plant_real_cycle(directory: Path) -> None:
    pkg = directory / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "a.py").write_text("import app.b\n")
    (pkg / "b.py").write_text("import app.a\n")


@pytest.mark.asyncio
async def test_chat_agent_rejects_directory_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "circular_dep_hardening_outside"
    outside.mkdir(exist_ok=True)
    _plant_real_cycle(outside)
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("circular_dep_detect", {"directory": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "app.a" not in result
    finally:
        (outside / "app" / "a.py").unlink()
        (outside / "app" / "b.py").unlink()
        (outside / "app").rmdir()
        outside.rmdir()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("arch_reviewer", make_arch_reviewer_handlers),
    ],
)
def test_both_factories_reject_directory_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"circular_dep_hardening_outside_{factory_name}"
    outside.mkdir(exist_ok=True)
    _plant_real_cycle(outside)
    try:
        handlers = factory(str(tmp_path))
        result = handlers["circular_dep_detect"]({"directory": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
        assert "app.a" not in result
    finally:
        (outside / "app" / "a.py").unlink()
        (outside / "app" / "b.py").unlink()
        (outside / "app").rmdir()
        outside.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "circular_dep_detect", {"directory": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 (confirmed reproducible here, matching tool #94's sibling
# class) — PermissionError during rglob() traversal is silently
# swallowed, not raised. Pinned as a regression test.
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    (restricted / "inner.py").write_text("import os\n")
    original_mode = restricted.stat().st_mode
    restricted.chmod(0)
    try:
        yield "restricted_dir"
    finally:
        restricted.chmod(original_mode)


@pytest.mark.asyncio
async def test_chat_agent_permission_denied_does_not_raise(
    tmp_path: Path, restricted_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("circular_dep_detect", {"directory": restricted_dir})
    assert "[POLICY DENIED]" not in result


def test_make_chat_handlers_permission_denied_does_not_raise(
    tmp_path: Path, restricted_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["circular_dep_detect"]({"directory": restricted_dir})
    assert result  # must not raise


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_detects_real_cycle(tmp_path: Path) -> None:
    _plant_real_cycle(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("circular_dep_detect", {"directory": "."})
    assert "app.a" in result
    assert "app.b" in result


@pytest.mark.asyncio
async def test_chat_agent_defaults_to_repo_root(tmp_path: Path) -> None:
    _plant_real_cycle(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("circular_dep_detect", {})
    assert "app.a" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_arch_reviewer_handlers],
)
def test_both_factories_detect_real_cycle(tmp_path: Path, factory) -> None:
    _plant_real_cycle(tmp_path)
    handlers = factory(str(tmp_path))
    result = handlers["circular_dep_detect"]({"directory": "."})
    assert "app.a" in result
    assert "app.b" in result
