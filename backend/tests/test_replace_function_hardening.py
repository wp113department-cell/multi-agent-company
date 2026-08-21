"""replace_function tool #24 — tool_enhance.md productionization pass
(2026-08-18).

Real, empirically-verified finding (severe — a genuine "this feature has
never worked" bug, found while auditing this tool's already-worktree-
fixed implementations from tool #11): `refactor_agent`'s
`rf_replace_function` read `inp["new_body"]`, but `REPLACE_FUNCTION_TOOL`'s
own schema — the one `refactor_agent` itself advertises — documents the
field as `new_code`. Proved directly: a real, schema-conformant call
raised an unhandled `KeyError('new_body')`. A second, related gap in the
same handler: its regex only matched top-level functions, never class
methods, unlike the other two implementations.

Every test here proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real handler factories), not a
reimplementation — real file rewrites throughout.

Retroactive correction, added during tool #57's turn (2026-08-20):
building `replace_class` found the exact same boundary-detection
algorithm has a second, independent, real bug — skipping lines
starting with "#"/"@" when searching for the end boundary silently
swallowed (and discarded) a decorator/comment belonging to the NEXT
symbol, instead of preserving it. Proved live: replacing `foo()`
immediately followed by `@decorator\ndef bar():` deleted the decorator
entirely. Fixed by removing the "#"/"@" special-case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers, make_refactor_agent_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.replace_function import (
    REPLACE_FUNCTION_TOOL,
    replace_function_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_replace_function_hardening", repo_path=repo)
    return ChatAgent(session)


def test_replace_function_tool_schema_requires_new_code_not_new_body() -> None:
    assert REPLACE_FUNCTION_TOOL["name"] == "replace_function"
    assert REPLACE_FUNCTION_TOOL["input_schema"]["required"] == [
        "path",
        "function_name",
        "new_code",
    ]
    assert "new_code" in REPLACE_FUNCTION_TOOL["input_schema"]["properties"]
    assert "new_body" not in REPLACE_FUNCTION_TOOL["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# The real, proven "always crashed" bug — verified closed
# ---------------------------------------------------------------------------


def test_refactor_agent_replace_function_no_longer_raises_keyerror(
    tmp_path: Path,
) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    handlers = make_refactor_agent_handlers(str(tmp_path))
    # A real, schema-conformant call — exactly what refactor_agent's own
    # LLM would send per REPLACE_FUNCTION_TOOL's schema (new_code, not
    # new_body). This used to raise KeyError('new_body') unconditionally.
    result = handlers["replace_function"](
        {"path": "mod.py", "function_name": "foo", "new_code": "def foo():\n    return 2\n"}
    )
    assert not result.startswith("[ERROR]")
    assert result.startswith("Replaced 'foo'")
    assert (tmp_path / "mod.py").read_text() == "def foo():\n    return 2\n"


def test_refactor_agent_replace_function_can_now_replace_a_class_method(
    tmp_path: Path,
) -> None:
    """The second, related gap: the old regex only matched unindented
    top-level functions and could never match a class method."""
    (tmp_path / "mod.py").write_text(
        "class C:\n    def method(self):\n        return 1\n"
    )
    handlers = make_refactor_agent_handlers(str(tmp_path))
    result = handlers["replace_function"](
        {
            "path": "mod.py",
            "function_name": "method",
            "new_code": "    def method(self):\n        return 2\n",
        }
    )
    assert result.startswith("Replaced 'method'")
    assert "return 2" in (tmp_path / "mod.py").read_text()


# ---------------------------------------------------------------------------
# Regression — the two implementations that already worked must keep
# working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_replace_function_top_level(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "replace_function",
        {"path": "mod.py", "function_name": "foo", "new_code": "def foo():\n    return 2\n"},
    )
    assert result.startswith("Replaced 'foo'")
    assert (tmp_path / "mod.py").read_text() == "def foo():\n    return 2\n"


@pytest.mark.asyncio
async def test_chat_agent_replace_function_protected_path_denied(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "replace_function",
        {"path": ".env", "function_name": "x", "new_code": "def x(): pass\n"},
    )
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_replace_function_missing_file(tmp_path: Path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "replace_function",
        {"path": "nope.py", "function_name": "x", "new_code": "def x(): pass\n"},
    )
    assert result.startswith("[ERROR] File not found")


@pytest.mark.asyncio
async def test_chat_agent_replace_function_missing_function(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "replace_function",
        {"path": "mod.py", "function_name": "bar", "new_code": "def bar(): pass\n"},
    )
    assert result.startswith("[ERROR] Function 'bar' not found")


def test_make_chat_handlers_replace_function_still_works(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["replace_function"](
        {"path": "mod.py", "function_name": "foo", "new_code": "def foo():\n    return 2\n"}
    )
    assert result.startswith("Replaced 'foo'")


@pytest.mark.asyncio
async def test_chat_agent_replace_function_preserves_next_functions_decorator(
    tmp_path: Path,
) -> None:
    """The retroactively-fixed bug: replacing foo() must not delete
    @decorator on the immediately-following bar()."""
    (tmp_path / "mod.py").write_text(
        "def foo():\n    return 1\n\n\n@decorator\ndef bar():\n    return 2\n"
    )
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "replace_function",
        {"path": "mod.py", "function_name": "foo", "new_code": "def foo():\n    return 999\n"},
    )
    assert result.startswith("Replaced 'foo'")
    content = (tmp_path / "mod.py").read_text()
    assert "@decorator\ndef bar():" in content
    assert "return 999" in content


def test_handler_rejects_worktree_boundary_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def foo():\n    return 1\n")
    result = replace_function_handler(
        repo,
        str(repo),
        {"path": str(outside), "function_name": "foo", "new_code": "def foo(): return 2\n"},
    )
    assert result.startswith("[POLICY DENIED]")
    assert "return 1" in outside.read_text()
