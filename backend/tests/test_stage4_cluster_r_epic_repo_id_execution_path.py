"""Stage 4 Cluster R Phase 2 (2026-08-05, STAGE4_BACKLOG.md / CLUSTER_R_DESIGN.md)
— execution-path wiring only.

Phase 1 (tests/test_stage4_cluster_r_epic_repo_id.py) added the schema and
API-schema layer (Epic.repo_id, CreateEpicRequest.repo_id) without touching
any execution path. Phase 2 closes the loop this file proves end-to-end:

    Epic.repo_id (persisted)
        -> _launch_epic_manager() resolves it via resolve_epic_repo_path()
        -> run_epic_manager()/_run_epic_manager_body() seed it into
           EpicManagerState["repo_id"]
        -> _planning_node() inherits it onto the DevTask it creates

Real correction found during the Phase 1 design review (CLUSTER_R_DESIGN.md
§1.3), fixed here: EpicManagerState's own prior docstring claimed
downstream scoping would "start working automatically" once epics had a
real repo_id -- true for the two embed_task_outcome() calls in
_finalize_node (already covered by
tests/test_cluster_o_phase1b_repo_scoped_memory_isolation.py), but
_planning_node's DevTask(...) construction never passed repo_id= and
needed a real one-line fix, which is what this file's core test proves.

No product behavior or UI changes -- this is execution-path wiring only,
same discipline as Phase 1.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.manager import EpicManagerState, _planning_node, run_epic_manager
from app.config import get_settings
from app.db.models import DevTask, Epic, Repo
from app.db.repository import resolve_epic_repo_path
from app.db.session import new_isolated_async_engine


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str, ready: bool = True) -> Repo:
    repo = Repo(
        github_url=f"https://github.com/test/clusterr-exec-{suffix}",
        name=f"clusterr-exec-{suffix}",
        local_path=f"/tmp/clusterr-exec-{suffix}",
        status="ready" if ready else "cloning",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


def _make_repo_sync(suffix: str, ready: bool = True) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = await _make_repo(session, suffix, ready=ready)
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
                        title=f"cluster r phase 2 test {suffix}",
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


def _cleanup_sync(
    epic_ids: list[str], task_ids: list[int], repo_ids: list[int]
) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                if task_ids:
                    await session.execute(
                        delete(DevTask).where(DevTask.id.in_(task_ids))
                    )
                await session.execute(delete(Epic).where(Epic.epic_id.in_(epic_ids)))
                await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# resolve_epic_repo_path() -- the Cluster O-pattern helper, real Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_epic_repo_path_uses_epic_repo_id() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix)
            epic_id = str(uuid.uuid4())
            session.add(
                Epic(
                    epic_id=epic_id,
                    title="t",
                    description="d",
                    status="pending",
                    repo_id=repo.id,
                )
            )
            await session.commit()

            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Epic)
                .options(selectinload(Epic.repo))
                .where(Epic.epic_id == epic_id)
            )
            epic = result.scalar_one()

            assert resolve_epic_repo_path(epic) == repo.local_path

            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_epic_repo_path_returns_none_for_not_ready_repo() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix, ready=False)
            epic_id = str(uuid.uuid4())
            session.add(
                Epic(
                    epic_id=epic_id,
                    title="t",
                    description="d",
                    status="pending",
                    repo_id=repo.id,
                )
            )
            await session.commit()

            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Epic)
                .options(selectinload(Epic.repo))
                .where(Epic.epic_id == epic_id)
            )
            epic = result.scalar_one()

            assert resolve_epic_repo_path(epic) is None

            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


def test_resolve_epic_repo_path_returns_none_for_a_legacy_epic_with_no_repo() -> None:
    """The literal backward-compatibility case: repo_id=NULL (today's only
    real path pre-Phase-1) must resolve to None, not raise or default to
    something else -- the caller's existing settings.target_repo_path
    fallback stays intact."""
    epic = Epic(epic_id=str(uuid.uuid4()), title="t", description="d", status="pending")
    assert epic.repo is None
    assert resolve_epic_repo_path(epic) is None


# ---------------------------------------------------------------------------
# _planning_node() -- the core Phase 2 fix: DevTask inherits state["repo_id"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_node_creates_a_devtask_scoped_to_the_epics_repo_id() -> None:
    """The direct proof of the one-line fix this phase makes: given a
    populated state["repo_id"] (as _run_epic_manager_body now seeds it from
    the epic's own resolved repo_id), the DevTask _planning_node creates
    must carry that same repo_id -- not None, and not a different value."""
    from unittest.mock import MagicMock

    from app.pipeline import graph as graph_module

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix)
            epic_id = str(uuid.uuid4())
            session.add(
                Epic(
                    epic_id=epic_id,
                    title=f"clusterr phase2 planning {suffix}",
                    description="d",
                    status="pending",
                    repo_id=repo.id,
                )
            )
            await session.commit()

            async def _fake_ainvoke(state: object, config: object) -> object:
                return {**state, "subtasks": [], "task_description": "d"}  # type: ignore[dict-item]

            fake_graph = MagicMock()
            fake_graph.ainvoke = AsyncMock(side_effect=_fake_ainvoke)

            state: EpicManagerState = {
                "epic_id": epic_id,
                "goal": f"clusterr phase2 planning {suffix}",
                "db": session,
                "repo": "/tmp",
                "repo_id": repo.id,
            }
            with patch.object(graph_module, "get_graph", return_value=fake_graph):
                result = await _planning_node(state)

            assert result["repo_id"] == repo.id

            task_row = (
                await session.execute(
                    select(DevTask).where(DevTask.id == result["task_id"])
                )
            ).scalar_one()
            assert task_row.repo_id == repo.id

            await session.execute(
                delete(DevTask).where(DevTask.id == result["task_id"])
            )
            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# _launch_epic_manager() -- resolves the epic's repo_id/repo_path and
# threads them into run_epic_manager(), real Postgres, run_epic_manager
# itself mocked to isolate this one wiring hop.
# ---------------------------------------------------------------------------


class TestLaunchEpicManagerThreading:
    def test_launch_epic_manager_resolves_and_threads_repo_id_and_path(self) -> None:
        from app.api.epics import _launch_epic_manager

        suffix = uuid.uuid4().hex[:8]
        repo_id = _make_repo_sync(suffix)
        epic_id = _make_epic_sync(suffix, repo_id=repo_id)

        captured: dict[str, object] = {}

        async def _fake_run_epic_manager(**kwargs: object) -> object:
            captured.update(kwargs)
            from app.agents.manager import EpicApprovalPackage

            return EpicApprovalPackage(
                epic_id=str(kwargs["epic_id"]),
                status="ready_for_review",
                subtask_results=[],
                total_files_changed=[],
                all_diffs=[],
                all_qa_summaries=[],
                all_review_findings=[],
                cost_actual_usd=0.0,
                halt_reason=None,
            )

        try:
            with patch(
                "app.agents.manager.run_epic_manager",
                new=AsyncMock(side_effect=_fake_run_epic_manager),
            ):
                asyncio.run(_launch_epic_manager(epic_id, "goal"))
        finally:
            _cleanup_sync([epic_id], [], [repo_id])

        assert captured["repo_id"] == repo_id
        assert captured["repo_path"] == f"/tmp/clusterr-exec-{suffix}"

    def test_launch_epic_manager_threads_none_for_a_legacy_epic(self) -> None:
        """Backward compatibility at the execution-path layer: a legacy
        epic (repo_id=NULL) must still resolve to repo_id=None,
        repo_path=None -- exactly today's pre-Phase-2 call shape, so
        run_epic_manager falls back to settings.target_repo_path
        unchanged."""
        from app.api.epics import _launch_epic_manager

        suffix = uuid.uuid4().hex[:8]
        epic_id = _make_epic_sync(suffix, repo_id=None)

        captured: dict[str, object] = {}

        async def _fake_run_epic_manager(**kwargs: object) -> object:
            captured.update(kwargs)
            from app.agents.manager import EpicApprovalPackage

            return EpicApprovalPackage(
                epic_id=str(kwargs["epic_id"]),
                status="ready_for_review",
                subtask_results=[],
                total_files_changed=[],
                all_diffs=[],
                all_qa_summaries=[],
                all_review_findings=[],
                cost_actual_usd=0.0,
                halt_reason=None,
            )

        try:
            with patch(
                "app.agents.manager.run_epic_manager",
                new=AsyncMock(side_effect=_fake_run_epic_manager),
            ):
                asyncio.run(_launch_epic_manager(epic_id, "goal"))
        finally:
            _cleanup_sync([epic_id], [], [])

        assert captured["repo_id"] is None
        assert captured["repo_path"] is None


# ---------------------------------------------------------------------------
# Full chain -- run_epic_manager() end-to-end (real graph, real Postgres),
# mirroring test_phase51_epic_manager_graph.py's own conflict-halt style to
# stop short of the real coding/LLM node.
# ---------------------------------------------------------------------------


class TestFullChainThroughRunEpicManager:
    async def test_run_epic_manager_with_a_repo_id_produces_a_scoped_devtask(
        self,
    ) -> None:
        fake_estimate = AsyncMock(
            side_effect=[
                type(
                    "Estimate",
                    (),
                    {"estimated_cost_usd": 1.0, "requires_approval": False},
                )(),
                type(
                    "Estimate",
                    (),
                    {"estimated_cost_usd": 1.5, "requires_approval": False},
                )(),
            ]
        )
        fake_pipeline_result = {
            "subtasks": [
                {"id": 1, "type": "backend", "title": "t", "description": "d"}
            ],
            "task_description": "goal",
            "architect_plan": {
                "impacted_files": [{"path": "app/conflicting_file.py", "reason": "x"}]
            },
        }

        suffix = uuid.uuid4().hex[:8]
        setup_engine = _engine()
        try:
            async with async_sessionmaker(setup_engine, expire_on_commit=False)() as setup_session:  # type: ignore[arg-type]
                repo = await _make_repo(setup_session, suffix)
                epic_id = str(uuid.uuid4())
                setup_session.add(
                    Epic(
                        epic_id=epic_id,
                        title=f"clusterr phase2 fullchain {suffix}",
                        description="d",
                        status="pending",
                        repo_id=repo.id,
                    )
                )
                await setup_session.commit()
        finally:
            await setup_engine.dispose()

        try:
            with patch(
                "app.pipeline.cost_controller.estimate_epic_cost", new=fake_estimate
            ), patch(
                "app.pipeline.graph.run_planning_pipeline",
                new=AsyncMock(return_value=fake_pipeline_result),
            ), patch(
                "app.pipeline.conflict_guard.check_file_conflicts",
                new=AsyncMock(
                    return_value="app/conflicting_file.py already claimed by epic X"
                ),
            ), patch(
                "app.agents.manager.run_manager",
                new=AsyncMock(side_effect=AssertionError("coding node must not run")),
            ):
                run_engine = _engine()
                try:
                    async with async_sessionmaker(run_engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        package = await asyncio.wait_for(
                            run_epic_manager(
                                epic_id=epic_id,
                                goal="goal",
                                db=session,
                                repo_id=repo.id,
                                repo_path=repo.local_path,
                            ),
                            timeout=10.0,
                        )
                finally:
                    await run_engine.dispose()

            assert package.status == "halted"

            verify_engine = _engine()
            try:
                async with async_sessionmaker(verify_engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_row = (
                        await session.execute(
                            select(DevTask).where(DevTask.epic_id == epic_id)
                        )
                    ).scalar_one()
                    assert task_row.repo_id == repo.id
                    await session.execute(
                        delete(DevTask).where(DevTask.id == task_row.id)
                    )
                    await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
                    await session.execute(delete(Repo).where(Repo.id == repo.id))
                    await session.commit()
            finally:
                await verify_engine.dispose()
        except BaseException:
            _cleanup_sync([epic_id], [], [repo.id])
            raise
