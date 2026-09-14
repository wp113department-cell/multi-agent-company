"""generate_diagram tool #146 — tool_enhance.md productionization
pass (2026-09-14).

Two real, empirically-verified findings on the one real implementation
(`generate_diagram_h`'s private helpers `_real_class_diagram` /
`_real_call_flowchart` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine CLASS/METHOD/FUNCTION-NAME
   disclosure oracle. `root / file_path` was never validated (same
   class as tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144)
   — proved live: a real class's name AND method names (classDiagram
   mode), and real function names + call edges (flowchart mode), were
   genuinely disclosed from a file entirely outside the worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144).

Both are now closed via a shared `generate_diagram_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.generate_diagram import (
    GENERATE_DIAGRAM_TOOL,
    generate_diagram_handler,
)

SECRET_MODULE = (
    "class SuperSecretInternalClass:\n"
    "    def top_secret_method(self):\n"
    "        pass\n\n"
    "def caller_function():\n"
    "    helper_function()\n\n"
    "def helper_function():\n"
    "    pass\n"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_generate_diagram_hardening", repo_path=repo)
    return ChatAgent(session)


def test_generate_diagram_tool_schema() -> None:
    assert GENERATE_DIAGRAM_TOOL["name"] == "generate_diagram"
    assert GENERATE_DIAGRAM_TOOL["input_schema"]["required"] == ["description"]  # type: ignore[index]


def test_generate_diagram_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("generate_diagram") == 1


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret_module.py"
    secret.write_text(SECRET_MODULE)
    return secret


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape class/method/function-name disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_class_diagram_escape_blocked(
        self, worktree: Path, outside_secret: Path
    ) -> None:
        out = generate_diagram_handler(
            worktree,
            str(worktree),
            {
                "description": "x",
                "kind": "classDiagram",
                "path": str(outside_secret),
            },
        )
        assert "POLICY DENIED" in out
        assert "SuperSecretInternalClass" not in out
        assert "top_secret_method" not in out

    def test_direct_handler_flowchart_escape_blocked(
        self, worktree: Path, outside_secret: Path
    ) -> None:
        out = generate_diagram_handler(
            worktree,
            str(worktree),
            {
                "description": "x",
                "kind": "flowchart",
                "path": str(outside_secret),
            },
        )
        assert "POLICY DENIED" in out
        assert "caller_function" not in out
        assert "helper_function" not in out

    def test_make_chat_handlers_escape_blocked(
        self, worktree: Path, outside_secret: Path
    ) -> None:
        handlers = make_chat_handlers(str(worktree))
        out = handlers["generate_diagram"](
            {
                "description": "x",
                "kind": "classDiagram",
                "path": str(outside_secret),
            }
        )
        assert "POLICY DENIED" in out
        assert "SuperSecretInternalClass" not in out

    def test_chat_agent_dispatch_escape_blocked(
        self, worktree: Path, outside_secret: Path
    ) -> None:
        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "generate_diagram",
                {
                    "description": "x",
                    "kind": "classDiagram",
                    "path": str(outside_secret),
                },
            )

        import asyncio

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out
        assert "SuperSecretInternalClass" not in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, worktree: Path) -> None:
        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "generate_diagram", {"description": "generic", "kind": "sequence"}
            )

        import asyncio

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "sequenceDiagram" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree files, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_class_diagram_real_classes_in_worktree(self, worktree: Path) -> None:
        (worktree / "shapes.py").write_text(
            "class Shape:\n    def area(self):\n        pass\n\n"
            "class Circle(Shape):\n    def area(self):\n        return 1\n"
        )
        handlers = make_chat_handlers(str(worktree))
        out = handlers["generate_diagram"](
            {"description": "shapes", "kind": "classDiagram", "path": "shapes.py"}
        )
        assert "classDiagram" in out
        assert "Shape <|-- Circle" in out

    def test_flowchart_real_call_edges_in_worktree_via_chat_agent(
        self, worktree: Path
    ) -> None:
        (worktree / "flow.py").write_text(
            "def outer():\n    return inner()\n\ndef inner():\n    return 1\n"
        )
        agent = _agent(str(worktree))

        async def _run() -> str:
            return await agent._execute_tool(
                "generate_diagram",
                {"description": "flow", "kind": "flowchart", "path": "flow.py"},
            )

        import asyncio

        out = asyncio.run(_run())
        assert "outer --> inner" in out

    def test_no_path_falls_back_to_template(self, worktree: Path) -> None:
        handlers = make_chat_handlers(str(worktree))
        out = handlers["generate_diagram"](
            {"description": "generic", "kind": "flowchart"}
        )
        assert "A[Start]" in out
        assert "derive this from actual code" in out

    def test_class_diagram_falls_back_when_no_classes(self, worktree: Path) -> None:
        (worktree / "empty.py").write_text("x = 1\n")
        handlers = make_chat_handlers(str(worktree))
        out = handlers["generate_diagram"](
            {"description": "nothing", "kind": "classDiagram", "path": "empty.py"}
        )
        assert "MyClass" in out
