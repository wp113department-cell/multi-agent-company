"""Database integration tests — require a real Postgres (DATABASE_URL pointing to localhost)."""

from __future__ import annotations

import uuid
from tests.pending.conftest import requires_db


@requires_db
class TestDBIntegration:
    """Full CRUD + state transition tests against a real Postgres database."""

    async def test_create_and_fetch_task(self) -> None:
        """Create a task via DB layer, fetch it, verify fields round-trip."""
        from app.db.session import get_async_session
        from app.db.models import DevTask

        async with get_async_session() as session:
            task = DevTask(
                title="Integration test task",
                description="Created by test_db_integration.py",
                status="pending",
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            assert task.id is not None
            assert task.title == "Integration test task"
            assert task.status == "pending"

            await session.delete(task)
            await session.commit()

    async def test_task_log_append(self) -> None:
        """Append a log entry to a task and fetch it back."""
        from app.db.session import get_async_session
        from app.db.models import DevTask, TaskLog

        async with get_async_session() as session:
            task = DevTask(title="Log test", description="x", status="pending")
            session.add(task)
            await session.commit()
            await session.refresh(task)

            log = TaskLog(
                task_id=task.id,
                category="planning",
                message="Plan started",
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)

            assert log.id is not None
            assert log.task_id == task.id
            assert log.category == "planning"

            await session.delete(log)
            await session.delete(task)
            await session.commit()

    async def test_valid_status_transition_in_db(self) -> None:
        """Status can be transitioned from pending → planning in the DB layer."""
        from app.db.session import get_async_session
        from app.db.models import DevTask, VALID_TRANSITIONS

        async with get_async_session() as session:
            task = DevTask(title="Transition test", description="x", status="pending")
            session.add(task)
            await session.commit()
            await session.refresh(task)

            assert "planning" in VALID_TRANSITIONS["pending"]
            task.status = "planning"
            await session.commit()
            await session.refresh(task)
            assert task.status == "planning"

            await session.delete(task)
            await session.commit()

    async def test_agent_run_record(self) -> None:
        """Create an AgentRun record linked to a task."""
        from app.db.session import get_async_session
        from app.db.models import DevTask, AgentRun

        async with get_async_session() as session:
            task = DevTask(title="Agent run test", description="x", status="planning")
            session.add(task)
            await session.commit()
            await session.refresh(task)

            run_id = f"run-{uuid.uuid4()}"
            run = AgentRun(
                id=run_id,
                task_id=task.id,
                agent_type="planner",
                status="running",
                tokens_in=100,
                tokens_out=50,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            assert run.id == run_id
            assert run.agent_type == "planner"
            assert run.tokens_in == 100

            await session.delete(run)
            await session.delete(task)
            await session.commit()

    async def test_subtask_linked_to_parent(self) -> None:
        """Create a subtask linked to a parent DevTask."""
        from app.db.session import get_async_session
        from app.db.models import DevTask, Subtask

        async with get_async_session() as session:
            parent = DevTask(title="Parent task", description="x", status="planning")
            session.add(parent)
            await session.commit()
            await session.refresh(parent)

            sub = Subtask(
                task_id=parent.id,
                type="test",
                title="Sub: write tests",
                description="Write pytest tests",
                status="pending",
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)

            assert sub.id is not None
            assert sub.task_id == parent.id
            assert sub.type == "test"

            await session.delete(sub)
            await session.delete(parent)
            await session.commit()
