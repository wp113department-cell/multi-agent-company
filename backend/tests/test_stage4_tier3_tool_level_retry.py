"""Stage 4 Tier 3 (2026-08-05, answer2.md Q4) — real automatic retry at the
individual-tool-call level, consuming `app/fleet/tool_manifest.py`'s
`retry_policy` field for the first time (previously pure metadata with zero
real readers, confirmed by grep before writing this).

Deliberately scoped to exclude two real hazard classes rather than blindly
honoring every tool's declared policy — proven directly below, not just
asserted in a comment:
  - `write_remote` tools (github_create_pr, slack_send_message, etc.): a
    network call that appears to fail may have already succeeded remotely;
    retrying risks a real duplicate side effect.
  - `execute`/`write_repo` tools (run_tests, pip_install, etc.): these
    return "[ERROR]" for genuinely deterministic failures (a real failing
    test) far more often than transient ones — retrying doubles real
    wall-clock cost for an outcome a retry mathematically cannot change.

Uses the same minimal-probe-graph pattern this suite already established
for `_make_execute_tools_node` (test_gap19_execute_tools_replay_safety.py)
and for Cluster N's own heartbeat throttle tests
(test_stage4_clustern_real_agent_run_heartbeat.py) — bypasses call_llm
entirely, feeds pre-set tool_use blocks directly.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
    _post_execute_tools_router,
    _run_tool_with_retry,
)
from app.fleet.tool_manifest import TOOL_MANIFEST


def _build_probe_graph(tool_name: str, handler: Any) -> Any:
    node = _make_execute_tools_node(
        tool_handlers={tool_name: handler},
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=[
            {
                "name": tool_name,
                "description": "probe",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    g: StateGraph[Any, Any, Any, Any] = StateGraph(AgentRunState)
    g.add_node("execute_tools", node)  # type: ignore[call-overload]
    g.set_entry_point("execute_tools")
    g.add_conditional_edges(
        "execute_tools",
        _post_execute_tools_router,
        {"execute_tools": "execute_tools", "critique_node": END, "call_llm": END},
    )
    return g.compile(checkpointer=MemorySaver())


def _initial_state_one_tool_call(tool_name: str) -> AgentRunState:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": tool_name, "input": {}}
                ],
            }
        ],
        "verification": {},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def test_manifest_retry_policy_is_real_metadata_confirmed_before_this_fix() -> None:
    """Baseline fact this whole fix rests on: real manifest data, not
    invented for this test."""
    non_none = [n for n, e in TOOL_MANIFEST.items() if e.retry_policy != "none"]
    assert (
        len(non_none) == 19
    )  # 3 backoff + 16 once, confirmed live before writing the fix


def test_network_only_tool_retries_once_on_error_then_succeeds() -> None:
    """check_url_status: retry_policy='once', permissions=['network'] only
    -- a real eligible tool, not a synthetic one."""
    assert TOOL_MANIFEST["check_url_status"].retry_policy == "once"
    assert TOOL_MANIFEST["check_url_status"].permissions == ["network"]

    calls: list[int] = []

    def flaky_handler(inp: dict[str, Any]) -> str:
        calls.append(1)
        if len(calls) == 1:
            return "[ERROR] simulated transient network failure"
        return "200 OK"

    graph = _build_probe_graph("check_url_status", flaky_handler)
    for _ in graph.stream(
        _initial_state_one_tool_call("check_url_status"),
        config={"configurable": {"thread_id": "retry-probe-1"}},
        stream_mode="values",
    ):
        pass

    assert len(calls) == 2  # 1 failure + 1 real retry


def test_run_tests_never_auto_retries_despite_manifest_saying_once() -> None:
    """The real safety exclusion: run_tests carries 'execute' permission,
    so it must NEVER be automatically retried even though its own manifest
    entry says retry_policy='once' -- a deterministic test failure retried
    would just waste real wall-clock time re-running the whole suite."""
    assert TOOL_MANIFEST["run_tests"].retry_policy == "once"
    assert "execute" in TOOL_MANIFEST["run_tests"].permissions

    calls: list[int] = []

    def always_fails(inp: dict[str, Any]) -> str:
        calls.append(1)
        return "[ERROR] Tests failed (exit code 1)"

    graph = _build_probe_graph("run_tests", always_fails)
    for _ in graph.stream(
        _initial_state_one_tool_call("run_tests"),
        config={"configurable": {"thread_id": "retry-probe-2"}},
        stream_mode="values",
    ):
        pass

    assert len(calls) == 1  # no retry


def test_slack_send_message_never_auto_retries_despite_manifest_saying_once() -> None:
    """The other real safety exclusion: write_remote tools must never be
    automatically retried -- a false-negative network error could mean the
    message already sent, and retrying would send a real duplicate."""
    assert TOOL_MANIFEST["slack_send_message"].retry_policy == "once"
    assert "write_remote" in TOOL_MANIFEST["slack_send_message"].permissions

    calls: list[int] = []

    def always_fails(inp: dict[str, Any]) -> str:
        calls.append(1)
        return "[ERROR] simulated timeout (message may have already sent)"

    graph = _build_probe_graph("slack_send_message", always_fails)
    for _ in graph.stream(
        _initial_state_one_tool_call("slack_send_message"),
        config={"configurable": {"thread_id": "retry-probe-3"}},
        stream_mode="values",
    ):
        pass

    assert len(calls) == 1  # no retry -- would risk a real duplicate Slack message


def test_backoff_policy_retries_up_to_three_times_then_gives_up() -> None:
    """web_search: retry_policy='backoff' -- max 3 attempts, then the real
    [ERROR] result reaches the LLM unchanged (not silently swallowed)."""
    assert TOOL_MANIFEST["web_search"].retry_policy == "backoff"

    calls: list[int] = []

    def always_fails(inp: dict[str, Any]) -> str:
        calls.append(1)
        return "[ERROR] simulated persistent network failure"

    graph = _build_probe_graph("web_search", always_fails)
    events = list(
        graph.stream(
            _initial_state_one_tool_call("web_search"),
            config={"configurable": {"thread_id": "retry-probe-4"}},
            stream_mode="values",
        )
    )

    assert len(calls) == 3  # 1 original + 2 retries, then give up
    final_messages = events[-1]["messages"]
    tool_result_msg = final_messages[-1]
    result_blocks = tool_result_msg["content"]
    assert any(
        "simulated persistent network failure" in str(b.get("content", ""))
        for b in result_blocks
    )


def test_unknown_tool_name_is_never_retried() -> None:
    """A tool with no manifest entry at all defaults to policy 'none' (1
    attempt) -- no crash, no unbounded retry on an unrecognized name."""
    calls: list[int] = []

    def handler(inp: dict[str, Any]) -> str:
        calls.append(1)
        return "[ERROR] fails"

    result = _run_tool_with_retry(handler, "totally_unknown_tool_xyz", {})
    assert len(calls) == 1
    assert result == "[ERROR] fails"


def test_exception_raised_by_handler_is_caught_and_can_still_retry() -> None:
    """A real Python exception (not just an [ERROR]-string return) from a
    retry-eligible tool must still be caught and retried, matching the
    pre-existing non-retry behavior's own exception handling."""
    calls: list[int] = []

    def raises_once(inp: dict[str, Any]) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated transient exception")
        return "200 OK"

    result = _run_tool_with_retry(raises_once, "check_url_status", {})
    assert len(calls) == 2
    assert result == "200 OK"
