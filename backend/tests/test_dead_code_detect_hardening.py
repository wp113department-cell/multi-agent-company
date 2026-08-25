"""dead_code_detect tool #94 — tool_enhance.md productionization pass
(2026-08-25).

Four real implementations, all thin one-liners sharing the identical
worktree-boundary-escape bug, unified into one shared
`dead_code_detect_handler()` in `app.tools.filesystem.dead_code_detect`:

1. Worktree-boundary escape on all four — proved live, a request for a
   directory outside the repo genuinely returned real function names and
   line references from that outside directory.
2. Checked for the sibling class established by tools #83/#93 (an
   uncaught PermissionError on the same underlying `app.repo_tools.
   ast_engine` module) — confirmed it does NOT reproduce here.
   `detect_dead_code()`'s internal `Path(directory).rglob("*.py")` call
   silently swallows `PermissionError` during traversal (verified
   directly against Python's own pathlib behavior), so a restricted
   subdirectory produces a harmless "(no .py files found)" message
   rather than raising. This is documented, checked-safe behavior — not
   a regression to fix — and is pinned here so it isn't accidentally
   broken by a future change.

`app.repo_tools.ast_engine.detect_dead_code()` itself is untouched and
still does the real heuristic scan — it's reused, not reinvented.

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
    make_cleanup_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.dead_code_detect import DEAD_CODE_DETECT_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_dead_code_detect_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_dead_code_detect_tool_schema() -> None:
    assert DEAD_CODE_DETECT_TOOL["name"] == "dead_code_detect"
    assert DEAD_CODE_DETECT_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_dead_code_detect_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("dead_code_detect") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-boundary escape (all four real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_directory_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "dead_code_hardening_outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("def totally_unused_secret_function():\n    return 42\n")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool("dead_code_detect", {"directory": str(outside)})
        assert "[POLICY DENIED]" in result
        assert "totally_unused_secret_function" not in result
    finally:
        (outside / "secret.py").unlink()
        outside.rmdir()


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("arch_reviewer", make_arch_reviewer_handlers),
        ("cleanup_agent", make_cleanup_agent_handlers),
    ],
)
def test_all_three_factories_reject_directory_outside_repo(
    tmp_path: Path, factory_name: str, factory
) -> None:
    outside = tmp_path.parent / f"dead_code_hardening_outside_{factory_name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("def totally_unused_secret_function():\n    return 42\n")
    try:
        handlers = factory(str(tmp_path))
        result = handlers["dead_code_detect"]({"directory": str(outside)})
        assert "[POLICY DENIED]" in result, f"{factory_name} did not reject the escape"
        assert "totally_unused_secret_function" not in result
    finally:
        (outside / "secret.py").unlink()
        outside.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_rejects_dotdot_traversal(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "dead_code_detect", {"directory": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Finding #2 (checked, confirmed NOT reproducible here) — PermissionError
# during rglob() traversal is silently swallowed, not raised. Pinned as a
# regression test so this documented-safe behavior isn't broken later.
# ---------------------------------------------------------------------------


@pytest.fixture
def restricted_dir(tmp_path: Path):
    restricted = tmp_path / "restricted_dir"
    restricted.mkdir()
    (restricted / "inner.py").write_text("def unused_inner():\n    pass\n")
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
    result = await agent._execute_tool("dead_code_detect", {"directory": restricted_dir})
    assert "[POLICY DENIED]" not in result
    assert "unused_inner" not in result


def test_make_chat_handlers_permission_denied_does_not_raise(
    tmp_path: Path, restricted_dir: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses permission checks, cannot exercise this path")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["dead_code_detect"]({"directory": restricted_dir})
    assert "unused_inner" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_shows_real_dead_code(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def totally_unused_real_function():\n    return 1\n\n\n"
        "def used_function():\n    return used_function_caller()\n\n\n"
        "def used_function_caller():\n    return 1\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("dead_code_detect", {"directory": "."})
    assert "totally_unused_real_function" in result


@pytest.mark.asyncio
async def test_chat_agent_defaults_to_repo_root(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text(
        "def totally_unused_default_scan():\n    return 1\n"
    )
    agent = _agent(tmp_path)
    result = await agent._execute_tool("dead_code_detect", {})
    assert "totally_unused_default_scan" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_arch_reviewer_handlers, make_cleanup_agent_handlers],
)
def test_all_three_factories_show_real_dead_code(tmp_path: Path, factory) -> None:
    (tmp_path / "target.py").write_text(
        "def totally_unused_factory_scan():\n    return 1\n"
    )
    handlers = factory(str(tmp_path))
    result = handlers["dead_code_detect"]({"directory": "."})
    assert "totally_unused_factory_scan" in result
