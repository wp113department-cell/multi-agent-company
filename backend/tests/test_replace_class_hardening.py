"""replace_class tool #57 — tool_enhance.md productionization pass
(2026-08-20).

Worktree-boundary handling was already correct on both real
implementations (tool #11's fix, re-verified here, not re-fixed).

Real, severe, empirically-proven finding instead: a genuine content-
loss bug in the class-boundary-detection algorithm, identical in both
real implementations. The end-boundary scan skipped lines starting
with "#"/"@", meaning a decorator or comment belonging to the NEXT
top-level class/function was silently swallowed into (and discarded
with) the replaced target's region. Proved live: replacing a middle
class immediately followed by "@dataclass\nclass Baz:" deleted the
blank lines and the decorator entirely from the output. The identical
bug was also found in the sibling replace_function tool (#24, already
shipped) and retroactively fixed there in this same turn.

Every test here uses a real file on disk and proves the fix against
the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.replace_class import REPLACE_CLASS_TOOL


def _real_multiclass_file(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "classes.py").write_text(
        "import os\n"
        "\n"
        "\n"
        "class Foo:\n"
        "    def method_a(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Bar:\n"
        "    def method_c(self):\n"
        "        return 3\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Baz:\n"
        "    x: int\n"
        "    y: int\n"
        "\n"
        "\n"
        "class Qux:\n"
        "    def last_method(self):\n"
        '        return "last"\n'
    )
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_replace_class_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_replace_class_tool_schema_requires_fields() -> None:
    assert REPLACE_CLASS_TOOL["name"] == "replace_class"
    assert REPLACE_CLASS_TOOL["input_schema"]["required"] == [
        "path",
        "class_name",
        "new_code",
    ]


def test_replace_class_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("replace_class") == 1


# ---------------------------------------------------------------------------
# The proven decorator/content-loss finding — verified closed on both
# real call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_replace_class_preserves_next_classes_decorator(
    tmp_path: Path,
) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {
            "path": "classes.py",
            "class_name": "Bar",
            "new_code": "class Bar:\n    def method_c(self):\n        return 999\n",
        },
    )
    assert result.startswith("Replaced class 'Bar'")

    content = (repo / "classes.py").read_text()
    assert "@dataclass\nclass Baz:" in content
    assert "class Qux:" in content
    assert "return 999" in content


def test_make_chat_handlers_replace_class_preserves_next_classes_decorator(
    tmp_path: Path,
) -> None:
    repo = _real_multiclass_file(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["replace_class"](
        {
            "path": "classes.py",
            "class_name": "Bar",
            "new_code": "class Bar:\n    def method_c(self):\n        return 999\n",
        }
    )
    assert result.startswith("Replaced class 'Bar'")

    content = (repo / "classes.py").read_text()
    assert "@dataclass\nclass Baz:" in content


# ---------------------------------------------------------------------------
# Worktree-boundary protection — re-verified live, not re-fixed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_replace_class_rejects_outside_repo_path(
    tmp_path: Path,
) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {"path": "/etc/hostname", "class_name": "X", "new_code": "class X: pass\n"},
    )
    assert result.startswith("[POLICY DENIED]")


@pytest.mark.asyncio
async def test_chat_agent_replace_class_rejects_protected_path(
    tmp_path: Path,
) -> None:
    repo = _real_multiclass_file(tmp_path)
    (repo / ".env").write_text("SECRET=x\n")
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {"path": ".env", "class_name": "X", "new_code": "class X: pass\n"},
    )
    assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# Regression — every other position must keep working exactly as
# before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_replace_class_first_class(tmp_path: Path) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {
            "path": "classes.py",
            "class_name": "Foo",
            "new_code": "class Foo:\n    def method_a(self):\n        return 111\n",
        },
    )
    assert result.startswith("Replaced class 'Foo'")
    content = (repo / "classes.py").read_text()
    assert "return 111" in content
    assert "class Bar:" in content


@pytest.mark.asyncio
async def test_chat_agent_replace_class_last_class_in_file(tmp_path: Path) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {
            "path": "classes.py",
            "class_name": "Qux",
            "new_code": (
                "class Qux:\n"
                "    def last_method(self):\n"
                '        return "replaced_last"\n'
            ),
        },
    )
    assert result.startswith("Replaced class 'Qux'")
    assert "replaced_last" in (repo / "classes.py").read_text()


@pytest.mark.asyncio
async def test_chat_agent_replace_class_not_found(tmp_path: Path) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {
            "path": "classes.py",
            "class_name": "NoSuchClass",
            "new_code": "class NoSuchClass: pass\n",
        },
    )
    assert result.startswith("[ERROR] Class 'NoSuchClass' not found")


@pytest.mark.asyncio
async def test_chat_agent_replace_class_file_not_found(tmp_path: Path) -> None:
    repo = _real_multiclass_file(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "replace_class",
        {"path": "nope.py", "class_name": "X", "new_code": "class X: pass\n"},
    )
    assert result.startswith("[ERROR] File not found")
