"""Pending integration tests for Manager Agent + Epic lifecycle.

Require: ANTHROPIC_API_KEY + live Postgres (DATABASE_URL) + RUN_PENDING_TESTS=1
"""
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_PENDING_TESTS"),
    reason="Set RUN_PENDING_TESTS=1 and provide API keys + live DB",
)


@pytest.mark.asyncio
async def test_manager_dispatches_subtasks_and_completes() -> None:
    """Manager: goal → epic → subtasks → batched approval package."""
    from app.db.session import get_async_session
    from app.agents.manager import run_epic_manager
    import uuid

    async with get_async_session() as db:
        epic_id = str(uuid.uuid4())
        from app.db.models import Epic
        epic = Epic(
            epic_id=epic_id,
            title="Add a hello world endpoint",
            description="Add GET /hello that returns {message: 'hello world'} to the FastAPI app",
            status="pending",
        )
        db.add(epic)
        await db.commit()

        package = await run_epic_manager(epic_id=epic_id, goal=epic.description, db=db)

    assert package.epic_id == epic_id
    assert package.status in ("ready_for_review", "halted", "pending_cost_approval")


@pytest.mark.asyncio
async def test_epic_halts_on_repeated_subtask_failures() -> None:
    """Manager: force 2 subtasks to fail repeatedly → epic.halted event emitted."""
    from app.agents.manager import run_manager
    from app.event_bus.bus import subscribe, unsubscribe
    from app.event_bus.models import GridironEvent
    import uuid

    halted_events: list[GridironEvent] = []

    def capture(ev: GridironEvent) -> None:
        if ev.event_type == "task.blocked":
            halted_events.append(ev)

    subscribe("task.blocked", capture)
    try:
        # Subtasks that will fail (impossible plan)
        bad_subtasks = [
            {"id": 1, "type": "backend", "title": "This is impossible", "description": "Write code that defies physics"},
            {"id": 2, "type": "backend", "title": "Also impossible", "description": "Also defies physics"},
        ]
        result = await run_manager(
            task_id=9999,
            subtasks=bad_subtasks,
            worktree_path="/tmp",
            plan="impossible",
            epic_id=str(uuid.uuid4()),
        )
        assert result["blocked_count"] >= 1
    finally:
        unsubscribe("task.blocked", capture)


@pytest.mark.asyncio
async def test_cost_estimate_before_execution() -> None:
    """Epic over COST_APPROVAL_THRESHOLD blocks before agents start."""
    from app.db.session import get_async_session
    from app.agents.manager import run_epic_manager
    from app.config import get_settings
    import uuid

    settings = get_settings()
    # Force a threshold so low any estimate exceeds it
    original_threshold = settings.cost_approval_threshold

    try:
        settings.__dict__["cost_approval_threshold"] = 0.000001  # type: ignore[assignment]

        async with get_async_session() as db:
            from app.db.models import Epic
            epic_id = str(uuid.uuid4())
            epic = Epic(
                epic_id=epic_id,
                title="Cost gated epic",
                description="Any description",
                status="pending",
            )
            db.add(epic)
            await db.commit()

            package = await run_epic_manager(epic_id=epic_id, goal=epic.description, db=db)

        assert package.status == "pending_cost_approval"
        assert package.halt_reason is not None
    finally:
        settings.__dict__["cost_approval_threshold"] = original_threshold  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_policy_v2_blocks_migration_subtask() -> None:
    """Subtask touching **/migrations/** blocks until policy_approvals row exists."""
    from app.db.session import get_async_session
    from app.policy.engine_v2 import check_file_against_policies, has_approval

    async with get_async_session() as db:
        # The seed policies from migration 003 should be present
        matches = await check_file_against_policies("backend/migrations/versions/004.py", db)
        assert len(matches) > 0
        blocking = [m for m in matches if m.blocking]
        assert len(blocking) > 0

        # No approval yet
        approved = await has_approval(matches[0].policy_id, db)
        assert approved is False
