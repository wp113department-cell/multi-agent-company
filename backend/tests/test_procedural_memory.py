"""Tests for MASTER_AGENT_v2.md Phase 1.5 — procedural memory.

Before this, memory captured only declarative facts (task/failure/
architecture/learning categories) — WHAT happened, never HOW a hard problem
was actually solved. Confirmed via grep: no repair_strategy/playbook/
fix_pattern structure existed anywhere in this codebase. Covers the
store-layer write/read (embed_procedure/query_procedures) and the
base_graph.py wiring that decides when a real procedure is worth recording
(_extract_steps_taken/_maybe_store_procedure).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base_graph import (
    AgentRunState,
    _extract_steps_taken,
    _maybe_store_procedure,
)
from app.memory.store import (
    embed_procedure,
    format_full_memory_context,
    query_procedures,
)

# ---------------------------------------------------------------------------
# embed_procedure / query_procedures — store layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_procedure_inserts_row_with_procedure_category() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_refresh(obj: Any) -> None:
        obj.id = 1

    mock_db.refresh = fake_refresh

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.0] * 1536

        result = await embed_procedure(
            task_id="task-1",
            symptom="flaky test failing intermittently in CI",
            steps_taken=[
                "read_file (path=tests/test_x.py)",
                "bash (command=pytest -x)",
            ],
            resolution="added a lock around the shared fixture",
            agent_name="debugger_agent",
            db=mock_db,
        )

    assert mock_db.add.called
    added_row = mock_db.add.call_args.args[0]
    assert added_row.category == "procedure"
    assert added_row.outcome == "procedure"
    assert added_row.description == "flaky test failing intermittently in CI"
    assert "debugger_agent" in added_row.summary
    assert "added a lock" in added_row.summary
    assert "read_file" in added_row.summary
    assert result is not None


@pytest.mark.asyncio
async def test_embed_procedure_disabled_returns_none() -> None:
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        result = await embed_procedure(
            task_id="t",
            symptom="s",
            steps_taken=["a"],
            resolution="r",
            agent_name="qa",
            db=mock_db,
        )
    assert result is None
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_embed_procedure_db_error_returns_none() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock(side_effect=RuntimeError("db down"))
    mock_db.rollback = AsyncMock()

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.0] * 1536
        result = await embed_procedure(
            task_id="t",
            symptom="s",
            steps_taken=["a"],
            resolution="r",
            agent_name="qa",
            db=mock_db,
        )

    assert result is None
    assert mock_db.rollback.called


@pytest.mark.asyncio
async def test_query_procedures_returns_formatted_rows() -> None:
    mock_db = AsyncMock()
    fake_row = MagicMock()
    fake_row.task_id = "task-1"
    fake_row.epic_id = None
    fake_row.description = "flaky test"
    fake_row.summary = "Agent: debugger_agent\nResolution: added lock\nSteps:\n1. bash"
    fake_row.similarity = 0.91

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.1] * 1536
        results = await query_procedures("flaky test in CI", mock_db)

    assert len(results) == 1
    assert results[0]["task_id"] == "task-1"
    assert results[0]["symptom"] == "flaky test"
    assert "added lock" in results[0]["steps_and_resolution"]
    assert results[0]["similarity"] == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_query_procedures_disabled_returns_empty() -> None:
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        results = await query_procedures("q", mock_db)
    assert results == []


# ---------------------------------------------------------------------------
# format_full_memory_context — procedures section
# ---------------------------------------------------------------------------


def test_format_full_memory_context_includes_procedures_section() -> None:
    procedures = [
        {
            "task_id": "t-5",
            "epic_id": None,
            "symptom": "race condition in shared fixture",
            "steps_and_resolution": "Agent: debugger_agent\nResolution: added lock",
            "similarity": 0.88,
        }
    ]
    out = format_full_memory_context([], [], [], procedures)
    assert "Similar past repair procedures" in out
    assert "race condition" in out
    assert "added lock" in out


def test_format_full_memory_context_omits_procedures_when_none_or_empty() -> None:
    assert "repair procedures" not in format_full_memory_context([], [], [], [])
    assert "repair procedures" not in format_full_memory_context([], [], [], None)


# ---------------------------------------------------------------------------
# _extract_steps_taken — reconstructing the real tool-call sequence
# ---------------------------------------------------------------------------


def _state_with_messages(messages: list[dict[str, Any]]) -> AgentRunState:
    state: AgentRunState = {
        "messages": messages,
        "verification": {},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    return state


def test_extract_steps_taken_walks_assistant_tool_use_blocks_in_order() -> None:
    messages = [
        {"role": "user", "content": "fix the bug"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {
                    "type": "tool_use",
                    "name": "read_file",
                    "input": {"path": "app/x.py"},
                },
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "content": "..."}]},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "bash", "input": {"command": "pytest"}},
            ],
        },
    ]
    steps = _extract_steps_taken(_state_with_messages(messages))
    assert steps == ["read_file (path=app/x.py)", "bash (command=pytest)"]


def test_extract_steps_taken_empty_when_no_tool_calls() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert _extract_steps_taken(_state_with_messages(messages)) == []


# ---------------------------------------------------------------------------
# _maybe_store_procedure — the gating logic
# ---------------------------------------------------------------------------


def _submitted_state_with_tool_calls(**overrides: Any) -> AgentRunState:
    base: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": "fix the flaky test"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "bash", "input": {"command": "pytest"}}
                ],
            },
        ],
        "verification": {},
        "result": {"summary": "fixed by adding a lock"},
        "turns": 3,
        "submitted": True,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_maybe_store_procedure_skips_when_not_submitted() -> None:
    state = _submitted_state_with_tool_calls(
        submitted=False, reflection_unsatisfied_count=1
    )
    with patch("app.memory.store.embed_procedure", new=AsyncMock()) as mock_embed:
        _maybe_store_procedure(state, "debugger_agent", "task-1")
    mock_embed.assert_not_called()


def test_maybe_store_procedure_skips_when_no_iteration_needed() -> None:
    state = _submitted_state_with_tool_calls(
        reflection_unsatisfied_count=0, retry_count=0
    )
    with patch("app.memory.store.embed_procedure", new=AsyncMock()) as mock_embed:
        _maybe_store_procedure(state, "debugger_agent", "task-1")
    mock_embed.assert_not_called()


def test_maybe_store_procedure_skips_when_no_steps_extracted() -> None:
    state = _submitted_state_with_tool_calls(
        reflection_unsatisfied_count=1,
        messages=[{"role": "user", "content": "task"}],  # no tool_use blocks at all
    )
    with patch("app.memory.store.embed_procedure", new=AsyncMock()) as mock_embed:
        _maybe_store_procedure(state, "debugger_agent", "task-1")
    mock_embed.assert_not_called()


def test_maybe_store_procedure_stores_when_reflection_was_unsatisfied() -> None:
    state = _submitted_state_with_tool_calls(reflection_unsatisfied_count=1)
    with patch(
        "app.memory.store.embed_procedure", new=AsyncMock(return_value=object())
    ) as mock_embed:
        _maybe_store_procedure(state, "debugger_agent", "task-1")

    mock_embed.assert_called_once()
    kwargs = mock_embed.call_args.kwargs
    assert kwargs["task_id"] == "task-1"
    assert kwargs["agent_name"] == "debugger_agent"
    assert kwargs["steps_taken"] == ["bash (command=pytest)"]
    assert kwargs["resolution"] == "fixed by adding a lock"
    assert "flaky test" in kwargs["symptom"]


def test_maybe_store_procedure_stores_when_retry_count_positive() -> None:
    state = _submitted_state_with_tool_calls(
        reflection_unsatisfied_count=0, retry_count=1
    )
    with patch(
        "app.memory.store.embed_procedure", new=AsyncMock(return_value=object())
    ) as mock_embed:
        _maybe_store_procedure(state, "coder", "task-2")
    mock_embed.assert_called_once()


def test_maybe_store_procedure_is_non_fatal_on_store_failure() -> None:
    state = _submitted_state_with_tool_calls(reflection_unsatisfied_count=1)
    with patch(
        "app.memory.store.embed_procedure",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        _maybe_store_procedure(state, "debugger_agent", "task-1")  # must not raise
