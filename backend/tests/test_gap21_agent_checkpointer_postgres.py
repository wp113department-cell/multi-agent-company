"""Gap-closure Day 21 (Stage 1.3, answers.md) — proves the real
`AsyncPostgresSaver` checkpointer wired into `build_agent_graph()` actually
durably persists worker-agent runs, safe only as of Day 19 (which closed
the replay-safety hazard that would have made this dangerous — see
tests/test_gap19_execute_tools_replay_safety.py).

Uses the real Postgres instance this dev environment already runs for the
rest of the test suite (`tests/conftest.py`'s own DATABASE_URL default,
`gridiron-postgres` docker container) — no mocking of the checkpointer
itself, since the whole point is proving the real driver/connection/thread-
bridging actually works, not just that the Python wiring compiles.

`AsyncPostgresSaver`'s sync methods (`get_tuple`/`put`/...) bridge onto
their owning event loop via `asyncio.run_coroutine_threadsafe` and
explicitly refuse to be called synchronously from the SAME thread that
owns that loop (confirmed by reading `AsyncPostgresSaver.get_tuple`'s
source before writing this test) — exactly the shape production already
has: `init_agent_checkpointer()` is awaited on the main event loop at
FastAPI startup, and every real `run_agent_graph()` call (which performs
the actual sync `graph.stream()`) is dispatched via `asyncio.to_thread()`
from `app/api/specialized_agents.py` and `app/agents/manager.py` — never
directly on the main loop. This test's helpers are wrapped in
`asyncio.to_thread()` for the same reason: calling `graph.stream()`
directly in this async test function's body would hit that same guard.

Real-Postgres-vs-MemorySaver-fallback note (found while writing this test,
confirmed against the pre-existing `app/pipeline/graph.py::init_checkpointer`
too, not something Day 21 introduced): psycopg3's async mode is
incompatible with Windows' DEFAULT `ProactorEventLoop`
(`asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
fixes it, confirmed empirically). Production runs in Docker/Linux
(`backend/Dockerfile`), whose default loop has no such incompatibility, so
this never manifests there — but on a native-Windows dev/test run (this
machine, and pytest-asyncio's own event loop for this test specifically),
`init_agent_checkpointer()` correctly falls back to `MemorySaver` per its
existing `except Exception` contract, exactly as designed. This test does
not hard-require real Postgres to have activated (that would make it
environment-flaky for the wrong reason); it proves the replay-safety
property holds against whichever backend actually activated, and reports
which one that was.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from langgraph.graph import END, StateGraph

from app.agents import base_graph as bg
from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
    _post_execute_tools_router,
    close_agent_checkpointer,
    init_agent_checkpointer,
)
from app.config import get_settings


def _make_side_effect_handler(log_path: Path) -> Any:
    def handler(inp: dict[str, Any]) -> str:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{inp['label']}\n")
        return "ok"

    return handler


def _build_probe_graph(log_path: Path) -> Any:
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
    g.add_conditional_edges(
        "execute_tools",
        _post_execute_tools_router,
        {"execute_tools": "execute_tools", "critique_node": END, "call_llm": END},
    )
    # The real point of this test: compile against the module's real
    # checkpointer (set by init_agent_checkpointer below), not a MemorySaver
    # built locally — proving the actual production wiring works.
    return g.compile(checkpointer=bg._agent_checkpointer)


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


def _run_until_two_side_effects(
    graph: Any, initial_state: AgentRunState, config: dict[str, Any], log_path: Path
) -> None:
    """Runs on a worker thread (via asyncio.to_thread), never the event
    loop thread — required for AsyncPostgresSaver's sync methods."""
    for _ in graph.stream(initial_state, config=config, stream_mode="values"):
        if (
            log_path.exists()
            and len(log_path.read_text(encoding="utf-8").splitlines()) >= 2
        ):
            break


def _run_to_completion(graph: Any, config: dict[str, Any]) -> None:
    for _ in graph.stream(None, config=config, stream_mode="values"):
        pass


@pytest.mark.asyncio
async def test_agent_checkpointer_resumes_without_replaying_completed_calls(
    tmp_path: Path,
) -> None:
    settings = get_settings()
    await init_agent_checkpointer(settings.database_url)
    backend = (
        "real AsyncPostgresSaver"
        if bg._agent_pg_cm is not None
        else (
            "MemorySaver fallback (Postgres init failed — see module docstring "
            "for the known Windows/ProactorEventLoop cause)"
        )
    )
    print(f"\n[test_gap21] checkpointer backend actually active: {backend}")
    try:
        log_path = tmp_path / "side_effects.log"
        thread_id = f"day21-pg-repro-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        # "Process 1": runs until 2 of 3 real side effects have happened,
        # then stops — simulating a real crash (no exception, just stops
        # consuming the stream), same method as Day 19's MemorySaver proof.
        graph1 = _build_probe_graph(log_path)
        await asyncio.to_thread(
            _run_until_two_side_effects, graph1, _initial_state(), config, log_path
        )

        log_after_crash = log_path.read_text(encoding="utf-8").splitlines()
        assert log_after_crash == ["a", "b"], (
            f"sanity check: exactly the first two tool calls should have "
            f"run before the simulated crash, got {log_after_crash}"
        )

        # "Process 2": a BRAND NEW StateGraph object (fresh compile, exactly
        # like a fresh Python process reconnecting after a restart), same
        # thread_id, resuming from the real Postgres-persisted checkpoint —
        # not the same in-process graph object attempt 1 used.
        graph2 = _build_probe_graph(log_path)
        await asyncio.to_thread(_run_to_completion, graph2, config)

        log_after_resume = log_path.read_text(encoding="utf-8").splitlines()
        assert log_after_resume == ["a", "b", "c"], (
            f"REPLAY-SAFETY REGRESSION against the {backend} checkpointer: "
            f"tool calls that already completed before the crash must not "
            f"run again on resume, got {log_after_resume}"
        )
    finally:
        await close_agent_checkpointer()


def test_real_postgres_backend_activates_given_a_compatible_event_loop() -> None:
    """The test above tolerates a MemorySaver fallback because pytest-asyncio
    owns its event loop before this module ever runs, and on native Windows
    that loop is the psycopg3-incompatible ProactorEventLoop (see module
    docstring). This test isolates that variable: as a plain SYNC test
    function, nothing has created an event loop yet, so it can freely
    `asyncio.run()` with an explicitly compatible policy (SelectorEventLoop
    on Windows — what Docker/Linux production already uses by default) and
    prove the real driver/connection/`setup()` table-creation logic actually
    works end to end, not just that the Python wiring compiles."""
    import sys

    async def _try_real_postgres() -> bool:
        settings = get_settings()
        await init_agent_checkpointer(settings.database_url)
        activated = bg._agent_pg_cm is not None
        await close_agent_checkpointer()
        return activated

    if sys.platform == "win32":
        old_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            activated = asyncio.run(_try_real_postgres())
        finally:
            asyncio.set_event_loop_policy(old_policy)
    else:
        activated = asyncio.run(_try_real_postgres())

    assert activated, (
        "real AsyncPostgresSaver must activate given a psycopg3-compatible "
        "event loop — if this fails, the driver/connection/table-setup "
        "logic itself is broken (not just an unrelated Windows event-loop "
        "quirk), since Docker/Linux production uses a compatible loop by "
        "default already"
    )
