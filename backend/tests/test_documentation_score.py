"""GRIDIRON_PARTIAL #414 re-verification (2026-09-28) — app/fleet/
documentation_score.py, the "documentation" category's real, non-
fabricated quality-score producer, closed once #457's doc_coverage.py
(2026-09-25) started publishing real, repo-scoped
"subtask.advisory_gate_completed"/"subtask.advisory_gate_blocked" events
(gate="documentation") to the real `events` table.

Tested against real Postgres (its only real dependency is the `events`
table's own repo_id scoping, populated here directly rather than by
running the full agent pipeline — that pipeline's own gate-triggering
logic is app/agents/manager.py's concern, already covered elsewhere).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import DocumentationScore, Event, Repo
from app.fleet.documentation_score import (
    compute_documentation_score,
    get_latest_documentation_score,
)
from app.fleet.quality_score import get_quality_score


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_repo_sync() -> int:
    async def _run() -> int:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/doc-score-{uuid.uuid4().hex[:8]}",
                    name=f"doc-score-{uuid.uuid4().hex[:8]}",
                    local_path=f"/tmp/doc-score-{uuid.uuid4().hex[:8]}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                return repo.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_gate_event_sync(
    repo_id: int, event_type: str, undocumented_count: int
) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                session.add(
                    Event(
                        event_id=str(uuid.uuid4()),
                        event_type=event_type,
                        task_id="999",
                        payload={
                            "subtask_id": 1,
                            "gate": "documentation",
                            "undocumented_count": undocumented_count,
                        },
                        emitted_by="doc_coverage",
                        repo_id=repo_id,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _cleanup_sync(repo_id: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(Event).where(Event.repo_id == repo_id)
                )
                await session.execute(
                    delete(DocumentationScore).where(
                        DocumentationScore.repo_id == repo_id
                    )
                )
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


class TestDocumentationScore:
    def test_returns_none_with_no_gate_events(self) -> None:
        repo_id = _make_repo_sync()
        try:

            async def _check() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        result = await compute_documentation_score(repo_id, session)
                        assert result is None
                finally:
                    await engine.dispose()

            asyncio.run(_check())
        finally:
            _cleanup_sync(repo_id)

    def test_mixed_passed_and_blocked_computes_real_pass_rate(self) -> None:
        repo_id = _make_repo_sync()
        try:
            _seed_gate_event_sync(
                repo_id, "subtask.advisory_gate_completed", undocumented_count=0
            )
            _seed_gate_event_sync(
                repo_id, "subtask.advisory_gate_completed", undocumented_count=1
            )
            _seed_gate_event_sync(
                repo_id, "subtask.advisory_gate_blocked", undocumented_count=9
            )

            async def _check() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        return await compute_documentation_score(repo_id, session)
                finally:
                    await engine.dispose()

            result = asyncio.run(_check())
            assert result is not None
            assert result.gate_count == 3
            assert result.blocked_count == 1
            assert result.documentation_score == pytest.approx(2 / 3)
        finally:
            _cleanup_sync(repo_id)

    def test_events_outside_window_are_excluded(self) -> None:
        repo_id = _make_repo_sync()
        try:
            _seed_gate_event_sync(
                repo_id, "subtask.advisory_gate_blocked", undocumented_count=5
            )

            async def _backdate_and_check() -> object:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        from sqlalchemy import update

                        await session.execute(
                            update(Event)
                            .where(Event.repo_id == repo_id)
                            .values(
                                created_at=datetime.now(timezone.utc)
                                - timedelta(days=60)
                            )
                        )
                        await session.commit()
                        return await compute_documentation_score(
                            repo_id, session, window_days=30
                        )
                finally:
                    await engine.dispose()

            result = asyncio.run(_backdate_and_check())
            assert result is None
        finally:
            _cleanup_sync(repo_id)

    def test_store_and_read_latest_round_trips_through_real_postgres(self) -> None:
        repo_id = _make_repo_sync()
        try:
            assert get_latest_documentation_score(repo_id) is None

            _seed_gate_event_sync(
                repo_id, "subtask.advisory_gate_completed", undocumented_count=0
            )

            async def _compute_and_persist() -> None:
                from app.fleet.documentation_score import _persist

                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        result = await compute_documentation_score(repo_id, session)
                        assert result is not None
                        # store_documentation_score's own asyncio.run() bridge
                        # can't be called from inside this already-running
                        # event loop — call the async _persist directly
                        # instead, exactly what the sync bridge itself does.
                        await _persist(repo_id, result)
                finally:
                    await engine.dispose()

            asyncio.run(_compute_and_persist())

            latest = get_latest_documentation_score(repo_id)
            assert latest is not None
            assert latest.documentation_score == pytest.approx(1.0)

            qs = get_quality_score(repo_id)
            by_name = {c.name: c for c in qs.categories}
            assert by_name["documentation"].status == "available"
            assert by_name["documentation"].score == pytest.approx(1.0)
            # "performance" remains the one genuinely unimplemented category.
            assert by_name["performance"].status == "unavailable"
            assert by_name["performance"].reason == "not_implemented"
        finally:
            _cleanup_sync(repo_id)
