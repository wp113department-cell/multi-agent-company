"""T2-B10 (2026-09-24, GRIDIRON_PARTIAL #498/#484 "Roadmap tracked,
sequenced, and re-sequenced against real progress" / "Product Management
(roadmap/strategy)" — Task 1's own re-verification of both items,
DOWNGRADED: "roadmap_agent produces a one-shot LLM-written roadmap
document ... with no persisted Roadmap model, no sequence field, and no
mechanism that re-sequences it against real completed epics/tasks over
time — each run is independent, nothing is 'tracked' between runs.").

Real Postgres + real TestClient — no mocks for the DB itself.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.agents.roadmap_agent import (
    _fetch_latest_roadmap_context_sync,
    _persist_roadmap_sync,
)
from app.config import get_settings
from app.db.models import Repo, Roadmap, RoadmapItem
from app.db.repository import (
    create_roadmap,
    get_latest_roadmap_for_repo,
    update_roadmap_item_status,
)
from app.main import app
from app.middleware.rbac import require_approver, require_authenticated


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_repo_sync() -> tuple[int, str]:
    async def _run() -> tuple[int, str]:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                path = f"/tmp/t2b10-roadmap-{uuid.uuid4().hex[:8]}"
                repo = Repo(
                    github_url=f"https://github.com/test/t2b10-{uuid.uuid4().hex[:8]}",
                    name=f"t2b10-{uuid.uuid4().hex[:8]}",
                    local_path=path,
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                return repo.id, path
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(repo_id: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                roadmap_ids = (
                    await session.execute(
                        Roadmap.__table__.select().where(Roadmap.repo_id == repo_id)
                    )
                ).fetchall()
                for row in roadmap_ids:
                    await session.execute(
                        delete(RoadmapItem).where(RoadmapItem.roadmap_id == row.id)
                    )
                await session.execute(delete(Roadmap).where(Roadmap.repo_id == repo_id))
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


_SAMPLE_ITEMS = [
    {
        "phase": "Now",
        "initiative": "Ship the thing",
        "impact": "high",
        "effort": "medium",
        "confidence": "high",
        "dependencies": [],
    },
    {
        "phase": "Next",
        "initiative": "Ship the other thing",
        "impact": "medium",
        "effort": "low",
        "confidence": "medium",
        "dependencies": ["Ship the thing"],
    },
]


class TestRepositoryLayer:
    def test_create_and_read_back_a_real_roadmap(self) -> None:
        repo_id, _ = _make_repo_sync()
        try:

            async def _run() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        roadmap = await create_roadmap(
                            session, repo_id, None, "test summary", _SAMPLE_ITEMS
                        )
                        assert len(roadmap.items) == 2
                        assert roadmap.items[0].sequence_order == 0
                        assert roadmap.items[0].status == "planned"

                        latest = await get_latest_roadmap_for_repo(session, repo_id)
                        assert latest is not None
                        assert latest.id == roadmap.id
                        assert [i.initiative for i in latest.items] == [
                            "Ship the thing",
                            "Ship the other thing",
                        ]
                finally:
                    await engine.dispose()

            asyncio.run(_run())
        finally:
            _cleanup_sync(repo_id)

    def test_a_second_roadmap_is_the_new_latest(self) -> None:
        repo_id, _ = _make_repo_sync()
        try:

            async def _run() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        await create_roadmap(
                            session, repo_id, None, "v1", _SAMPLE_ITEMS
                        )
                        second = await create_roadmap(
                            session, repo_id, None, "v2", _SAMPLE_ITEMS[:1]
                        )
                        latest = await get_latest_roadmap_for_repo(session, repo_id)
                        assert latest is not None
                        assert latest.id == second.id
                        assert latest.summary == "v2"
                finally:
                    await engine.dispose()

            asyncio.run(_run())
        finally:
            _cleanup_sync(repo_id)

    def test_update_status_is_real_and_persisted(self) -> None:
        repo_id, _ = _make_repo_sync()
        try:

            async def _run() -> int:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        roadmap = await create_roadmap(
                            session, repo_id, None, "s", _SAMPLE_ITEMS
                        )
                        item_id = roadmap.items[0].id
                        ok = await update_roadmap_item_status(
                            session, item_id, "completed"
                        )
                        assert ok is True
                        return item_id
                finally:
                    await engine.dispose()

            item_id = asyncio.run(_run())

            async def _check() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        latest = await get_latest_roadmap_for_repo(session, repo_id)
                        assert latest is not None
                        by_id = {i.id: i for i in latest.items}
                        assert by_id[item_id].status == "completed"
                finally:
                    await engine.dispose()

            asyncio.run(_check())
        finally:
            _cleanup_sync(repo_id)

    def test_invalid_status_is_rejected_not_silently_applied(self) -> None:
        repo_id, _ = _make_repo_sync()
        try:

            async def _run() -> bool:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        roadmap = await create_roadmap(
                            session, repo_id, None, "s", _SAMPLE_ITEMS
                        )
                        return await update_roadmap_item_status(
                            session, roadmap.items[0].id, "not_a_real_status"
                        )
                finally:
                    await engine.dispose()

            assert asyncio.run(_run()) is False
        finally:
            _cleanup_sync(repo_id)

    def test_unknown_item_id_returns_false(self) -> None:
        async def _run() -> bool:
            engine = _engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    return await update_roadmap_item_status(
                        session, 99_999_999, "completed"
                    )
            finally:
                await engine.dispose()

        assert asyncio.run(_run()) is False


class TestRoadmapAgentPersistAndRereadWiring:
    def test_persist_then_fetch_context_reflects_real_status(self) -> None:
        repo_id, repo_path = _make_repo_sync()
        try:
            _persist_roadmap_sync(repo_path, None, "real summary", _SAMPLE_ITEMS)

            context = _fetch_latest_roadmap_context_sync(repo_path)
            assert "Ship the thing" in context
            assert "[planned]" in context

            async def _mark_completed() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        latest = await get_latest_roadmap_for_repo(session, repo_id)
                        assert latest is not None
                        await update_roadmap_item_status(
                            session, latest.items[0].id, "completed"
                        )
                finally:
                    await engine.dispose()

            asyncio.run(_mark_completed())

            context_after = _fetch_latest_roadmap_context_sync(repo_path)
            assert "[completed]" in context_after
        finally:
            _cleanup_sync(repo_id)

    def test_no_items_is_never_persisted(self) -> None:
        repo_id, repo_path = _make_repo_sync()
        try:
            _persist_roadmap_sync(repo_path, None, "empty summary", [])
            context = _fetch_latest_roadmap_context_sync(repo_path)
            assert context == ""
        finally:
            _cleanup_sync(repo_id)

    def test_unregistered_repo_path_is_a_silent_noop(self) -> None:
        # No real Repo row for this path — best-effort, never raises.
        _persist_roadmap_sync(
            f"/tmp/t2b10-unregistered-{uuid.uuid4().hex[:8]}", None, "s", _SAMPLE_ITEMS
        )
        context = _fetch_latest_roadmap_context_sync(
            f"/tmp/t2b10-unregistered-{uuid.uuid4().hex[:8]}"
        )
        assert context == ""


@pytest.fixture
def client():
    actor = f"t2b10-roadmap-user-{uuid.uuid4().hex[:8]}"
    app.dependency_overrides[require_authenticated] = lambda: actor
    app.dependency_overrides[require_approver] = lambda: actor
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(require_authenticated, None)
        app.dependency_overrides.pop(require_approver, None)


class TestRoadmapApi:
    def test_get_roadmap_with_no_data_returns_null(self, client: TestClient) -> None:
        repo_id, _ = _make_repo_sync()
        try:
            resp = client.get(f"/api/roadmap?repo_id={repo_id}")
            assert resp.status_code == 200
            assert resp.json()["roadmap"] is None
        finally:
            _cleanup_sync(repo_id)

    def test_get_roadmap_returns_the_real_persisted_items(
        self, client: TestClient
    ) -> None:
        repo_id, repo_path = _make_repo_sync()
        try:
            _persist_roadmap_sync(repo_path, None, "api test summary", _SAMPLE_ITEMS)

            resp = client.get(f"/api/roadmap?repo_id={repo_id}")
            assert resp.status_code == 200
            body = resp.json()["roadmap"]
            assert body is not None
            assert body["summary"] == "api test summary"
            assert len(body["items"]) == 2
            assert body["items"][0]["status"] == "planned"
        finally:
            _cleanup_sync(repo_id)

    def test_patch_item_status_round_trips_through_get(
        self, client: TestClient
    ) -> None:
        repo_id, repo_path = _make_repo_sync()
        try:
            _persist_roadmap_sync(repo_path, None, "s", _SAMPLE_ITEMS)
            item_id = client.get(f"/api/roadmap?repo_id={repo_id}").json()["roadmap"][
                "items"
            ][0]["id"]

            resp = client.patch(
                f"/api/roadmap/items/{item_id}/status", json={"status": "in_progress"}
            )
            assert resp.status_code == 200

            body = client.get(f"/api/roadmap?repo_id={repo_id}").json()["roadmap"]
            assert body["items"][0]["status"] == "in_progress"
        finally:
            _cleanup_sync(repo_id)

    def test_patch_invalid_status_is_a_422(self, client: TestClient) -> None:
        repo_id, repo_path = _make_repo_sync()
        try:
            _persist_roadmap_sync(repo_path, None, "s", _SAMPLE_ITEMS)
            item_id = client.get(f"/api/roadmap?repo_id={repo_id}").json()["roadmap"][
                "items"
            ][0]["id"]

            resp = client.patch(
                f"/api/roadmap/items/{item_id}/status", json={"status": "bogus"}
            )
            assert resp.status_code == 422
        finally:
            _cleanup_sync(repo_id)

    def test_get_roadmap_requires_a_scope(self, client: TestClient) -> None:
        resp = client.get("/api/roadmap")
        assert resp.status_code == 422
