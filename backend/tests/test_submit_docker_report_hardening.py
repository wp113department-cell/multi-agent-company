"""submit_docker_report tool #186 — tool_enhance.md productionization
pass (2026-09-16).

Same class and shape as sibling tools #180/#181/#182/#183/#184/#185.
No injection surface. Not in CHAT_TOOLS (one-shot docker_agent-only
tool, correct absence).

One real finding: `dk_submit`'s local `docker_result` dict was updated
on every call and exported as `handlers["_docker_result"]`, but NEVER
read anywhere in the codebase — genuinely dead state. The real
result-capture mechanism lives entirely in
app.agents.base_graph.run_agent_graph's generic submit_* handling,
confirmed by docker_agent.py's own `raw = final_state["result"]` line,
which is what real production code actually consumes. Fixed by
removing the dead accumulator; the handler now just returns the same
confirmation string as before, with zero end-to-end behavior change.
"""

from __future__ import annotations

from app.agents.tools import (
    CHAT_TOOLS,
    DOCKER_AGENT_TOOLS,
    make_docker_agent_handlers,
)
from app.tools.agents.submit_docker_report import (
    SUBMIT_DOCKER_REPORT_TOOL,
    submit_docker_report_handler,
)


def test_submit_docker_report_tool_schema() -> None:
    assert SUBMIT_DOCKER_REPORT_TOOL["name"] == "submit_docker_report"
    assert SUBMIT_DOCKER_REPORT_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "action",
        "outcome",
    ]


def test_submit_docker_report_appears_exactly_once_in_docker_agent_tools() -> None:
    names = [t["name"] for t in DOCKER_AGENT_TOOLS]
    assert names.count("submit_docker_report") == 1


def test_submit_docker_report_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_docker_report" not in names


# ---------------------------------------------------------------------------
# Finding — dead accumulator removed, behavior unchanged
# ---------------------------------------------------------------------------


class TestDeadStateRemoved:
    def test_no_docker_result_key_exported(self) -> None:
        handlers = make_docker_agent_handlers("/tmp")
        assert "_docker_result" not in handlers

    def test_direct_handler_returns_confirmation_unchanged(self) -> None:
        out = submit_docker_report_handler(
            {"action": "inspect", "outcome": "all healthy"}
        )
        assert out == "Docker report submitted"

    def test_handler_return_value_identical_regardless_of_input_shape(self) -> None:
        out_minimal = submit_docker_report_handler({})
        out_full = submit_docker_report_handler(
            {
                "action": "build",
                "outcome": "image built and pushed",
                "files_written": ["Dockerfile"],
            }
        )
        assert out_minimal == out_full == "Docker report submitted"


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_docker_agent_handlers_wires_submit_docker_report(self) -> None:
        handlers = make_docker_agent_handlers("/tmp")
        assert "submit_docker_report" in handlers
        out = handlers["submit_docker_report"](
            {"action": "inspect", "outcome": "Real submission"}
        )
        assert out == "Docker report submitted"

    def test_repeated_calls_do_not_accumulate_or_leak_state(self) -> None:
        handlers = make_docker_agent_handlers("/tmp")
        out1 = handlers["submit_docker_report"]({"action": "a", "outcome": "first"})
        out2 = handlers["submit_docker_report"]({"action": "b", "outcome": "second"})
        assert out1 == out2 == "Docker report submitted"

    def test_other_docker_agent_handlers_unaffected(self) -> None:
        handlers = make_docker_agent_handlers("/tmp")
        for key in (
            "docker_ps",
            "docker_logs",
            "docker_exec",
            "docker_compose",
            "docker_build",
            "docker_restart",
            "write_file",
            "submit_docker_report",
        ):
            assert key in handlers
