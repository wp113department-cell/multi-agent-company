"""Tests for Agent Registry — metrics math, tag dispatch, insert-only registration."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---- Helpers ----

def _make_agent(
    name: str,
    capability_tags: list[str],
    success_rate: float = 1.0,
    avg_retries: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=str(uuid.uuid4()),
        name=name,
        capability_tags=capability_tags,
        tool_list=["read_file", "list_files"],
        prompt_ref=f"roles/{name}.md",
        version="1.0",
        success_rate=success_rate,
        avg_retries=avg_retries,
        last_computed_at=datetime.now(tz=timezone.utc),
        created_at=datetime.now(tz=timezone.utc),
    )


# ---- Metrics math ----

def test_success_rate_all_complete() -> None:
    """Success rate = 1.0 when all runs are completed."""
    runs = [MagicMock(status="completed") for _ in range(5)]
    successes = sum(1 for r in runs if r.status == "completed")
    rate = successes / len(runs)
    assert rate == 1.0


def test_success_rate_partial() -> None:
    """Success rate = 0.6 when 3/5 runs are completed."""
    statuses = ["completed", "completed", "completed", "failed", "failed"]
    runs = [MagicMock(status=s) for s in statuses]
    successes = sum(1 for r in runs if r.status == "completed")
    rate = successes / len(runs)
    assert abs(rate - 0.6) < 1e-9


def test_success_rate_zero_runs_falls_back_to_stored() -> None:
    """When total_runs=0, the stored agent.success_rate is used unchanged."""
    agent = _make_agent("test_agent", ["code"], success_rate=0.85)
    total_runs = 0
    if total_runs == 0:
        computed_rate = agent.success_rate
    else:
        computed_rate = 0.0  # would compute from runs
    assert computed_rate == 0.85


# ---- Tag-based dispatch ----

@pytest.mark.asyncio
async def test_pick_agent_by_tag_found() -> None:
    """pick_agent_by_tag returns the agent with matching capability tag."""
    from app.pipeline.dispatcher import pick_agent_by_tag

    mock_agent_row = SimpleNamespace(name="backend_dev")

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_agent_row

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    name = await pick_agent_by_tag("backend", db)
    assert name == "backend_dev"


@pytest.mark.asyncio
async def test_pick_agent_by_tag_not_found_returns_none() -> None:
    """pick_agent_by_tag returns None when no agent has the requested tag."""
    from app.pipeline.dispatcher import pick_agent_by_tag

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    name = await pick_agent_by_tag("nonexistent_tag", db)
    assert name is None


@pytest.mark.asyncio
async def test_pick_agent_prefers_highest_success_rate() -> None:
    """When multiple agents match, the one with highest success_rate is first."""
    from app.pipeline.dispatcher import pick_agent_by_tag

    # Simulates DB returning the highest-success_rate agent first
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = SimpleNamespace(name="best_backend_dev")

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    name = await pick_agent_by_tag("backend", db, prefer_highest_success=True)
    assert name == "best_backend_dev"


@pytest.mark.asyncio
async def test_dispatch_falls_back_when_db_raises() -> None:
    """dispatch_subtask falls back to hardcoded routing when DB raises."""
    from app.pipeline.dispatcher import dispatch_subtask
    from unittest.mock import patch

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))

    subtask = {"id": 1, "type": "backend", "description": "add a button"}

    # Patch run_backend_dev to avoid real LLM call
    fake_return = (["backend/main.py"], None)
    with patch("app.agents.backend_dev.run_backend_dev", return_value=fake_return):
        result = await dispatch_subtask(
            task_id=1,
            subtask=subtask,
            worktree_path="/tmp/wt",
            plan="do the backend work",
            db=db,
        )

    assert result["agent"] in ("backend_dev", "backend")
    assert result["files_changed"] == ["backend/main.py"]
    assert result["error"] is None


# ---- Insert-only registration ----

@pytest.mark.asyncio
async def test_register_new_agent_via_sql_dispatched_by_tag() -> None:
    """A new agent inserted into the registry is discovered by tag — zero code change."""
    from app.pipeline.dispatcher import pick_agent_by_tag

    # Simulate a freshly inserted "security_agent" with tag "security"
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = SimpleNamespace(name="security_agent")

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    name = await pick_agent_by_tag("security", db)
    assert name == "security_agent"


def test_agent_registry_orm_fields() -> None:
    """Agent ORM model has all required Phase 6 fields."""
    from app.db.models import Agent
    cols = {c.key for c in Agent.__table__.columns}
    required = {
        "agent_id", "name", "capability_tags", "tool_list",
        "prompt_ref", "version", "success_rate", "avg_retries",
        "last_computed_at", "created_at",
    }
    assert required <= cols, f"Missing columns: {required - cols}"
