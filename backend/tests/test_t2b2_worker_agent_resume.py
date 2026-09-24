"""T2-B2 (2026-09-22, GRIDIRON_PARTIAL #212/#213/#235/#236/#246) — real
end-to-end proof that run_agent_graph(resume_trace_id=...) genuinely
continues a previous run's checkpointed conversation, rather than silently
restarting from a fresh AgentRunState under the same thread_id (the
pre-existing bug: `graph.stream(initial_state, config=run_config, ...)`
always passed a freshly-built literal dict, and AgentRunState has no
Annotated/reducer fields, so LangGraph's default last-write-wins channel
semantics simply overwrote whatever the checkpoint held on every call).

Matches tests/test_gap21_agent_checkpointer_postgres.py's own real-Postgres-
checkpointer convention: `graph.stream()` (called deep inside
run_agent_graph, a plain sync function) is dispatched via asyncio.to_thread()
so AsyncPostgresSaver's sync methods can bridge back onto this test's own
running event loop, exactly the production shape (run_agent_graph is always
invoked via asyncio.to_thread from an async caller).

The LLM itself is mocked (unittest.mock, same pattern as
tests/test_phase36_continuous_replanning.py) — this test is proving the real
LangGraph/checkpointer/Python wiring, not model behavior, and the initiative's
own standing rule is to spend real Claude API credits only when a live model
behavior genuinely needs proving, not for infrastructure tests like this one.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base_graph import (
    VerificationConfig,
    close_agent_checkpointer,
    init_agent_checkpointer,
    run_agent_graph,
)
from app.config import get_settings

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit the result",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


class _ImmediateSubmitLLM:
    """Always submits on its very first (and only) real turn — the simplest
    possible real graph execution, just enough to produce a genuine
    checkpoint with real conversation history for the next call to resume
    from. Records every `messages` list it was ever called with, so the test
    can assert on exactly what the model actually saw."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.seen_messages.append(list(kwargs.get("messages") or []))
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id=f"tu{self.calls}",
                    name="submit_result",
                    input={"summary": f"done {self.calls}"},
                )
            ],
            usage=SimpleNamespace(input_tokens=25, output_tokens=9),
        )


def _run_kwargs(trace_kwarg: dict[str, str], initial_message: str) -> dict[str, Any]:
    return dict(
        role_name="t2b2_resume_test_agent",
        model="claude-haiku-4-5-20251001",
        tools=[SUBMIT_TOOL],
        tool_handlers={"submit_result": lambda inp: "ok"},
        verification_cfg=VerificationConfig(),
        initial_message=initial_message,
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        enable_critique=False,
        enable_replanning=False,
        max_turns=5,
        enable_run_tracking=False,  # unrelated to what this test proves
        **trace_kwarg,
    )


@pytest.mark.asyncio
async def test_resume_trace_id_continues_real_prior_conversation_real_postgres() -> (
    None
):
    settings = get_settings()
    await init_agent_checkpointer(settings.database_url)
    try:
        llm = _ImmediateSubmitLLM()
        tid = f"t2b2-resume-{uuid.uuid4().hex[:8]}"

        with (
            patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            # "Process 1" — the original run, ends naturally (submits).
            final_state_1 = await asyncio.to_thread(
                run_agent_graph,
                **_run_kwargs({"trace_id": tid}, "original task: implement X"),
            )
            assert final_state_1["submitted"] is True
            turns_after_1 = final_state_1["turns"]
            tokens_after_1 = final_state_1["tokens_in"] + final_state_1["tokens_out"]
            messages_after_1 = final_state_1["messages"]
            assert any(
                "original task" in str(m.get("content")) for m in messages_after_1
            ), "sanity check: the first run's own message must be in its own final state"

            # "Process 2" — a fresh call under resume_trace_id, a NEW
            # follow-up message, no trace_id/initial-state literal reuse.
            final_state_2 = await asyncio.to_thread(
                run_agent_graph,
                **_run_kwargs(
                    {"resume_trace_id": tid}, "follow-up: also handle the Y case"
                ),
            )
            assert final_state_2["submitted"] is True

            # THE CORE PROOF: turn 2's conversation contains BOTH the
            # original message AND the follow-up — real continuation, not a
            # silent restart from a fresh AgentRunState under the same
            # thread_id (the pre-existing bug this batch fixes).
            combined = " ".join(
                str(m.get("content")) for m in final_state_2["messages"]
            )
            assert "original task" in combined, (
                "resume must carry the ORIGINAL run's conversation forward — "
                "it is missing entirely, meaning this silently restarted "
                "from scratch instead of resuming"
            )
            assert "follow-up" in combined

            # Counters carried forward, not reset to 0 — the same "continue,
            # don't restart" claim, checked on the numeric side too.
            assert final_state_2["turns"] > turns_after_1
            assert (
                final_state_2["tokens_in"] + final_state_2["tokens_out"]
                > tokens_after_1
            )

            # The mock model's FIRST call of the SECOND run must have
            # actually been sent the real prior history (not just present in
            # the checkpoint object, or only visible in the final output) —
            # proves the merged state was truly the input to graph.stream(),
            # not reconstructed after the fact. Each submit cycle is 2 real
            # LLM calls (the tool_use turn, then one more turn where the
            # model sees the tool_result before the graph ends) — so index 2
            # is run 2's first call, immediately after run 1's 2 calls.
            assert llm.calls == 4
            second_run_first_call_messages = llm.seen_messages[2]
            assert any(
                "original task" in str(m.get("content"))
                for m in second_run_first_call_messages
            ), "the LLM's first real call of the resumed run did not receive the prior turn's history"
    finally:
        await close_agent_checkpointer()


@pytest.mark.asyncio
async def test_unset_resume_trace_id_does_not_leak_a_prior_runs_history_real_postgres() -> (
    None
):
    """Regression guard the other direction: reusing the same trace_id via
    the ORDINARY `trace_id=` kwarg (not `resume_trace_id=`) must behave
    exactly as it always has — a normal fresh run, unaffected by whatever a
    prior run under that same id left checkpointed. Only the explicit
    resume_trace_id= opt-in triggers continuation."""
    settings = get_settings()
    await init_agent_checkpointer(settings.database_url)
    try:
        llm = _ImmediateSubmitLLM()
        tid = f"t2b2-noresume-{uuid.uuid4().hex[:8]}"

        with (
            patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            await asyncio.to_thread(
                run_agent_graph,
                **_run_kwargs({"trace_id": tid}, "original task: implement X"),
            )
            final_state_2 = await asyncio.to_thread(
                run_agent_graph,
                **_run_kwargs({"trace_id": tid}, "a completely unrelated task"),
            )

        combined = " ".join(str(m.get("content")) for m in final_state_2["messages"])
        assert "original task" not in combined
        assert final_state_2["turns"] == 1  # fresh, not carried forward
    finally:
        await close_agent_checkpointer()
