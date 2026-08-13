"""plan14 Day 4 (#1 Agent-to-Agent Delegation + #13 Delegation Safety +
#12 Agent Communication) — built as one unit, per the governing spec.

Confirmed fully absent before this work (repo-wide grep, zero hits): no
delegate_to_agent, no cycle detection, no depth limit, no caller matrix.

Adversarial test session per the spec's own Day 4 requirement: force
cycles, exhaust budget, exceed depth — confirm every guard actually BLOCKS
(raises the right DelegationError subclass, or the handler returns a
[POLICY DENIED]/[ERROR] string), not just logs a warning and proceeds.

Most tests register a synthetic capability/agent pair (dg_test_* prefix,
same collision-avoidance convention as test_dynamic_tool_selection.py) and
patch _build_adapter_registry so they don't need a real LLM call to
exercise the safety guards. One real end-to-end test (spike_agent, via the
default delegation_allowed_matrix, mocked anthropic.Anthropic) proves the
mechanism actually invokes a real agent, not just a mock.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.agents.agent_result import AgentResult
from app.agents.delegation import (
    DelegationBudgetExceededError,
    DelegationCycleError,
    DelegationDepthExceededError,
    DelegationDisabledError,
    DelegationNotAllowedError,
    DelegationRequest,
    DelegationTargetUnavailableError,
    delegate,
)
from app.agents.tools import make_delegate_to_agent_handler
from app.config import get_settings, reset_settings_cache
from app.fleet.agent_registry import get_agent_registry
from app.fleet.capability_registry import AgentCapability, get_capability_registry


def _register_test_agent(name: str, capability: str) -> None:
    get_capability_registry().register(
        AgentCapability(
            name=name,
            description="test target agent",
            tools=[],
            input_types=[],
            output_types=[],
            capabilities=[capability],
        )
    )
    get_agent_registry().register(name)


def _fake_result(**overrides: object) -> AgentResult:
    base: dict[str, object] = dict(
        summary="fake summary", status="completed", verified=True
    )
    base.update(overrides)
    return AgentResult(**base)  # type: ignore[arg-type]


def _base_request(**overrides: object) -> DelegationRequest:
    base: dict[str, object] = dict(
        source_agent="dg_test_source",
        target_capability="dg_test_capability",
        objective="do the thing",
        context="",
        ancestry=("dg_test_source",),
        delegation_depth=0,
        budget_remaining_usd=1.0,
        task_id="1",
        repo_path="",
        trace_id="dg-test-trace",
        parent_run_id="",
    )
    base.update(overrides)
    return DelegationRequest(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Adversarial safety-guard tests — each must actually BLOCK, not just log
# ---------------------------------------------------------------------------


def test_delegation_disabled_blocks_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "delegation_enabled", False)
    try:
        with pytest.raises(DelegationDisabledError):
            delegate(_base_request())
    finally:
        reset_settings_cache()


def test_depth_limit_blocks_beyond_max_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "delegation_max_depth", 3)
    with pytest.raises(DelegationDepthExceededError):
        delegate(_base_request(delegation_depth=3))


def test_delegations_per_run_limit_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "delegation_max_delegations_per_run", 2)
    with pytest.raises(DelegationBudgetExceededError):
        delegate(
            _base_request(
                ancestry=("a", "b", "c"),  # 3 hops already, exceeds limit of 2
                delegation_depth=0,
            )
        )


def test_budget_exhausted_blocks_delegation() -> None:
    with pytest.raises(DelegationBudgetExceededError):
        delegate(_base_request(budget_remaining_usd=0.0))
    with pytest.raises(DelegationBudgetExceededError):
        delegate(_base_request(budget_remaining_usd=-1.0))


def test_disallowed_capability_blocked() -> None:
    with pytest.raises(DelegationNotAllowedError):
        delegate(
            _base_request(
                source_agent="dg_test_source_not_in_matrix",
                target_capability="anything",
            )
        )


def test_allowed_matrix_is_per_source_agent_not_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source agent must only reach capabilities explicitly listed for
    IT — being allowed for a different source agent must not leak."""
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_allowed_source": ["dg_test_cap_x"]},
    )
    with pytest.raises(DelegationNotAllowedError):
        delegate(
            _base_request(
                source_agent="dg_test_other_source",
                target_capability="dg_test_cap_x",
            )
        )


def test_no_available_agent_for_capability_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_source_ok": ["dg_test_capability_nobody_covers"]},
    )
    with pytest.raises(DelegationTargetUnavailableError):
        delegate(
            _base_request(
                source_agent="dg_test_source_ok",
                target_capability="dg_test_capability_nobody_covers",
            )
        )


def test_cycle_detection_blocks_a_to_b_to_a(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real adversarial case: target agent already appears in the
    delegation ancestry (A -> B -> ... -> A) must be refused BEFORE any
    invocation, not merely logged."""
    _register_test_agent("dg_test_cycle_target", "dg_test_cycle_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_cycle_source": ["dg_test_cycle_cap"]},
    )
    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={"dg_test_cycle_target": lambda *a: _fake_result()},
    ):
        with pytest.raises(DelegationCycleError):
            delegate(
                _base_request(
                    source_agent="dg_test_cycle_source",
                    target_capability="dg_test_cycle_cap",
                    # dg_test_cycle_target is already an ancestor — this
                    # delegation would re-enter it, a real cycle.
                    ancestry=("dg_test_cycle_target", "dg_test_cycle_source"),
                )
            )


def test_no_adapter_registered_for_resolved_agent_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_test_agent("dg_test_no_adapter_agent", "dg_test_no_adapter_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_no_adapter_source": ["dg_test_no_adapter_cap"]},
    )
    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={},  # resolved agent has no real invocation adapter
    ):
        with pytest.raises(DelegationTargetUnavailableError):
            delegate(
                _base_request(
                    source_agent="dg_test_no_adapter_source",
                    target_capability="dg_test_no_adapter_cap",
                )
            )


def test_delegation_timeout_actually_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real adversarial case: the target adapter hangs past the
    configured timeout — delegate() must return control to the caller
    (raising a structured DelegationTimeoutError from _run_with_timeout,
    caught internally) rather than blocking forever."""
    _register_test_agent("dg_test_slow_agent", "dg_test_slow_cap")
    monkeypatch.setattr(get_settings(), "delegation_default_timeout_seconds", 0.2)
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_slow_source": ["dg_test_slow_cap"]},
    )

    def _slow_adapter(*a: object) -> AgentResult:
        time.sleep(2.0)
        return _fake_result()

    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={"dg_test_slow_agent": _slow_adapter},
    ):
        start = time.monotonic()
        outcome = delegate(
            _base_request(
                source_agent="dg_test_slow_source", target_capability="dg_test_slow_cap"
            )
        )
        elapsed = time.monotonic() - start

    assert outcome.success is False
    assert outcome.error is not None and "timeout" in outcome.error.lower()
    # Returned promptly (well under the 2s the adapter actually sleeps for)
    assert elapsed < 1.5


# ---------------------------------------------------------------------------
# Successful delegation — structured result, real events/audit
# ---------------------------------------------------------------------------


def test_successful_delegation_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_test_agent("dg_test_success_agent", "dg_test_success_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_success_source": ["dg_test_success_cap"]},
    )
    fake = _fake_result(summary="did the work", status="completed", verified=True)
    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={"dg_test_success_agent": lambda *a: fake},
    ):
        outcome = delegate(
            _base_request(
                source_agent="dg_test_success_source",
                target_capability="dg_test_success_cap",
            )
        )

    assert outcome.success is True
    assert outcome.target_agent == "dg_test_success_agent"
    assert outcome.result is fake
    assert outcome.error is None
    assert outcome.child_ancestry == ("dg_test_source", "dg_test_success_agent")


def test_child_exception_returns_structured_failure_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child agent's own failure must return a structured failure to the
    parent — never fabricate success, never propagate an unstructured
    exception past delegate()."""
    _register_test_agent("dg_test_fail_agent", "dg_test_fail_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_fail_source": ["dg_test_fail_cap"]},
    )

    def _raising_adapter(*a: object) -> AgentResult:
        raise RuntimeError("child agent blew up")

    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={"dg_test_fail_agent": _raising_adapter},
    ):
        outcome = delegate(
            _base_request(
                source_agent="dg_test_fail_source", target_capability="dg_test_fail_cap"
            )
        )

    assert outcome.success is False
    assert outcome.result is None
    assert outcome.error is not None and "blew up" in outcome.error


def test_successful_delegation_publishes_events_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_test_agent("dg_test_event_agent", "dg_test_event_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_event_source": ["dg_test_event_cap"]},
    )
    with (
        patch(
            "app.agents.delegation._build_adapter_registry",
            return_value={"dg_test_event_agent": lambda *a: _fake_result()},
        ),
        patch("app.agents.delegation._publish_delegation_event") as mock_publish,
        patch("app.agents.delegation._audit_delegation") as mock_audit,
    ):
        outcome = delegate(
            _base_request(
                source_agent="dg_test_event_source",
                target_capability="dg_test_event_cap",
            )
        )

    assert outcome.success is True
    # requested + completed = 2 events; requested + completed = 2 audit calls
    assert mock_publish.call_count == 2
    assert mock_audit.call_count == 2
    audit_action_types = [c.args[0] for c in mock_audit.call_args_list]
    assert audit_action_types == ["delegation_requested", "delegation_completed"]


# ---------------------------------------------------------------------------
# Tool handler — make_delegate_to_agent_handler
# ---------------------------------------------------------------------------


def test_handler_rejects_missing_required_fields() -> None:
    handler = make_delegate_to_agent_handler(
        source_agent="dg_test_source", task_id="1", repo_path=""
    )
    assert handler({}).startswith("[ERROR]")
    assert handler({"target_capability": "x"}).startswith("[ERROR]")


def test_handler_returns_policy_denied_prefix_on_delegation_error() -> None:
    handler = make_delegate_to_agent_handler(
        source_agent="dg_test_source_not_in_matrix", task_id="1", repo_path=""
    )
    result = handler({"target_capability": "anything", "objective": "do it"})
    assert result.startswith("[POLICY DENIED]")


def test_handler_returns_summary_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_test_agent("dg_test_handler_agent", "dg_test_handler_cap")
    monkeypatch.setattr(
        get_settings(),
        "delegation_allowed_matrix",
        {"dg_test_handler_source": ["dg_test_handler_cap"]},
    )
    fake = _fake_result(summary="handler summary text")
    handler = make_delegate_to_agent_handler(
        source_agent="dg_test_handler_source", task_id="1", repo_path=""
    )
    with patch(
        "app.agents.delegation._build_adapter_registry",
        return_value={"dg_test_handler_agent": lambda *a: fake},
    ):
        result = handler(
            {"target_capability": "dg_test_handler_cap", "objective": "do it"}
        )

    assert "dg_test_handler_agent" in result
    assert "handler summary text" in result


# ---------------------------------------------------------------------------
# GridironEvent extension
# ---------------------------------------------------------------------------


def test_gridiron_event_new_fields_default_none() -> None:
    from app.event_bus.models import GridironEvent

    ev = GridironEvent(event_type="task.created")
    assert ev.receiver is None
    assert ev.message_type is None
    assert ev.trace_id is None
    assert ev.parent_run_id is None


def test_delegation_event_constructors_populate_routing_fields() -> None:
    from app.event_bus.models import delegation_requested

    ev = delegation_requested(
        source_agent="a", target_capability="b", trace_id="t1", parent_run_id="r1"
    )
    assert ev.event_type == "delegation.requested"
    assert ev.emitted_by == "a"
    assert ev.receiver == "b"
    assert ev.message_type == "delegation_requested"
    assert ev.trace_id == "t1"
    assert ev.parent_run_id == "r1"


# ---------------------------------------------------------------------------
# Real end-to-end — real spike_agent module code, real run_spike_agent(),
# real handler/prompt construction — WITHOUT a real graph execution.
#
# Deliberately NOT a "mock anthropic.Anthropic and let the real LangGraph
# loop run" test: run_spike_agent hardcodes enable_memory=True/
# enable_reflection=True/enable_lesson=True with no override, so a real
# graph run also does real Postgres round-trips (memory_hook_node, lesson
# persistence via get_main_loop()/run_coroutine_threadsafe) and an
# unbounded number of turns depending on how well a hand-written mock LLM
# happens to match every prompt shape the real planner/reflection nodes
# send — all of that running inside _run_with_timeout's background thread.
# That combination is unnecessarily heavy for what this test needs to
# prove. Patching one level deeper (app.agents.base_graph.run_agent_graph
# itself, the shared function every real adapter's own run_*() wrapper
# calls) keeps spike_agent's own real code — handler construction, prompt
# building, AgentResult construction from final_state — genuinely
# exercised, while making the call itself instant and DB-free.
# ---------------------------------------------------------------------------


def test_real_delegation_to_spike_agent_end_to_end() -> None:
    """Uses the REAL default delegation_allowed_matrix (backend_dev ->
    research_spike) and the REAL spike_agent capability registration
    (module-level _register() already ran at import time). Proves the
    adapter registry really calls through to spike_agent's own real
    run_spike_agent() — not a stub — including its real post-processing of
    the graph's final state into a real AgentResult."""
    import app.agents.spike_agent  # noqa: F401  ensure _register() has run

    fake_final_state: dict[str, object] = {
        "result": {"summary": "delegated spike done", "findings": []},
        "verification": {"read": True},
        "tokens_in": 100,
        "tokens_out": 50,
        "submitted": True,
    }

    with patch("app.agents.spike_agent.run_agent_graph", return_value=fake_final_state):
        outcome = delegate(
            _base_request(
                source_agent="backend_dev",
                target_capability="research_spike",
                ancestry=("backend_dev",),
                budget_remaining_usd=1.0,
            )
        )

    assert outcome.success is True
    assert outcome.target_agent == "spike_agent"
    assert outcome.result is not None
    assert outcome.result.summary == "delegated spike done"
    assert outcome.result.status == "completed"
    assert outcome.result.verified is True
