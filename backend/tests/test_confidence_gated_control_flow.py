"""plan14 Day 1 Task 2 — Confidence-Gated Control Flow.

The quality gate (base_graph.py::_run_quality_gate) already computed a
confidence:threshold check and flagged raw_result["_requires_human_approval"]
before this change — proven by tests/test_phase37_quality_gate.py. What was
missing, verified by repo search before writing any code: (1) every real
caller left quality_gate_min_confidence at its implicit 0.0 default, so the
check could never fail in production, and (2) even a caller that did pass a
real threshold had no real consumer downstream — AgentResult.
requires_human_approval is hardcoded False at ~76 agent call sites and
manager.py's dispatch loop never reads that field at all.

This adds: a config-driven per-agent threshold
(Settings.quality_gate_min_confidence_by_agent), one pilot agent wired to it
(spike_agent), and a real, already-wired, already-observable consumer —
approval_gate.py's PendingApproval table (the same mechanism
request_clarification already uses) — instead of a second, novel signal path.

Tests use the real dev Postgres via approval_gate.py's own facades, matching
the established pattern in tests/test_approval_gate.py (thread_id-prefixed
rows, cleaned up in a try/finally).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.agents.base_graph import (
    VerificationConfig,
    _make_execute_tools_node,
    run_agent_graph,
)
from app.config import get_settings
from app.fleet import approval_gate as ag


def _cfg(**overrides: Any) -> VerificationConfig:
    base: dict[str, Any] = dict(
        set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
    )
    base.update(overrides)
    return VerificationConfig(**base)


def _submit_state(confidence: float) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "submit_result",
                        "input": {"summary": "done"},
                    }
                ],
            }
        ],
        "verification": {},
        "result": {},
        "submitted": False,
        "turns": 1,
        "confidence": confidence,
        "critique_result": {},
    }


SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}


# ---------------------------------------------------------------------------
# Config — the per-agent threshold dict itself
# ---------------------------------------------------------------------------


def test_config_seeds_spike_agent_pilot_threshold() -> None:
    settings = get_settings()
    assert settings.quality_gate_min_confidence_by_agent.get("spike_agent") == 0.5


def test_config_unlisted_agent_falls_back_to_zero() -> None:
    settings = get_settings()
    assert (
        settings.quality_gate_min_confidence_by_agent.get("qa_totally_unlisted", 0.0)
        == 0.0
    )


# ---------------------------------------------------------------------------
# Node-level unit tests — _make_execute_tools_node, request_human_input mocked
# ---------------------------------------------------------------------------


def test_low_confidence_with_real_threshold_requests_human_input() -> None:
    with patch("app.fleet.approval_gate.request_human_input") as mock_rhi:
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            quality_gate_min_confidence=0.9,
            agent_name="cgc_test_agent",
            task_id="4242",
            trace_id="trace-abc",
        )
        node(_submit_state(confidence=0.2))

    assert mock_rhi.call_count == 1
    _, kwargs = mock_rhi.call_args
    assert kwargs["kind"] == "low_confidence_submission"
    assert kwargs["agent_name"] == "cgc_test_agent"
    assert kwargs["task_id"] == 4242
    assert kwargs["blocking"] is False
    assert kwargs["details"]["confidence"] == 0.2
    assert kwargs["details"]["min_confidence"] == 0.9


def test_default_zero_threshold_never_requests_human_input() -> None:
    """The inert-by-default invariant: quality_gate_min_confidence's own
    default (0.0) must never trigger the new HITL path, exactly as it never
    flipped gate.passed before this change."""
    with patch("app.fleet.approval_gate.request_human_input") as mock_rhi:
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            agent_name="cgc_test_agent_default",
        )
        node(_submit_state(confidence=0.01))

    mock_rhi.assert_not_called()


def test_confidence_meeting_threshold_does_not_request_human_input() -> None:
    with patch("app.fleet.approval_gate.request_human_input") as mock_rhi:
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            quality_gate_min_confidence=0.5,
            agent_name="cgc_test_agent_pass",
        )
        node(_submit_state(confidence=0.9))

    mock_rhi.assert_not_called()


def test_non_confidence_gate_failure_does_not_request_human_input() -> None:
    """A gate failure from schema validation (not confidence) must not
    trigger the confidence-specific HITL path — only confidence:threshold
    failing does."""
    with patch("app.fleet.approval_gate.request_human_input") as mock_rhi:
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            quality_gate_min_confidence=0.9,
            agent_name="cgc_test_agent_schema",
        )
        state = _submit_state(confidence=0.95)  # passes confidence
        state["messages"][0]["content"][0]["input"] = {"summary": 12345}  # wrong type
        node(state)

    mock_rhi.assert_not_called()


def test_request_human_input_failure_is_non_fatal() -> None:
    """approval_gate is a best-effort side channel — a DB error recording the
    flag must never break the actual submission."""
    with patch(
        "app.fleet.approval_gate.request_human_input",
        side_effect=RuntimeError("db unreachable"),
    ):
        node = _make_execute_tools_node(
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=_cfg(),
            human_approval_required=False,
            tools=[SUBMIT_TOOL],
            quality_gate_min_confidence=0.9,
            agent_name="cgc_test_agent_dbfail",
        )
        result = node(_submit_state(confidence=0.1))

    assert result["result"]["_quality_gate"]["passed"] is False


# ---------------------------------------------------------------------------
# Full integration — run_agent_graph end to end with a real Postgres row,
# same pattern as tests/test_approval_gate.py.
# ---------------------------------------------------------------------------


class _LowConfidencePlannerLLM:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from types import SimpleNamespace
        import json as _json

        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""

        if "Create a step-by-step plan" in last_text:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text=_json.dumps({"confidence": 0.1}))
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )
        if "Analyze this task" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="{}")],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

        tools = kwargs.get("tools") or []
        if any(t.get("name") == "submit_result" for t in tools):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu1",
                        name="submit_result",
                        input={"summary": "done"},
                    )
                ],
                usage=SimpleNamespace(input_tokens=30, output_tokens=10),
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_graph_low_confidence_creates_a_real_pending_approval_row() -> None:
    thread_id = "low-confidence-cgc-integration-trace"
    try:
        llm = _LowConfidencePlannerLLM()
        with (
            patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            run_agent_graph(
                role_name="cgc_integration_agent",
                model="claude-haiku-4-5-20251001",
                tools=[SUBMIT_TOOL],
                tool_handlers={"submit_result": lambda inp: "ok"},
                verification_cfg=_cfg(),
                initial_message="do a task",
                enable_planning=True,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                quality_gate_min_confidence=0.9,
                max_turns=10,
                trace_id="cgc-integration-trace",
            )

        pending = ag.get_pending(thread_id)
        assert pending is not None
        assert pending.action == "low_confidence_submission"
        assert pending.agent_name == "cgc_integration_agent"
        assert pending.details["confidence"] == 0.1
        assert pending.details["blocking"] is False
    finally:
        _cleanup(thread_id)


def test_graph_default_threshold_creates_no_pending_approval_row() -> None:
    """Regression safety: an agent that never opts into a real threshold
    (quality_gate_min_confidence left at 0.0, i.e. every one of the ~75
    non-pilot agents today) must produce zero PendingApproval rows even when
    the planner itself reports very low confidence."""
    thread_id = "low-confidence-cgc-no-op-trace"
    try:
        llm = _LowConfidencePlannerLLM()
        with (
            patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"),
            patch("anthropic.Anthropic") as mock_anthropic_cls,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = llm
            mock_anthropic_cls.return_value = mock_client

            run_agent_graph(
                role_name="cgc_no_op_agent",
                model="claude-haiku-4-5-20251001",
                tools=[SUBMIT_TOOL],
                tool_handlers={"submit_result": lambda inp: "ok"},
                verification_cfg=_cfg(),
                initial_message="do a task",
                enable_planning=True,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=False,
                max_turns=10,
                trace_id="cgc-no-op-trace",
            )

        assert ag.get_pending(thread_id) is None
    finally:
        _cleanup(thread_id)


def _cleanup(thread_id: str) -> None:
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import PendingApproval

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(PendingApproval).where(
                        PendingApproval.thread_id == thread_id
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# spike_agent.py wiring — confirms the real call site actually reads the
# config dict instead of leaving quality_gate_min_confidence unset.
# ---------------------------------------------------------------------------


def test_spike_agent_call_site_reads_configured_threshold() -> None:
    from app.agents import spike_agent as sa_module

    captured: dict[str, Any] = {}

    def _fake_run_agent_graph(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "result": {"summary": "ok"},
            "verification": {},
            "tokens_in": 1,
            "tokens_out": 1,
            "submitted": True,
        }

    with patch.object(sa_module, "run_agent_graph", side_effect=_fake_run_agent_graph):
        sa_module.run_spike_agent(task_id=1, description="test spike")

    assert captured["quality_gate_min_confidence"] == 0.5
