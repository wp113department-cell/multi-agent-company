"""read_output tool #176 — tool_enhance.md productionization pass
(2026-09-15).

Audit: this tool was already dispatched on BOTH real access paths
(`make_chat_handlers()`'s `read_output_h` AND `chat_agent.py`'s own
separate dispatch), and both already delegated to the same shared,
safe `app.fleet.process_manager.read_output()` for the actual
stdout/stderr reading (no injection surface there — `pid` is only
ever used as a dict key, never reaches a subprocess/shell). Same
"duplicate implementation, core logic already shared and safe" shape
as tool #162's `list_background_processes`.

One real finding: uncaught crash on malformed `pid`/`lines` input on
BOTH call sites (missing pid, non-numeric pid, non-numeric lines).
Fixed by consolidating pid/lines parsing into a new shared
`read_output_handler()`, used identically by both call sites.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.read_output import READ_OUTPUT_TOOL, read_output_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_read_output_hardening", repo_path=repo)
    return ChatAgent(session)


def test_read_output_tool_schema() -> None:
    assert READ_OUTPUT_TOOL["name"] == "read_output"
    assert READ_OUTPUT_TOOL["input_schema"]["required"] == ["pid"]  # type: ignore[index]


def test_read_output_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("read_output") == 1


# ---------------------------------------------------------------------------
# Finding — uncaught crash on malformed input, now closed
# ---------------------------------------------------------------------------


class TestMalformedInputNoLongerCrashes:
    def test_missing_pid_returns_clean_error(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_output"]({})
        assert out.startswith("[ERROR]")

    def test_non_numeric_pid_returns_clean_error(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_output"]({"pid": "not-a-number"})
        assert out.startswith("[ERROR]")

    def test_non_numeric_lines_returns_clean_error(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_output"]({"pid": 12345, "lines": "bad"})
        assert out.startswith("[ERROR]")

    def test_direct_handler_missing_pid(self) -> None:
        out = read_output_handler({}, {}, lambda s: None)
        assert out == "[ERROR] read_output: 'pid' is required"

    def test_chat_agent_dispatch_non_numeric_pid_no_crash(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("read_output", {"pid": "not-a-number"})

        out = asyncio.run(_run())
        assert out.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real background process, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_reads_real_output(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        started = handlers["run_background"](
            {"command": "echo hello_read_output_hardening_test; sleep 0.3"}
        )
        m = re.search(r"PID (\d+)", started)
        assert m is not None
        pid = int(m.group(1))

        out = ""
        for _ in range(5):
            time.sleep(0.3)
            out = handlers["read_output"]({"pid": pid})
            if "hello_read_output_hardening_test" in out:
                break
        assert "hello_read_output_hardening_test" in out

    def test_unknown_pid_reports_clean_error_not_crash(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["read_output"]({"pid": 999999999})
        assert "[ERROR]" in out

    def test_chat_agent_dispatch_reads_real_output(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _start() -> str:
            return await agent._execute_tool(
                "run_background",
                {"command": "echo hello_from_chat_dispatch; sleep 0.3"},
            )

        started = asyncio.run(_start())
        m = re.search(r"PID (\d+)", started)
        assert m is not None
        pid = int(m.group(1))

        async def _read() -> str:
            return await agent._execute_tool("read_output", {"pid": pid})

        out = ""
        for _ in range(5):
            time.sleep(0.3)
            out = asyncio.run(_read())
            if "hello_from_chat_dispatch" in out:
                break
        assert "hello_from_chat_dispatch" in out
