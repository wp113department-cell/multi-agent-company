"""AUDIT_Q_BATCH18 Bonus-table row 2 gap-closure (2026-08-12) — "In-process
singletons block horizontal scaling": LessonStore was purely in-process,
so lessons learned by one backend process's agents were invisible to
another's. Tests the real DB write-through (_persist_lesson_async, via the
main-loop cross-thread dispatch pattern) and read-refresh
(LessonStore.refresh_from_db) against a real DB.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agents.base_graph import Lesson, LessonStore, _persist_lesson_async


def _engine():  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _cleanup_lessons(engine, category: str) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(
            text("DELETE FROM lessons WHERE category = :category"),
            {"category": category},
        )
        await conn.commit()


async def _poll_for_lesson_rows(
    engine, category: str, *, timeout_s: float = 5.0
):  # type: ignore[no-untyped-def]
    """_persist_lesson_async schedules the real write via
    run_coroutine_threadsafe rather than awaiting it directly (that's the
    whole point — non-blocking for the caller), so the exact moment it
    lands is not deterministic. Polls instead of a single fixed sleep,
    which was observed to be genuinely flaky (the write reliably lands
    around ~0.5s, sometimes just past it) under real test-environment
    load, not a structural bug in the write path itself."""
    from sqlalchemy import text

    elapsed = 0.0
    interval = 0.25
    while elapsed < timeout_s:
        await asyncio.sleep(interval)
        elapsed += interval
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT lesson FROM lessons WHERE category = :c"),
                {"c": category},
            )
            rows = result.fetchall()
        if rows:
            return rows
    return rows


class TestPersistLessonAsync:
    @pytest.mark.asyncio
    async def test_writes_a_real_row_when_a_main_loop_is_running(self) -> None:
        """Simulates the real production shape: a running event loop
        registered as the 'main loop' (fleet_events.get_main_loop(), the
        same mechanism AgentRegistry._notify_agent_retired already relies
        on), called from a plain synchronous context (mirrors calling from
        a worker thread with no loop of its own)."""
        from app.fleet import fleet_events

        category = f"batch18_persist_{uuid.uuid4().hex[:8]}"
        lesson = Lesson(
            agent_name="test_agent",
            lesson="always check the return value",
            pattern="error handling",
            category=category,
        )

        loop = asyncio.get_running_loop()
        fleet_events.set_main_loop(loop)
        try:
            _persist_lesson_async(lesson)
            engine = _engine()
            try:
                rows = await _poll_for_lesson_rows(engine, category)
                assert len(rows) == 1
                assert rows[0][0] == "always check the return value"
            finally:
                await _cleanup_lessons(engine, category)
                await engine.dispose()
        finally:
            fleet_events.set_main_loop(None)

    def test_no_loop_anywhere_is_a_safe_noop(self) -> None:
        """No running loop in this thread AND no registered main loop —
        the common case for a freshly-imported test module — must not
        raise."""
        lesson = Lesson(
            agent_name="test_agent",
            lesson="x",
            pattern="y",
            category="z",
        )
        _persist_lesson_async(lesson)  # must not raise


class TestRefreshFromDb:
    @pytest.mark.asyncio
    async def test_merges_rows_written_by_another_process(self) -> None:
        """Simulates 'another process' by inserting directly via SQL (not
        through this LessonStore instance at all), then proving THIS
        LessonStore's refresh_from_db() picks it up."""
        category = f"batch18_refresh_{uuid.uuid4().hex[:8]}"
        engine = _engine()
        try:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO lessons (agent_name, lesson, pattern, category, reusable) "
                        "VALUES ('other_process_agent', 'lesson from elsewhere', "
                        "'pattern', :category, true)"
                    ),
                    {"category": category},
                )
                await conn.commit()

            store = LessonStore(capacity=100)
            assert store.total == 0

            merged = await store.refresh_from_db()

            assert merged >= 1
            retrieved = store.retrieve("lesson from elsewhere", top_k=5)
            assert any(ls.category == category for ls in retrieved)
        finally:
            await _cleanup_lessons(engine, category)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_refresh_does_not_repersist_merged_rows(self) -> None:
        """A row merged FROM the DB must not be written back to the DB —
        otherwise every refresh cycle across every process would grow the
        table by re-inserting everyone else's lessons forever."""
        from unittest.mock import patch

        category = f"batch18_norepersist_{uuid.uuid4().hex[:8]}"
        engine = _engine()
        try:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO lessons (agent_name, lesson, pattern, category, reusable) "
                        "VALUES ('other_process_agent', 'do not duplicate me', "
                        "'pattern', :category, true)"
                    ),
                    {"category": category},
                )
                await conn.commit()

            store = LessonStore(capacity=100)
            with patch("app.agents.base_graph._persist_lesson_async") as mock_persist:
                merged = await store.refresh_from_db()

            assert merged >= 1
            mock_persist.assert_not_called()
        finally:
            await _cleanup_lessons(engine, category)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_refresh_is_incremental_via_last_synced_id(self) -> None:
        category = f"batch18_incremental_{uuid.uuid4().hex[:8]}"
        engine = _engine()
        try:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO lessons (agent_name, lesson, pattern, category, reusable) "
                        "VALUES ('other_process_agent', 'first lesson', 'p', :category, true)"
                    ),
                    {"category": category},
                )
                await conn.commit()

            store = LessonStore(capacity=100)
            first_merge = await store.refresh_from_db()
            assert first_merge >= 1

            second_merge_no_new_rows = await store.refresh_from_db()
            assert second_merge_no_new_rows == 0

            async with engine.connect() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO lessons (agent_name, lesson, pattern, category, reusable) "
                        "VALUES ('other_process_agent', 'second lesson', 'p', :category, true)"
                    ),
                    {"category": category},
                )
                await conn.commit()

            third_merge = await store.refresh_from_db()
            assert third_merge == 1
        finally:
            await _cleanup_lessons(engine, category)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_query_failure_returns_zero_not_raise(self) -> None:
        from unittest.mock import patch

        store = LessonStore(capacity=100)
        with patch(
            "app.db.session.get_session_factory",
            side_effect=RuntimeError("db down"),
        ):
            merged = await store.refresh_from_db()
        assert merged == 0
