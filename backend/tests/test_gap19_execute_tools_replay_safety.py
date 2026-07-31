"""Gap-closure Day 19 (Stage 1.3, answers.md) — proves the REAL production
`_make_execute_tools_node` / `_post_execute_tools_router` no longer replay
already-completed real side effects across a crash + checkpoint-resume
cycle.

Day 18's scratch repro (not committed) proved this hazard existed in a
faithful *toy analog* of execute_tools's old shape: one node invocation
ran every pending tool call in a synchronous loop, so a crash partway
through and a checkpointer resume re-ran every already-completed side
effect, because LangGraph only checkpoints between node invocations, never
inside one.

This test proves the fix against the actual production code, not an
analog: a real LangGraph StateGraph built from the real
`_make_execute_tools_node`/`_post_execute_tools_router`, a real
`MemorySaver` checkpointer, three tool calls that each perform a real
external side effect (an append to a real file — standing in for a git
commit / file write / bash command, something that happens in the outside
world and can't be undone by the graph state rolling back).

Method: stream the graph, stop consuming the generator after exactly 2 of
3 tool calls have completed (this is what a real process kill — OOM,
deploy restart — looks like: no exception, the process just stops; the
checkpointer already has the last completed superstep saved). Then, doing
exactly what a fresh process reconnecting to the same durable checkpoint
store would do, stream the SAME graph/thread_id again with `None` as
input — LangGraph's own documented "resume from the last checkpoint"
convention. The real, external side-effect log proves whether the two
tool calls that already completed before the "crash" ran again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
    _post_execute_tools_router,
)


def _make_side_effect_handler(log_path: Path) -> Any:
    def handler(inp: dict[str, Any]) -> str:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{inp['label']}\n")
        return "ok"

    return handler


def _build_probe_graph(log_path: Path) -> Any:
    """A minimal graph exercising the exact same node + router + self-loop
    wiring build_agent_graph() uses for execute_tools, with call_llm
    skipped entirely (execute_tools is the entry point) since this test
    targets execute_tools's own replay safety, not the full agent loop."""
    node = _make_execute_tools_node(
        tool_handlers={"record_side_effect": _make_side_effect_handler(log_path)},
        verification_cfg=VerificationConfig(),
        human_approval_required=False,
        tools=[
            {
                "name": "record_side_effect",
                "description": "Record a side effect",
                "input_schema": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                },
            }
        ],
    )

    g: StateGraph[Any, Any, Any, Any] = StateGraph(AgentRunState)
    g.add_node("execute_tools", node)  # type: ignore[call-overload]
    g.set_entry_point("execute_tools")
    # No submit_* tool call in this probe, so submitted never flips True —
    # _post_execute_tools_router only ever returns "execute_tools" (batch
    # still draining) or "call_llm" (batch drained), exactly like the real
    # graph's own self-loop plus its post-batch continuation.
    g.add_conditional_edges(
        "execute_tools",
        _post_execute_tools_router,
        {"execute_tools": "execute_tools", "critique_node": END, "call_llm": END},
    )
    return g.compile(checkpointer=MemorySaver())


def _initial_state() -> AgentRunState:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "record_side_effect",
                        "input": {"label": "a"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tu2",
                        "name": "record_side_effect",
                        "input": {"label": "b"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tu3",
                        "name": "record_side_effect",
                        "input": {"label": "c"},
                    },
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


def test_execute_tools_does_not_replay_completed_side_effects_after_resume(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "side_effects.log"
    graph = _build_probe_graph(log_path)
    config = {"configurable": {"thread_id": "day19-repro-1"}}

    for _ in graph.stream(_initial_state(), config=config, stream_mode="values"):
        # Simulate a real process crash right after 2 of the 3 side effects
        # have actually happened: no exception, the process just stops.
        # MemorySaver already has the checkpoint from that completed
        # superstep persisted. Checking the real external log (not a step
        # counter) is what makes this robust to exactly which stream
        # "values" event the 2nd completed tool call lands on.
        if (
            log_path.exists()
            and len(log_path.read_text(encoding="utf-8").splitlines()) >= 2
        ):
            break

    log_after_crash = log_path.read_text(encoding="utf-8").splitlines()
    assert log_after_crash == ["a", "b"], (
        "sanity check: exactly the first two tool calls should have run "
        f"before the simulated crash, got {log_after_crash}"
    )

    # A fresh process resuming from the same durable checkpoint: same
    # thread_id, None as input — LangGraph's documented resume convention.
    for _ in graph.stream(None, config=config, stream_mode="values"):
        pass

    log_after_resume = log_path.read_text(encoding="utf-8").splitlines()
    assert log_after_resume == ["a", "b", "c"], (
        "REPLAY-SAFETY REGRESSION: tool calls that already completed "
        f"before the crash must not run again on resume, got {log_after_resume}"
    )


def test_execute_tools_completes_normally_with_no_crash(tmp_path: Path) -> None:
    """Control case: without any interruption, all three side effects run
    exactly once, in order — the decomposition doesn't change normal-path
    behavior, only what happens across a crash/resume."""
    log_path = tmp_path / "side_effects.log"
    graph = _build_probe_graph(log_path)
    config = {"configurable": {"thread_id": "day19-repro-2"}}

    for _ in graph.stream(_initial_state(), config=config, stream_mode="values"):
        pass

    log = log_path.read_text(encoding="utf-8").splitlines()
    assert log == ["a", "b", "c"]
