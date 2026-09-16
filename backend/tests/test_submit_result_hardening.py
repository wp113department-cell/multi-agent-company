"""submit_result tool #194 — tool_enhance.md productionization pass
(2026-09-16).

Unlike every prior "duplicate implementation" finding in this
initiative (e.g. tool #85's submit_docs, where 4 implementations were
functionally identical), this tool had TWO implementations that were
NOT identical:

1. `app/agents/chat_agent.py::ChatAgent._execute_tool`'s own inline
   dispatch — the REAL, ONLY production code path (submit_result is
   exclusively a CHAT_TOOLS entry; `_execute_tool` never calls
   `make_chat_handlers()` at all — grepped, confirmed).
2. `make_chat_handlers()`'s own `submit_result` closure — GENUINELY
   UNREACHABLE. Confirmed via two independent checks: chat_agent.py
   never calls `make_chat_handlers()`, and none of the 37 OTHER agent
   files that DO call `make_chat_handlers()` as their base include
   "submit_result" in their own tool list (each defines its own
   distinctly-named submit_<agent> tool instead).

Fixed by extracting the REAL, production-observed behavior into a
shared `submit_result_handler()`, wiring chat_agent.py's dispatch to
it (byte-for-byte identical output), and replacing
make_chat_handlers()'s separate, unreachable, differently-worded
duplicate (and its dead `chat_result`/`_chat_result` state) with the
same shared, real-behavior handler.

The 18 test files tool_inventory.json lists against this tool are all
a false-positive from its exact-string-match heuristic: every one of
them uses "submit_result" purely as an arbitrary example tool name to
test app/agents/base_graph.py's own generic submit_*-prefixed graph
mechanics, via inline dummy schemas and lambda mock handlers — never
importing the real SUBMIT_RESULT_TOOL/make_chat_handlers from
app.agents.tools. None required a change (spot-checked several).
"""

from __future__ import annotations

from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.tools.agents.submit_result import SUBMIT_RESULT_TOOL, submit_result_handler


def test_submit_result_tool_schema() -> None:
    assert SUBMIT_RESULT_TOOL["name"] == "submit_result"
    assert SUBMIT_RESULT_TOOL["input_schema"]["required"] == ["summary", "status"]  # type: ignore[index]


def test_submit_result_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("submit_result") == 1


# ---------------------------------------------------------------------------
# Real, production-observed behavior — extracted verbatim
# ---------------------------------------------------------------------------


class TestRealBehaviorPreserved:
    def test_direct_handler_matches_real_chat_agent_dispatch_format(self) -> None:
        out = submit_result_handler({"status": "done", "summary": "wrote tests"})
        assert out == "Task complete: done\nwrote tests"

    def test_direct_handler_defaults_status_to_done(self) -> None:
        out = submit_result_handler({"summary": "no status given"})
        assert out == "Task complete: done\nno status given"

    def test_direct_handler_defaults_summary_to_empty_string(self) -> None:
        out = submit_result_handler({"status": "blocked"})
        assert out == "Task complete: blocked\n"

    def test_direct_handler_empty_input(self) -> None:
        out = submit_result_handler({})
        assert out == "Task complete: done\n"


# ---------------------------------------------------------------------------
# Finding — unreachable duplicate removed from make_chat_handlers()
# ---------------------------------------------------------------------------


class TestUnreachableDuplicateRemoved:
    def test_no_chat_result_key_exported(self) -> None:
        handlers = make_chat_handlers("/tmp")
        assert "_chat_result" not in handlers

    def test_make_chat_handlers_submit_result_now_matches_real_behavior(self) -> None:
        """Before this fix, make_chat_handlers()'s own submit_result
        closure returned a DIFFERENT string ("Result submitted: ...")
        than chat_agent.py's real dispatch ("Task complete: ...") —
        never observed in practice since it was unreachable, but now
        unified onto the one real, correct behavior."""
        handlers = make_chat_handlers("/tmp")
        out = handlers["submit_result"]({"status": "done", "summary": "x"})
        assert out == "Task complete: done\nx"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_chat_handlers("/tmp")
        out1 = handlers["submit_result"]({"status": "done", "summary": "first"})
        out2 = handlers["submit_result"]({"status": "done", "summary": "second"})
        assert out1 == "Task complete: done\nfirst"
        assert out2 == "Task complete: done\nsecond"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_wires_submit_result(self) -> None:
        handlers = make_chat_handlers("/tmp")
        assert "submit_result" in handlers
