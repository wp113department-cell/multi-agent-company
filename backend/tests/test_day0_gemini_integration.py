"""
Real LLM integration tests via Gemini (2026-09-28).
=====================================================
TEMPORARY, easily removable — a second free-tier real-LLM test backend
alongside tests/test_day0_groq_integration.py, added because Groq's own
free-tier rate limit (8,000 tokens/minute on this key) was too tight to
get through a full pending-tests pass alone. These tests call a REAL
Gemini model to prove the adapter's translation logic actually works
end-to-end through the real LangGraph agent graph, not just mocked.

TO REMOVE (once a real Anthropic key is available — see
app/agents/gemini_adapter.py's own docstring for the full removal list):
  Delete this file and tests/gemini_compat.py. Done.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.gemini_compat import gemini_llm_patch  # noqa: F401 — registers fixture

# Real network calls against the Gemini free tier — excluded from the
# default `pytest tests/ -q` sweep (matches pytest.ini's `-m "not slow"`
# addopts), same posture as test_day0_groq_integration.py. Run explicitly:
#   pytest tests/test_day0_gemini_integration.py -v -m slow
pytestmark = pytest.mark.slow

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_result",
    "description": "Submit the final answer",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "answer": {"type": "string"}},
        "required": ["summary"],
    },
}


class TestFullGraphRunGemini:
    def test_mini_task_runs_end_to_end(self, gemini_llm_patch: Any) -> None:  # noqa: F811
        """Run a real mini-task through the graph with Gemini. Agent must
        call submit_result — proves the adapter's message/tool-schema
        translation survives a real multi-turn LangGraph run, not just a
        single isolated call."""
        from app.agents.base_graph import run_agent_graph, VerificationConfig

        result_state = run_agent_graph(
            role_name="coder",
            model="gemini-2.5-flash",
            tools=[SUBMIT_TOOL],
            tool_handlers={
                "submit_result": lambda inp: f"submitted: {inp.get('summary', '')}"
            },
            verification_cfg=VerificationConfig(),
            initial_message=(
                "Write a one-line Python function called `add(a, b)` that returns a+b. "
                "Then call submit_result with summary='done'."
            ),
            task_description="Write add function and submit",
            model_haiku="gemini-2.5-flash",
            max_turns=8,
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
        )

        assert result_state["submitted"] is True, (
            "Agent must call submit_result to complete the task. "
            f"Last message: {result_state['messages'][-1] if result_state['messages'] else 'none'}"
        )
        assert result_state["result"] != {}, "result must be non-empty after submit"

    def test_trace_id_in_final_state(self, gemini_llm_patch: Any) -> None:  # noqa: F811
        """trace_id passed to run_agent_graph appears in final state —
        proves the bypass doesn't disturb ordinary state plumbing."""
        from app.agents.base_graph import run_agent_graph, VerificationConfig

        state = run_agent_graph(
            role_name="coder",
            model="gemini-2.5-flash",
            tools=[SUBMIT_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="Say hello and submit_result with summary='hi'.",
            task_description="say hello",
            model_haiku="gemini-2.5-flash",
            max_turns=5,
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            trace_id="GEMINI-TRACE-XYZ",
        )
        assert state.get("trace_id") == "GEMINI-TRACE-XYZ"
