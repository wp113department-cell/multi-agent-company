"""Stage 4 Cluster R Phase 1 (2026-08-05, STAGE4_BACKLOG.md / CLUSTER_R_DESIGN.md)
— Epic.repo_id: schema + API-schema only.

Phase 1 scope (explicit user instruction — execution-path wiring is Phase
2, not covered here): migration 031, the nullable `Epic.repo_id` column +
`repo` relationship, `CreateEpicRequest.repo_id`, and backward
compatibility for epics created before this migration (repo_id=NULL,
identical real behavior to today).

Real migration was actually run against this environment's live Postgres
(`alembic upgrade head`) before this file was written, and the resulting
schema (column/FK/index) was verified directly via information_schema
queries — not just authored and assumed to work, same discipline as
test_stage4_tier3_dev_tasks_priority_enforcement.py's own migration-317
precedent for this constraint-testing style.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.epics import CreateEpicRequest
from app.db.models import Epic, Repo
from app.db.session import new_isolated_async_engine

# ---------------------------------------------------------------------------
# Pydantic layer — CreateEpicRequest
# ---------------------------------------------------------------------------


def test_pydantic_layer_default_repo_id_is_none() -> None:
    """Backward compatibility: any caller that doesn't send repo_id at all
    (including today's frontend, until it's updated) must keep working
    exactly as before this change."""
    req = CreateEpicRequest(title="t", description="d")
    assert req.repo_id is None


def test_pydantic_layer_accepts_a_real_int_repo_id() -> None:
    req = CreateEpicRequest(title="t", description="d", repo_id=42)
    assert req.repo_id == 42


def test_pydantic_layer_rejects_a_non_integer_repo_id() -> None:
    with pytest.raises(ValidationError):
        CreateEpicRequest(title="t", description="d", repo_id="not-an-int")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Real-Postgres helpers
# ---------------------------------------------------------------------------


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterr-{suffix}",
                    name=f"clusterr-{suffix}",
                    local_path=f"/tmp/clusterr-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _make_epic_sync(suffix: str, repo_id: int | None) -> str:
    async def _run() -> str:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                epic_id = str(uuid.uuid4())
                session.add(
                    Epic(
                        epic_id=epic_id,
                        title=f"cluster r phase 1 test {suffix}",
                        description="d",
                        status="pending",
                        repo_id=repo_id,
                    )
                )
                await session.commit()
                return epic_id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _read_epic_repo_id_sync(epic_id: str) -> int | None:
    async def _run() -> int | None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(Epic.repo_id).where(Epic.epic_id == epic_id)
                )
                return result.scalar_one_or_none()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(epic_ids: list[str], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(Epic).where(Epic.epic_id.in_(epic_ids)))
                await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Real-Postgres — legacy epics (repo_id=NULL) keep working unchanged
# ---------------------------------------------------------------------------


def test_legacy_epic_with_no_repo_id_persists_and_reads_back_none() -> None:
    """The exact backward-compatibility guarantee this phase must not
    break: an epic created without a repo (today's only real path) must
    continue to insert cleanly and read back repo_id=NULL, not fail or
    silently default to something else."""
    suffix = uuid.uuid4().hex[:8]
    epic_id = _make_epic_sync(suffix, repo_id=None)

    try:
        assert _read_epic_repo_id_sync(epic_id) is None
    finally:
        _cleanup_sync([epic_id], [])


# ---------------------------------------------------------------------------
# Real-Postgres — new epics (repo_id populated)
# ---------------------------------------------------------------------------


def test_new_epic_with_a_real_repo_id_persists_and_reads_back_correctly() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    epic_id = _make_epic_sync(suffix, repo_id=repo_id)

    try:
        assert _read_epic_repo_id_sync(epic_id) == repo_id
    finally:
        _cleanup_sync([epic_id], [repo_id])


def test_fk_constraint_rejects_a_nonexistent_repo_id_via_direct_sql() -> None:
    """Proves the real FK constraint (fk_epics_repo_id_repos), not just
    that the column accepts integers -- covers any write path that
    bypasses the ORM entirely, same style as the priority CHECK
    constraint's own direct-SQL proof."""

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with engine.connect() as conn:
                with pytest.raises(Exception, match="fk_epics_repo_id_repos"):
                    await conn.execute(
                        text(
                            "INSERT INTO epics (epic_id, title, description, status, repo_id) "
                            "VALUES (:epic_id, 'x', 'x', 'pending', 999999999)"
                        ),
                        {"epic_id": str(uuid.uuid4())},
                    )
                    await conn.commit()
                await conn.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_deleting_the_referenced_repo_sets_epic_repo_id_to_null() -> None:
    """Proves the real ondelete=SET NULL behavior end-to-end -- an epic
    scoped to a repo that later gets removed must not become a dangling
    FK or block the repo's deletion; it must fall back to the same
    unscoped state a legacy epic already has."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    epic_id = _make_epic_sync(suffix, repo_id=repo_id)

    async def _delete_repo() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    try:
        assert _read_epic_repo_id_sync(epic_id) == repo_id
        asyncio.run(_delete_repo())
        assert _read_epic_repo_id_sync(epic_id) is None
    finally:
        _cleanup_sync([epic_id], [])


# ---------------------------------------------------------------------------
# API layer -- POST /api/epics through the real HTTP endpoint, real Postgres
# ---------------------------------------------------------------------------


class TestCreateEpicApiRepoId:
    @pytest.fixture(autouse=True)
    def _reset_db_engine_between_tests(self):  # type: ignore[no-untyped-def]
        yield
        import app.db.session as _sess

        _sess._engine = None
        _sess._session_factory = None

    def test_create_epic_with_repo_id_persists_and_is_returned(self) -> None:
        """End-to-end through the real HTTP endpoint: the background epic-
        manager pipeline (_launch_epic_manager) is patched out -- Phase 1
        is schema/API-schema only, exercising the real orchestration graph
        is explicitly Phase 2 scope -- but epic creation, persistence, and
        the response shape are all real."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        repo_id = _make_repo_sync(suffix)
        epic_id: str | None = None
        try:
            with (
                patch("app.api.epics._launch_epic_manager", new=AsyncMock()),
                TestClient(app) as client,
            ):
                resp = client.post(
                    "/api/epics",
                    json={"title": "t", "description": "d", "repo_id": repo_id},
                )
                assert resp.status_code == 200, resp.text
                epic_id = resp.json()["epicId"]

                get_resp = client.get(f"/api/epics/{epic_id}")
                assert get_resp.status_code == 200, get_resp.text
                assert get_resp.json()["repoId"] == repo_id
        finally:
            _cleanup_sync([epic_id] if epic_id else [], [repo_id])

    def test_create_epic_without_repo_id_still_works_and_returns_null(self) -> None:
        """The literal backward-compatibility proof at the HTTP layer: a
        client that sends exactly the pre-Phase-1 request body (no repo_id
        field at all) must get exactly the same 200 response shape as
        before, plus a repoId key that is null."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from app.main import app

        epic_id: str | None = None
        try:
            with (
                patch("app.api.epics._launch_epic_manager", new=AsyncMock()),
                TestClient(app) as client,
            ):
                resp = client.post(
                    "/api/epics", json={"title": "t", "description": "d"}
                )
                assert resp.status_code == 200, resp.text
                epic_id = resp.json()["epicId"]

                get_resp = client.get(f"/api/epics/{epic_id}")
                assert get_resp.status_code == 200, get_resp.text
                assert get_resp.json()["repoId"] is None
        finally:
            _cleanup_sync([epic_id] if epic_id else [], [])

    def test_list_epics_includes_repo_id(self) -> None:
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        repo_id = _make_repo_sync(suffix)
        epic_id: str | None = None
        try:
            with (
                patch("app.api.epics._launch_epic_manager", new=AsyncMock()),
                TestClient(app) as client,
            ):
                resp = client.post(
                    "/api/epics",
                    json={"title": "t", "description": "d", "repo_id": repo_id},
                )
                epic_id = resp.json()["epicId"]

                list_resp = client.get("/api/epics")
                assert list_resp.status_code == 200, list_resp.text
                by_id = {e["epicId"]: e for e in list_resp.json()}
                assert by_id[epic_id]["repoId"] == repo_id
        finally:
            _cleanup_sync([epic_id] if epic_id else [], [repo_id])
