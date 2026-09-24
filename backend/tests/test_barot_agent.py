"""Tests for app.agents.barot_agent — the planning/guardrail layer that
decides whether and how to synthesize a temporary_agent to fill a
capability gap. Real Claude API calls are always mocked (patching
app.agents.base_graph._call_anthropic / _make_client)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.barot_agent import (
    TEMP_AGENT_EXECUTION,
    BarotDecision,
    _validate_tool_names,
    try_fill_capability_gap,
)
from app.agents.temporary_agent import get_temporary_agent_pool
from app.fleet.capability_registry import get_capability_registry


def _tool_use_response(tool_names, briefing):
    block = SimpleNamespace(
        type="tool_use",
        name="plan_tool_profile",
        input={"tool_names": tool_names, "briefing": briefing},
    )
    return SimpleNamespace(content=[block])


@pytest.fixture(autouse=True)
def _reset_settings():
    import app.config as cfg_module

    yield
    cfg_module._settings = None


# ---------------------------------------------------------------------------
# _validate_tool_names
# ---------------------------------------------------------------------------


def test_validate_tool_names_keeps_real_tools() -> None:
    assert _validate_tool_names(["read_file", "search_code"]) == [
        "read_file",
        "search_code",
    ]


def test_validate_tool_names_drops_denylisted() -> None:
    assert "delegate_to_agent" not in _validate_tool_names(
        ["read_file", "delegate_to_agent"]
    )
    assert "propose_subtask" not in _validate_tool_names(["propose_subtask"])


def test_validate_tool_names_drops_invented() -> None:
    assert _validate_tool_names(["totally_made_up_tool"]) == []


def test_validate_tool_names_drops_non_strings() -> None:
    assert _validate_tool_names(["read_file", 123, None]) == ["read_file"]


def test_validate_tool_names_dedupes() -> None:
    assert _validate_tool_names(["read_file", "read_file"]) == ["read_file"]


# ---------------------------------------------------------------------------
# try_fill_capability_gap — guard order
# ---------------------------------------------------------------------------


def test_declines_when_disabled(monkeypatch) -> None:

    monkeypatch.setenv("BAROT_AGENT_ENABLED", "false")
    import app.config as cfg_module

    cfg_module._settings = None

    with patch("app.agents.base_graph._call_anthropic") as mock_call:
        decision = try_fill_capability_gap(
            required_capability="some_gap",
            task_id="1",
            task_description="do the thing",
            repo_path="/tmp",
        )
    assert decision == BarotDecision(False, False, None, "barot_agent_disabled")
    mock_call.assert_not_called()


def test_declines_on_empty_capability() -> None:
    decision = try_fill_capability_gap(
        required_capability="", task_id="1", task_description="x", repo_path="/tmp"
    )
    assert decision.attempted is False
    assert decision.reason == "empty_capability"


def test_declines_on_missing_task_context() -> None:
    decision = try_fill_capability_gap(
        required_capability="cap_x", task_id="", task_description="", repo_path="/tmp"
    )
    assert decision.attempted is False
    assert decision.reason == "missing_task_context"

    decision2 = try_fill_capability_gap(
        required_capability="cap_x", task_id="1", task_description="", repo_path="/tmp"
    )
    assert decision2.reason == "missing_task_context"


def test_declines_on_recursion_guard() -> None:
    token = TEMP_AGENT_EXECUTION.set(True)
    try:
        decision = try_fill_capability_gap(
            required_capability="cap_x",
            task_id="1",
            task_description="x",
            repo_path="/tmp",
        )
        assert decision == BarotDecision(False, False, None, "recursion_blocked")
    finally:
        TEMP_AGENT_EXECUTION.reset(token)


def test_declines_at_capacity_without_calling_planning_api() -> None:
    pool = get_temporary_agent_pool()
    with patch.object(pool, "has_capacity", return_value=False):
        with patch("app.agents.base_graph._call_anthropic") as mock_call:
            decision = try_fill_capability_gap(
                required_capability="cap_x",
                task_id="1",
                task_description="x",
                repo_path="/tmp",
            )
    assert decision == BarotDecision(False, False, None, "at_capacity")
    mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# try_fill_capability_gap — happy path (mocked planning + spawn)
# ---------------------------------------------------------------------------


def test_successful_gap_fill_spawns_and_returns_success(tmp_path) -> None:
    """try_fill_capability_gap()/pool.spawn() only PLAN and REGISTER — they
    never call run_agent_graph (execution happens later, via whatever real
    path resolves and invokes the registered runtime function, exactly like
    any other agent's dispatch) — so this needs no thread orchestration."""
    response = _tool_use_response(["read_file"], "read the relevant files")

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", return_value=response
    ), patch("app.agents.base_graph.run_agent_graph") as mock_run_agent_graph:
        decision = try_fill_capability_gap(
            required_capability="unregistered_capability_xyz",
            task_id="1",
            task_description="do a thing only a made-up capability can do",
            repo_path=str(tmp_path),
        )

        assert decision.attempted is True
        assert decision.success is True
        assert decision.agent_name is not None
        assert decision.agent_name.startswith("temporary_agent-1-")
        mock_run_agent_graph.assert_not_called()

        cap = get_capability_registry().get(decision.agent_name)
        assert cap is not None
        assert cap.tools == ["read_file"]
        assert cap.capabilities == ["unregistered_capability_xyz"]

    get_temporary_agent_pool().scrap(decision.agent_name, reason="test_cleanup")


def test_declines_when_planning_returns_no_usable_tools(tmp_path) -> None:
    # Model "chooses" only denylisted/invented tools -> nothing survives
    # validation -> planning is treated as failed.
    response = _tool_use_response(["delegate_to_agent", "made_up_tool"], "briefing")

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", return_value=response
    ):
        decision = try_fill_capability_gap(
            required_capability="cap_y",
            task_id="2",
            task_description="task",
            repo_path=str(tmp_path),
        )

    assert decision.attempted is True
    assert decision.success is False
    assert decision.agent_name is None


def test_declines_when_all_models_fail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BAROT_AGENT_FALLBACK_MODELS", '["fallback-1"]')
    import app.config as cfg_module

    cfg_module._settings = None

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", side_effect=RuntimeError("api down")
    ):
        decision = try_fill_capability_gap(
            required_capability="cap_z",
            task_id="3",
            task_description="task",
            repo_path=str(tmp_path),
        )

    assert decision.attempted is True
    assert decision.success is False
    assert "api_error" in decision.reason


def test_never_grants_denylisted_tools_even_if_model_requests_them(tmp_path) -> None:
    response = _tool_use_response(
        ["read_file", "delegate_to_agent", "propose_subtask"], "briefing text"
    )

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", return_value=response
    ), patch("app.agents.base_graph.run_agent_graph") as mock_run_agent_graph:
        decision = try_fill_capability_gap(
            required_capability="cap_w",
            task_id="4",
            task_description="task",
            repo_path=str(tmp_path),
        )

        assert decision.success is True
        mock_run_agent_graph.assert_not_called()

        cap = get_capability_registry().get(decision.agent_name)
        assert cap is not None
        assert "delegate_to_agent" not in cap.tools
        assert "propose_subtask" not in cap.tools
        assert cap.tools == ["read_file"]

    get_temporary_agent_pool().scrap(decision.agent_name, reason="test_cleanup")
