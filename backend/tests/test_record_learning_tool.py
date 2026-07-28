"""Tests for MASTER_AGENT_v2.md Phase 1.4 — the record_learning tool.

Distinct from the automatic post-run memory hook (app/memory/hooks.py, Phase
1.1): this is an explicit, agent-controlled write path an agent calls mid-run
to flag a specific non-obvious finding. Covers the store-layer sync bridge
(embed_learning_signal_sync) and the tool handler factory
(make_record_learning_handler) that wraps it for use as a LangGraph tool.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.agents.tools import RECORD_LEARNING_TOOL, make_record_learning_handler
from app.memory.store import embed_learning_signal_sync

# ---------------------------------------------------------------------------
# RECORD_LEARNING_TOOL — schema shape
# ---------------------------------------------------------------------------


def test_record_learning_tool_schema_requires_finding() -> None:
    assert RECORD_LEARNING_TOOL["name"] == "record_learning"
    assert RECORD_LEARNING_TOOL["input_schema"]["required"] == ["finding"]
    assert "finding" in RECORD_LEARNING_TOOL["input_schema"]["properties"]
    assert "outcome" in RECORD_LEARNING_TOOL["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# embed_learning_signal_sync — the store-layer sync bridge
# ---------------------------------------------------------------------------


def test_embed_learning_signal_sync_returns_true_on_real_write() -> None:
    fake_row = object()
    with patch(
        "app.memory.store.embed_learning_signal", new=AsyncMock(return_value=fake_row)
    ):
        result = embed_learning_signal_sync(
            agent_name="debugger_agent",
            description="the flaky test was a real race, not a timing fluke",
            outcome_summary="added a lock around the shared fixture",
        )
    assert result is True


def test_embed_learning_signal_sync_returns_false_when_disabled_or_no_row() -> None:
    with patch(
        "app.memory.store.embed_learning_signal", new=AsyncMock(return_value=None)
    ):
        result = embed_learning_signal_sync(
            agent_name="debugger_agent", description="d", outcome_summary="o"
        )
    assert result is False


def test_embed_learning_signal_sync_returns_false_on_exception_never_raises() -> None:
    with patch(
        "app.memory.store.embed_learning_signal",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = embed_learning_signal_sync(
            agent_name="debugger_agent", description="d", outcome_summary="o"
        )
    assert result is False


# ---------------------------------------------------------------------------
# make_record_learning_handler — the tool handler agents actually call
# ---------------------------------------------------------------------------


def test_handler_rejects_empty_finding() -> None:
    handler = make_record_learning_handler("debugger_agent")
    result = handler({"finding": "   "})
    assert result.startswith("[ERROR]")


def test_handler_records_and_attributes_to_calling_agent() -> None:
    handler = make_record_learning_handler("debugger_agent")

    with patch(
        "app.memory.store.embed_learning_signal_sync", return_value=True
    ) as mock_sync:
        result = handler(
            {"finding": "root cause was a stale cache key", "outcome": "fixed"}
        )

    assert result == "Recorded."
    mock_sync.assert_called_once_with(
        agent_name="debugger_agent",
        description="root cause was a stale cache key",
        outcome_summary="fixed",
    )


def test_handler_defaults_outcome_when_omitted() -> None:
    handler = make_record_learning_handler("qa")

    with patch(
        "app.memory.store.embed_learning_signal_sync", return_value=True
    ) as mock_sync:
        handler({"finding": "flaky test needed a retry"})

    assert (
        mock_sync.call_args.kwargs["outcome_summary"]
        == "recorded during task execution"
    )


def test_handler_reports_error_when_store_write_fails() -> None:
    handler = make_record_learning_handler("qa")
    with patch("app.memory.store.embed_learning_signal_sync", return_value=False):
        result = handler({"finding": "something worth remembering"})
    assert result.startswith("[ERROR]")
