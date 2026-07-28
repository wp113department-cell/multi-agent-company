"""Tests for MASTER_AGENT_v2.md Phase 1.1 gap-closure — embed_architecture_note
had zero real call sites (confirmed by grep: only its own definition and an
importability test). Closed at the two real dispatch paths architecture-tagged
agents actually run through:
  - security_architect / database_architect / api_designer_agent — dispatched
    via app/api/specialized_agents.py, so wired into the existing universal
    post-run hook (app/memory/hooks.py::record_agent_run_outcome), same as
    embed_task_outcome/embed_failure already are.
  - architect — runs as a node inside app/pipeline/graph.py's separate
    pm->architect->decomposer pipeline, which has no shared post-run hook to
    piggyback on, so it gets a direct call at its own submission point.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.agent_result import AgentResult
from app.memory.hooks import _is_architecture_agent, record_agent_run_outcome
from app.memory.store import embed_architecture_note_sync

# ---------------------------------------------------------------------------
# _is_architecture_agent — real criterion, not a fabricated one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_name",
    ["architect", "database_architect", "security_architect", "api_designer_agent"],
)
def test_named_architecture_agents_are_recognized(agent_name: str) -> None:
    assert _is_architecture_agent(agent_name) is True


def test_agent_with_architecture_in_capability_tag_is_recognized() -> None:
    """architect.py's own real registered capability is 'architecture_design',
    not the literal 'architecture' the spec text names — the substring match
    must catch this real case, not just an exact-string one."""
    from types import SimpleNamespace

    fake_cap = SimpleNamespace(
        capabilities=["architecture_design", "technical_planning"]
    )
    with patch(
        "app.fleet.capability_registry.get_capability_registry"
    ) as mock_registry:
        mock_registry.return_value.get.return_value = fake_cap
        assert _is_architecture_agent("architect") is True


def test_unrelated_agent_is_not_recognized() -> None:
    assert _is_architecture_agent("debugger_agent") is False


def test_unknown_agent_with_no_capability_registered_is_not_recognized() -> None:
    with patch(
        "app.fleet.capability_registry.get_capability_registry"
    ) as mock_registry:
        mock_registry.return_value.get.return_value = None
        assert _is_architecture_agent("some_new_agent") is False


# ---------------------------------------------------------------------------
# embed_architecture_note_sync — the store-layer sync bridge (architect_node
# is a plain sync pipeline function, same reasoning as embed_learning_signal_sync)
# ---------------------------------------------------------------------------


def test_embed_architecture_note_sync_returns_true_on_real_write() -> None:
    fake_row = object()
    with patch(
        "app.memory.store.embed_architecture_note", new=AsyncMock(return_value=fake_row)
    ):
        result = embed_architecture_note_sync(
            task_id="1",
            content="Use event sourcing for the audit log",
            agent_name="architect",
        )
    assert result is True


def test_embed_architecture_note_sync_returns_false_when_disabled_or_no_row() -> None:
    with patch(
        "app.memory.store.embed_architecture_note", new=AsyncMock(return_value=None)
    ):
        result = embed_architecture_note_sync(
            task_id="1", content="c", agent_name="architect"
        )
    assert result is False


def test_embed_architecture_note_sync_returns_false_on_exception_never_raises() -> None:
    with patch(
        "app.memory.store.embed_architecture_note",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = embed_architecture_note_sync(
            task_id="1", content="c", agent_name="architect"
        )
    assert result is False


# ---------------------------------------------------------------------------
# record_agent_run_outcome — architecture-note wiring for the hook-dispatched
# agents (security_architect, database_architect, api_designer_agent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_architecture_agent_writes_architecture_note() -> None:
    result = AgentResult(
        summary="Chose a normalized schema with a separate audit table",
        findings=["considered denormalized, rejected for write amplification"],
        status="completed",
    )
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()),
        patch("app.memory.hooks.embed_architecture_note", new=AsyncMock()) as mock_note,
    ):
        await record_agent_run_outcome(
            agent_name="database_architect",
            task_id="10",
            description="design the schema",
            result=result,
            db=mock_db,
        )

    mock_note.assert_awaited_once()
    assert mock_note.await_args is not None
    kwargs = mock_note.await_args.kwargs
    assert kwargs["task_id"] == "10"
    assert kwargs["agent_name"] == "database_architect"
    assert "normalized schema" in kwargs["content"]
    assert "write amplification" in kwargs["content"]


@pytest.mark.asyncio
async def test_non_architecture_agent_skips_architecture_note() -> None:
    result = AgentResult(summary="Fixed the bug", status="completed")
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()),
        patch("app.memory.hooks.embed_architecture_note", new=AsyncMock()) as mock_note,
    ):
        await record_agent_run_outcome(
            agent_name="debugger_agent",
            task_id="11",
            description="fix it",
            result=result,
            db=mock_db,
        )

    mock_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_architecture_agent_skips_architecture_note() -> None:
    """The spec's own framing is 'should call this when it submits' — a
    blocked run never produced a real decision worth recording."""
    result = AgentResult(summary="Could not design a safe migration", status="blocked")
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()),
        patch("app.memory.hooks.embed_failure", new=AsyncMock()),
        patch("app.memory.hooks.embed_architecture_note", new=AsyncMock()) as mock_note,
    ):
        await record_agent_run_outcome(
            agent_name="security_architect",
            task_id="12",
            description="design auth",
            result=result,
            db=mock_db,
        )

    mock_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_architecture_note_write_failure_does_not_raise() -> None:
    result = AgentResult(summary="done", status="completed")
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()),
        patch(
            "app.memory.hooks.embed_architecture_note",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ),
    ):
        await record_agent_run_outcome(
            agent_name="api_designer_agent",
            task_id="13",
            description="design the API",
            result=result,
            db=mock_db,
        )
    # No exception propagated — test passing at all is the assertion.


# ---------------------------------------------------------------------------
# architect_node — the one architecture agent NOT dispatched through
# specialized_agents.py, so it needs its own direct call.
# ---------------------------------------------------------------------------


_SUBMITTED_PLAN_STATE = {
    "messages": [],
    "verification": {},
    "result": {
        "technical_approach": "Use a message queue to decouple ingestion from processing",
        "impacted_files": [],
        "risks": [],
        "risk_level": "low",
    },
    "turns": 1,
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 10,
    "tokens_out": 10,
}


def test_architect_node_writes_architecture_note_on_submission() -> None:
    from app.agents.architect import architect_node

    state = {
        "task_id": 55,
        "task_title": "Add async ingestion pipeline",
        "pm_brief": {},
        "repo_path": "/tmp",
    }
    with (
        patch(
            "app.agents.architect.run_agent_graph", return_value=_SUBMITTED_PLAN_STATE
        ),
        patch("app.memory.store.embed_architecture_note_sync") as mock_sync,
    ):
        architect_node(state)  # type: ignore[arg-type]

    mock_sync.assert_called_once()
    call_kwargs = mock_sync.call_args.kwargs
    assert call_kwargs["agent_name"] == "architect"
    assert "message queue" in call_kwargs["content"]
    assert call_kwargs["task_id"] == "55"


def test_architect_node_skips_write_when_not_submitted() -> None:
    from app.agents.architect import architect_node

    state = {
        "task_id": 56,
        "task_title": "t",
        "pm_brief": {},
        "repo_path": "/tmp",
    }
    not_submitted_state = {**_SUBMITTED_PLAN_STATE, "submitted": False, "result": {}}
    with (
        patch("app.agents.architect.run_agent_graph", return_value=not_submitted_state),
        patch("app.memory.store.embed_architecture_note_sync") as mock_sync,
    ):
        architect_node(state)  # type: ignore[arg-type]

    mock_sync.assert_not_called()


def test_architect_node_memory_write_failure_does_not_raise() -> None:
    from app.agents.architect import architect_node

    state = {
        "task_id": 57,
        "task_title": "t",
        "pm_brief": {},
        "repo_path": "/tmp",
    }
    with (
        patch(
            "app.agents.architect.run_agent_graph", return_value=_SUBMITTED_PLAN_STATE
        ),
        patch(
            "app.memory.store.embed_architecture_note_sync",
            side_effect=RuntimeError("db down"),
        ),
    ):
        result_state = architect_node(state)  # type: ignore[arg-type]

    assert result_state["stage"] == "decomposer"  # pipeline still proceeds
