"""Real-DB tests for T2-B2 (2026-09-22, GRIDIRON_PARTIAL #234 "Recovery
after crash (full state)").

Before this, Stop/Resume/Cancel lived entirely in ActivityStreamRegistry's
in-process threading.Event/dict (app/services/activity_stream.py) — real
within one process's lifetime, but a process crash or restart between "Stop
was clicked" and the agent loop observing it silently lost the signal: a
fresh process starts with an empty registry. These tests simulate exactly
that — write the flag through one ActivityStreamRegistry "process" instance,
then read it back through a SECOND, independent instance backed by nothing
but the real Postgres table — matching tests/test_orphan_recovery.py's own
real-DB convention rather than mocking.
"""

from __future__ import annotations

import asyncio

from app.db.repository import (
    get_task_control_flag_sync,
    pop_task_control_flag_resume_sync,
    set_task_control_flag_resume_sync,
    set_task_control_flag_stop_sync,
)
from app.services.activity_stream import ActivityStreamRegistry


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _cleanup(task_id: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import TaskControlFlag

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(TaskControlFlag).where(TaskControlFlag.task_id == task_id)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_stop_flag_survives_a_simulated_process_restart_real_db() -> None:
    """The core #234 claim: a Stop set by "process A" must still abort the
    run when "process B" (a fresh ActivityStreamRegistry — the same object a
    real process restart would create, since it's a module-level singleton)
    checks should_abort() for the same task_id, having never itself called
    set_abort()."""
    task_id = "t2b2-restart-stop-9001"
    _cleanup(task_id)
    try:
        process_a = ActivityStreamRegistry()
        assert process_a.set_abort(task_id) is False  # no stream existed yet
        stream_a = process_a.get_or_create(task_id)
        stream_a.set_abort()

        # Simulate a hard restart: a brand-new registry, zero in-memory state,
        # never told about task_id before.
        process_b = ActivityStreamRegistry()
        assert process_b.get(task_id) is None  # confirms no in-memory carryover
        assert process_b.should_abort(task_id) is True
    finally:
        _cleanup(task_id)


def test_clearing_abort_through_one_process_is_seen_by_a_fresh_one_real_db() -> None:
    task_id = "t2b2-restart-clear-9002"
    _cleanup(task_id)
    try:
        process_a = ActivityStreamRegistry()
        process_a.get_or_create(task_id).set_abort()

        process_b = ActivityStreamRegistry()
        assert process_b.should_abort(task_id) is True
        process_b.clear_abort(task_id)

        process_c = ActivityStreamRegistry()
        assert process_c.should_abort(task_id) is False
    finally:
        _cleanup(task_id)


def test_resume_payload_survives_a_simulated_process_restart_real_db() -> None:
    """A Resume message queued right before a crash must still be picked up
    (and consumed exactly once) by whichever process handles the resume."""
    task_id = "t2b2-restart-resume-9003"
    _cleanup(task_id)
    try:
        process_a = ActivityStreamRegistry()
        stream_a = process_a.get_or_create(task_id)
        stream_a.set_resume("please also handle the empty-input case", [])

        process_b = ActivityStreamRegistry()
        stream_b = process_b.get_or_create(task_id)
        # In-process pop_resume() was never called on this fresh stream —
        # this must come from the durable table, not from stream_a's memory.
        payload = stream_b.pop_resume()
        assert payload is not None
        assert payload["message"] == "please also handle the empty-input case"

        # Consumed exactly once — a second read (even via a third fresh
        # process) must not see it again.
        process_c = ActivityStreamRegistry()
        assert process_c.get_or_create(task_id).pop_resume() is None
    finally:
        _cleanup(task_id)


def test_repository_bridges_round_trip_directly_real_db() -> None:
    """Lower-level check of the repository bridges themselves, independent
    of ActivityStreamRegistry's caching — this is what a resume factory
    (T2-B2 core work) or a future admin endpoint would call directly."""
    task_id = "t2b2-repo-bridge-9004"
    _cleanup(task_id)
    try:
        assert get_task_control_flag_sync(task_id) is None

        set_task_control_flag_stop_sync(task_id, True)
        flag = get_task_control_flag_sync(task_id)
        assert flag is not None
        assert flag["stop_requested"] is True

        set_task_control_flag_resume_sync(task_id, "continue please", [{"path": "a.py"}])
        flag = get_task_control_flag_sync(task_id)
        assert flag is not None
        # set_resume clears stop_requested, mirroring TaskStream.set_resume()
        assert flag["stop_requested"] is False
        assert flag["resume_message"] == "continue please"

        popped = pop_task_control_flag_resume_sync(task_id)
        assert popped == {"message": "continue please", "files": [{"path": "a.py"}]}
        assert pop_task_control_flag_resume_sync(task_id) is None
    finally:
        _cleanup(task_id)


def test_write_through_works_from_inside_a_running_event_loop_real_db() -> None:
    """Regression guard for a real bug this change's own first test run
    caught: the *_sync repository bridges each do their own internal
    asyncio.run(...), which raises "cannot be called from a running event
    loop" when invoked from code that's already inside one — exactly what
    app/api/activity.py's async stop_task/resume_task/cancel_task route
    handlers do when they call a TaskStream method directly, synchronously.
    That exception was being silently swallowed by the write-through
    helpers' broad except-Exception, so a Stop/Resume set through the real
    API never actually reached this table at all. This test calls set_abort()
    from inside a real running event loop (an async test function) and
    confirms the write still lands — proving the actual production call
    shape, not just the sync-thread one every other test above exercises."""
    task_id = "t2b2-running-loop-9005"
    _cleanup(task_id)

    async def _inside_a_running_loop() -> None:
        registry = ActivityStreamRegistry()
        stream = registry.get_or_create(task_id)
        stream.set_abort()  # synchronous call, from inside this running loop

    try:
        asyncio.run(_inside_a_running_loop())

        # Fresh registry/process, reading purely from the durable table.
        fresh = ActivityStreamRegistry()
        assert fresh.should_abort(task_id) is True
    finally:
        _cleanup(task_id)
