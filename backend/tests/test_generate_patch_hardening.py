"""generate_patch tool #147 — tool_enhance.md productionization pass
(2026-09-14).

No worktree-escape and no shell-injection risk applies to this tool —
its input schema has only three strings (`content_a`, `content_b`,
`filename`), all pure in-memory `difflib.unified_diff()` inputs; there
is no filesystem access and no subprocess anywhere in either real
implementation — confirmed via direct code inspection.

No real bug found: both real implementations (`generate_patch_h` in
`make_chat_handlers` and `chat_agent.py`'s own separate dispatch) were
confirmed byte-for-byte behaviorally identical, and `generate_patch`
was already correctly dispatched on both real access paths — unlike
most tools this initiative, this one was never missing its
chat_agent.py dispatch branch. Consolidated the two independently-
hand-maintained duplicate copies into one shared
`generate_patch_handler()` in app/tools/filesystem/generate_patch.py,
per the mandatory modularization rule for this initiative.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.generate_patch import (
    GENERATE_PATCH_TOOL,
    generate_patch_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_generate_patch_hardening", repo_path=repo)
    return ChatAgent(session)


def test_generate_patch_tool_schema() -> None:
    assert GENERATE_PATCH_TOOL["name"] == "generate_patch"
    assert GENERATE_PATCH_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "content_a",
        "content_b",
    ]


def test_generate_patch_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("generate_patch") == 1


class TestDirectHandler:
    def test_produces_unified_diff(self) -> None:
        out = generate_patch_handler(
            {
                "content_a": "line1\nline2\n",
                "content_b": "line1\nlineX\n",
                "filename": "f.txt",
            }
        )
        assert "--- a/f.txt" in out
        assert "+++ b/f.txt" in out
        assert "-line2" in out
        assert "+lineX" in out

    def test_no_diff(self) -> None:
        out = generate_patch_handler({"content_a": "same\n", "content_b": "same\n"})
        assert out == "(no differences)"

    def test_default_filename(self) -> None:
        out = generate_patch_handler({"content_a": "a\n", "content_b": "b\n"})
        assert "a/file" in out
        assert "b/file" in out


class TestBothRealAccessPathsIdentical:
    def test_make_chat_handlers_matches_direct_handler(self) -> None:
        handlers = make_chat_handlers(".")
        inp = {
            "content_a": "one\ntwo\nthree\n",
            "content_b": "one\nTWO\nthree\n",
            "filename": "sample.py",
        }
        via_handlers = handlers["generate_patch"](inp)
        via_direct = generate_patch_handler(inp)
        assert via_handlers == via_direct

    def test_chat_agent_dispatch_matches_direct_handler(self) -> None:
        agent = _agent(".")
        inp = {
            "content_a": "one\ntwo\nthree\n",
            "content_b": "one\nTWO\nthree\n",
            "filename": "sample.py",
        }

        async def _run() -> str:
            return await agent._execute_tool("generate_patch", inp)

        via_dispatch = asyncio.run(_run())
        via_direct = generate_patch_handler(inp)
        assert via_dispatch == via_direct
        assert "Unknown tool" not in via_dispatch

    def test_chat_agent_dispatch_no_diff(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "generate_patch", {"content_a": "x\n", "content_b": "x\n"}
            )

        out = asyncio.run(_run())
        assert out == "(no differences)"
