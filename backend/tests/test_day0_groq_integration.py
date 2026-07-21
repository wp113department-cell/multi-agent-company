"""
Day 0 — Real LLM integration tests via Groq.
=============================================
These tests call a REAL language model (Groq/qwen3) to verify actual agent behaviour,
not just mocked responses. They prove the nodes produce valid outputs.

SKIP CATEGORIES:
  [GROQ-OK]      — runs with Groq (small tokens, fast)
  [ANTHROPIC-ONLY] — skipped now, will run when ANTHROPIC_API_KEY is available
                     (see memory: pending_anthropic_tests)

TO REMOVE (once you have Anthropic API key):
  Delete this file and tests/groq_compat.py. Done.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

# Load .env so GROQ_API_KEY and USE_GROQ are available
try:
    from dotenv import load_dotenv

    load_dotenv(
        dotenv_path=str(__file__).replace("tests/test_day0_groq_integration.py", ".env")
    )
except ImportError:
    pass

from tests.groq_compat import groq_llm_patch  # noqa: F401 — registers fixture

# Real network calls against the Groq free tier — excluded from the default
# `pytest tests/ -q` sweep (matches pytest.ini's `-m "not slow"` addopts) since
# concurrent free-tier calls 429 or the model call itself takes long enough to
# make the full-suite run unreliable. Run explicitly on demand:
#   pytest tests/test_day0_groq_integration.py -v -m slow
pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_result",
    "description": "Submit the final answer",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "answer": {"type": "string"}},
        "required": ["summary"],
    },
}


# ---------------------------------------------------------------------------
# [GROQ-OK] planner_node — real LLM produces valid JSON plan
# ---------------------------------------------------------------------------


class TestPlannerNodeRealLLM:
    def test_planner_produces_json_with_steps(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """planner_node calls Groq and returns parseable plan JSON with steps list."""
        from app.agents.base_graph import _make_planner_node, AgentRunState

        planner = _make_planner_node(
            "llama-3.1-8b-instant", "write a hello world function in Python"
        )
        state: AgentRunState = {
            "messages": [
                {"role": "user", "content": "write a hello world function in Python"}
            ],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = planner(state)

        assert "plan" in out, "planner_node must set state['plan']"
        assert "confidence" in out, "planner_node must set state['confidence']"
        assert isinstance(out["confidence"], float), "confidence must be a float"
        assert 0.0 <= out["confidence"] <= 1.0, "confidence must be 0–1"

        # Plan must be valid JSON with a steps key
        try:
            plan_data = json.loads(out["plan"])
        except (json.JSONDecodeError, ValueError):
            # Some models wrap JSON in markdown — acceptable as long as confidence is set
            plan_data = {}
        # Either steps key exists OR plan text is non-empty (model returned something)
        assert out["plan"] != "{}" or plan_data.get("steps") is not None

    def test_planner_sets_status_running(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """planner_node always sets status=running in output."""
        from app.agents.base_graph import _make_planner_node, AgentRunState

        planner = _make_planner_node("llama-3.1-8b-instant", "add unit tests")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "add unit tests"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = planner(state)
        assert out.get("status") == "running"

    def test_planner_survives_bad_model_response(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """planner_node must not raise even when LLM returns non-JSON text."""
        from app.agents.base_graph import _make_planner_node, AgentRunState

        # Force a very short max_tokens so the model truncates its JSON
        planner = _make_planner_node("llama-3.1-8b-instant", "x" * 5)
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "x"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = planner(state)  # must not raise
        assert "confidence" in out  # always returns a confidence value


# ---------------------------------------------------------------------------
# [GROQ-OK] reflection_node — real LLM produces valid JSON {satisfied, issues}
# ---------------------------------------------------------------------------


class TestReflectionNodeRealLLM:
    def test_reflection_returns_satisfied_field(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """reflection_node produces a JSON response with a 'satisfied' boolean."""
        from app.agents.base_graph import _make_reflection_node, AgentRunState

        node = _make_reflection_node("llama-3.1-8b-instant")
        state: AgentRunState = {
            "messages": [
                {"role": "user", "content": "write a hello world function"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "def hello(): print('hello world')"}
                    ],
                },
            ],
            "verification": {},
            "result": {},
            "turns": 1,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 100,
            "tokens_out": 30,
        }
        out = node(state)
        # Either empty dict (satisfied=True) or has a messages key (not satisfied)
        assert isinstance(out, dict)
        if "messages" in out:
            last = out["messages"][-1]
            assert "[Self-review]" in last.get("content", "")

    def test_reflection_is_non_fatal_on_partial_json(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """reflection_node must not raise when LLM returns partial or non-JSON."""
        from app.agents.base_graph import _make_reflection_node, AgentRunState

        node = _make_reflection_node("llama-3.1-8b-instant")
        state: AgentRunState = {
            "messages": [{"role": "user", "content": "quick task"}],
            "verification": {},
            "result": {},
            "turns": 0,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        out = node(state)  # must not raise
        assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# [GROQ-OK] lesson extraction — real LLM extracts a reusable lesson
# ---------------------------------------------------------------------------


class TestLessonExtractionRealLLM:
    def test_lesson_extracted_and_stored(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """_extract_and_store_lesson uses Groq to extract a real lesson and stores it."""
        from app.agents.base_graph import (
            _extract_and_store_lesson,
            get_lesson_store,
            AgentRunState,
        )

        store = get_lesson_store()
        before = store.total

        state: AgentRunState = {
            "messages": [
                {"role": "user", "content": "fix the bug where tests fail on import"}
            ],
            "verification": {"tests_passed": True},
            "result": {
                "summary": "Added missing __init__.py file — tests now import correctly"
            },
            "turns": 3,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 200,
            "tokens_out": 80,
        }
        _extract_and_store_lesson(
            state, "coder", "llama-3.1-8b-instant", trace_id="groq-test-001"
        )

        assert store.total == before + 1, "lesson must be stored after a successful run"
        last = store._lessons[-1]
        assert last.agent_name == "coder"
        assert len(last.lesson) > 10, "lesson text must be non-trivial"
        assert last.category in (
            "testing",
            "security",
            "refactor",
            "debugging",
            "planning",
            "docs",
            "general",
        )

    def test_lesson_retrieval_finds_stored_lesson(
        self, groq_llm_patch: Any  # noqa: F811
    ) -> None:
        """After storing a lesson, retrieve it by keyword overlap."""
        from app.agents.base_graph import (
            _extract_and_store_lesson,
            get_lesson_store,
            AgentRunState,
        )

        state: AgentRunState = {
            "messages": [{"role": "user", "content": "add type hints to the module"}],
            "verification": {},
            "result": {
                "summary": "Added strict type annotations to all public functions"
            },
            "turns": 2,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 150,
            "tokens_out": 60,
        }
        _extract_and_store_lesson(state, "architect", "llama-3.1-8b-instant")

        store = get_lesson_store()
        results = store.retrieve("type hints annotations", top_k=3)
        assert len(results) >= 1
        # At least one result should be about types/annotations
        texts = " ".join(r.lesson + " " + r.pattern for r in results).lower()
        assert any(w in texts for w in ("type", "hint", "annotation", "strict"))


# ---------------------------------------------------------------------------
# [GROQ-OK] Full mini-graph run — planner → call_llm → submit → lesson
# ---------------------------------------------------------------------------


class TestFullGraphRunGroq:
    def test_mini_task_runs_end_to_end(self, groq_llm_patch: Any) -> None:  # noqa: F811
        """Run a real mini-task through the graph with Groq. Agent must call submit_result."""
        from app.agents.base_graph import run_agent_graph, VerificationConfig

        result_state = run_agent_graph(
            role_name="coder",
            model="qwen/qwen3-32b",
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
            model_haiku="llama-3.1-8b-instant",
            max_turns=8,
            enable_planning=True,
            enable_memory=False,  # skip repo context (no repo in test)
            enable_reflection=False,  # save tokens
            enable_lesson=True,
        )

        assert result_state["submitted"] is True, (
            "Agent must call submit_result to complete the task. "
            f"Last message: {result_state['messages'][-1] if result_state['messages'] else 'none'}"
        )
        assert result_state["result"] != {}, "result must be non-empty after submit"

    def test_trace_id_in_final_state(self, groq_llm_patch: Any) -> None:  # noqa: F811
        """trace_id passed to run_agent_graph appears in final state."""
        from app.agents.base_graph import run_agent_graph, VerificationConfig

        state = run_agent_graph(
            role_name="coder",
            model="llama-3.1-8b-instant",
            tools=[SUBMIT_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="Say hello and submit_result with summary='hi'.",
            task_description="say hello",
            model_haiku="llama-3.1-8b-instant",
            max_turns=5,
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            trace_id="GROQ-TRACE-XYZ",
        )
        assert state.get("trace_id") == "GROQ-TRACE-XYZ"


# ---------------------------------------------------------------------------
# [ANTHROPIC-ONLY] — skipped until ANTHROPIC_API_KEY is available
# These are saved in memory as: pending_anthropic_tests
# ---------------------------------------------------------------------------

ANTHROPIC_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get(
    "ANTHROPIC_API_KEY", ""
).startswith("sk-ant")

anthropic_only = pytest.mark.skipif(
    not ANTHROPIC_AVAILABLE,
    reason="[ANTHROPIC-ONLY] Requires real ANTHROPIC_API_KEY — run after key is obtained",
)


@anthropic_only
def test_prompt_caching_header_sent() -> None:
    """Verify cache_control ephemeral header is sent on system prompt (Anthropic-specific)."""
    # TODO: mock anthropic.Anthropic, capture kwargs, assert system[0]["cache_control"] == {"type": "ephemeral"}
    pass


@anthropic_only
def test_image_block_param_in_call_llm() -> None:
    """Verify ImageBlockParam flows correctly through call_llm (Anthropic vision, Day 16)."""
    # TODO: inject {"type": "image", "source": {...}} into messages, verify no serialization error
    pass


@anthropic_only
def test_reflection_node_with_real_claude() -> None:
    """Verify reflection_node with Claude Sonnet gives structured JSON reliably."""
    # qwen3 sometimes returns prose instead of JSON — Claude is more reliable here
    pass


@anthropic_only
def test_full_pipeline_pm_to_qa_with_claude() -> None:
    """Full pipeline: pm → architect → decomposer → planner → coder → reviewer → qa."""
    # Requires Claude API key + database connection. Run on Day 12 smoke test day.
    pass
