"""T2-B10 (2026-09-24, GRIDIRON_PARTIAL #426 "Pause / Resume / Cancel" —
Task 1's own re-verification of this item, DOWNGRADED after proving live
with two real subprocesses that a Stop set in one process was invisible in
another).

T2-B2's own durable task_control_flags mechanism (tests/
test_t2b2_control_flags_durability.py) only proved the CRASH-RECOVERY half
of this: a brand-new process/registry starting AFTER a Stop was already
durably recorded correctly picks it up. It did NOT prove the LIVE half —
the actual QUEUE_BACKEND=rq scenario Task 1's own #426 verification used:
an ALREADY-RUNNING worker process, mid-run, with a Stop clicked from a
DIFFERENT (API) process WHILE the worker is still executing.

Reproduced live before this fix (see git history for this file's own
introduction): a TaskStream's should_abort() cached its one cold DB read
forever (`_abort_db_synced = True` after the first check, whatever it
found) — an already-running worker that checked once before a Stop was
set would never see that Stop for the rest of its life, since
should_abort() never touched the DB again after its first call. Fixed by
replacing the one-shot cache with a throttled periodic re-check
(_ABORT_DB_RECHECK_INTERVAL_SECONDS, app/services/activity_stream.py) —
these tests prove BOTH that the live case is now caught (within the
throttle window) AND that the "no unmatched every-single-turn DB hit"
property is preserved (a check inside the throttle window still costs
zero DB round trips beyond the first).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from app.services.activity_stream import (
    _ABORT_DB_RECHECK_INTERVAL_SECONDS,
    ActivityStreamRegistry,
)


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


def test_an_already_running_worker_eventually_observes_a_live_stop_real_db() -> None:
    task_id = "t2b10-live-stop-9101"
    _cleanup(task_id)
    try:
        # "process B" — a real worker, already running, checks should_abort()
        # once BEFORE any Stop exists (this is what a long-running rq worker
        # does on its very first turn).
        process_b = ActivityStreamRegistry()
        assert process_b.should_abort(task_id) is False

        # "process A" — a separate API process — sets a real Stop moments
        # later, entirely independent of process_b's own in-memory state.
        process_a = ActivityStreamRegistry()
        process_a.get_or_create(task_id).set_abort()

        # Immediately after: still within the throttle window, so process_b
        # correctly has NOT yet re-read the DB — proves this isn't an
        # unthrottled per-call DB hit.
        assert process_b.should_abort(task_id) is False

        # Past the throttle window: the SAME process_b instance (no restart,
        # no new registry) now genuinely observes the live Stop.
        time.sleep(_ABORT_DB_RECHECK_INTERVAL_SECONDS + 0.2)
        assert process_b.should_abort(task_id) is True
    finally:
        _cleanup(task_id)


def test_within_the_throttle_window_should_abort_never_touches_the_db() -> None:
    """A regression guard on the OTHER real requirement (T2-B2's own
    original design goal): call_llm calls should_abort() every turn — this
    must not become an unthrottled DB round trip per turn."""
    task_id = "t2b10-throttle-9102"
    _cleanup(task_id)
    try:
        registry = ActivityStreamRegistry()
        stream = registry.get_or_create(task_id)
        assert stream.should_abort() is False  # the one real cold read

        with patch(
            "app.services.activity_stream.TaskStream._read_through_stop"
        ) as mock_read:
            for _ in range(50):
                assert stream.should_abort() is False
            mock_read.assert_not_called()
    finally:
        _cleanup(task_id)


def test_once_aborted_stays_aborted_without_further_db_reads() -> None:
    task_id = "t2b10-sticky-9103"
    _cleanup(task_id)
    try:
        registry = ActivityStreamRegistry()
        stream = registry.get_or_create(task_id)
        stream.set_abort()
        assert stream.should_abort() is True

        with patch(
            "app.services.activity_stream.TaskStream._read_through_stop"
        ) as mock_read:
            assert stream.should_abort() is True
            mock_read.assert_not_called()
    finally:
        _cleanup(task_id)
