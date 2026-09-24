"""T2-B7 (2026-09-24, GRIDIRON_PARTIAL #414 "Aggregate quality score across
all categories (9/9)") — app/fleet/tools_score.py and prompts_score.py, the
two new real, non-fabricated quality-score producers this batch closes.

tools_score is tested against real Postgres (its only real dependency is
AgentRun.tool_accuracy, populated this same batch by #407's work).
prompts_score's real dependency (regression_detector.check_agent()) talks
to the in-process MetricsCollector ring buffer and AgentBenchmark table —
mocked here since this test is about prompts_score's OWN aggregation logic
(the "no baseline yet is excluded, not a fabricated pass" rule), not about
re-proving regression_detector's own behavior (already covered elsewhere).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import AgentRun, DevTask, PromptsScore, Repo, ToolsScore
from app.db.repository import create_agent_run, finish_agent_run
from app.fleet.prompts_score import (
    compute_prompts_score,
    get_latest_prompts_score,
    store_prompts_score,
)
from app.fleet.quality_score import get_quality_score
from app.fleet.tools_score import compute_tools_score, get_latest_tools_score


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_repo_and_task_sync() -> tuple[int, int]:
    async def _run() -> tuple[int, int]:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/t2b7-{uuid.uuid4().hex[:8]}",
                    name=f"t2b7-{uuid.uuid4().hex[:8]}",
                    local_path=f"/tmp/t2b7-{uuid.uuid4().hex[:8]}",
                    status="ready",
                )
                session.add(repo)
                await session.flush()
                task = DevTask(
                    title="t2b7", description="d", status="pending", repo_id=repo.id
                )
                session.add(task)
                await session.commit()
                return repo.id, task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(repo_id: int, task_id: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(AgentRun).where(AgentRun.task_id == task_id)
                )
                await session.execute(
                    delete(ToolsScore).where(ToolsScore.repo_id == repo_id)
                )
                await session.execute(
                    delete(PromptsScore).where(PromptsScore.repo_id == repo_id)
                )
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


class TestToolsScore:
    def test_returns_none_with_no_real_runs(self) -> None:
        repo_id, task_id = _make_repo_and_task_sync()
        try:

            async def _check() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        result = await compute_tools_score(repo_id, session)
                        assert result is None
                finally:
                    await engine.dispose()

            asyncio.run(_check())
        finally:
            _cleanup_sync(repo_id, task_id)

    def test_averages_real_tool_accuracy_excluding_null_rows(self) -> None:
        repo_id, task_id = _make_repo_and_task_sync()
        try:

            async def _seed_and_compute() -> float:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        r1 = await create_agent_run(session, task_id, "bug_fix", "m")
                        await finish_agent_run(
                            session, r1.id, "completed", tool_accuracy=1.0
                        )
                        r2 = await create_agent_run(session, task_id, "qa", "m")
                        await finish_agent_run(
                            session, r2.id, "completed", tool_accuracy=0.5
                        )
                        # A crashed run with no tool_accuracy recorded — must
                        # be excluded from the average, not counted as 0.
                        r3 = await create_agent_run(session, task_id, "reviewer", "m")
                        await finish_agent_run(session, r3.id, "failed", error="boom")

                        result = await compute_tools_score(repo_id, session)
                        assert result is not None
                        return result.tools_score, result.run_count
                finally:
                    await engine.dispose()

            score, run_count = asyncio.run(_seed_and_compute())
            assert score == pytest.approx(0.75)
            assert run_count == 2
        finally:
            _cleanup_sync(repo_id, task_id)

    def test_store_and_read_latest_round_trips_through_real_postgres(self) -> None:
        from app.fleet.tools_score import _persist as _persist_tools_score

        repo_id, task_id = _make_repo_and_task_sync()
        try:
            assert get_latest_tools_score(repo_id) is None

            async def _seed() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        run = await create_agent_run(session, task_id, "bug_fix", "m")
                        await finish_agent_run(
                            session, run.id, "completed", tool_accuracy=0.9
                        )
                        result = await compute_tools_score(repo_id, session)
                        assert result is not None
                        # store_tools_score's own asyncio.run() bridge can't
                        # be called from inside this already-running event
                        # loop — call the async _persist directly instead,
                        # exactly what the sync bridge itself does.
                        await _persist_tools_score(repo_id, result)
                finally:
                    await engine.dispose()

            asyncio.run(_seed())

            latest = get_latest_tools_score(repo_id)
            assert latest is not None
            assert latest.tools_score == pytest.approx(0.9)

            # And the cross-category aggregator now sees it as "available".
            qs = get_quality_score(repo_id)
            by_name = {c.name: c for c in qs.categories}
            assert by_name["tools"].status == "available"
            assert by_name["tools"].score == pytest.approx(0.9)
        finally:
            _cleanup_sync(repo_id, task_id)


class TestPromptsScore:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_relevant_roles(self) -> None:
        mock_db = AsyncMock()
        with patch(
            "app.fleet.agents_score._resolve_relevant_agent_names",
            new=AsyncMock(return_value=[]),
        ):
            result = await compute_prompts_score(repo_id=1, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_roles_with_no_baseline_are_excluded_not_counted_as_a_pass(
        self,
    ) -> None:
        no_baseline_gate = SimpleNamespace(
            blocked=False, report=SimpleNamespace(baseline_score=None)
        )
        mock_detector = SimpleNamespace(check_agent=lambda role_name: no_baseline_gate)
        with (
            patch(
                "app.fleet.agents_score._resolve_relevant_agent_names",
                new=AsyncMock(return_value=["brand_new_role"]),
            ),
            patch(
                "app.fleet.regression_detector.get_regression_detector",
                return_value=mock_detector,
            ),
        ):
            result = await compute_prompts_score(repo_id=1, db=AsyncMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_pass_and_blocked_roles_computes_real_pass_rate(self) -> None:
        def _check_agent(role_name: str) -> SimpleNamespace:
            if role_name == "regressed_role":
                return SimpleNamespace(
                    blocked=True, report=SimpleNamespace(baseline_score=0.8)
                )
            return SimpleNamespace(
                blocked=False, report=SimpleNamespace(baseline_score=0.8)
            )

        mock_detector = SimpleNamespace(check_agent=_check_agent)
        with (
            patch(
                "app.fleet.agents_score._resolve_relevant_agent_names",
                new=AsyncMock(
                    return_value=["healthy_role_a", "healthy_role_b", "regressed_role"]
                ),
            ),
            patch(
                "app.fleet.regression_detector.get_regression_detector",
                return_value=mock_detector,
            ),
        ):
            result = await compute_prompts_score(repo_id=1, db=AsyncMock())

        assert result is not None
        assert result.blocked_roles == ["regressed_role"]
        assert result.prompts_score == pytest.approx(2 / 3)

    def test_store_and_read_latest_round_trips_through_real_postgres(self) -> None:
        repo_id, task_id = _make_repo_and_task_sync()
        try:
            assert get_latest_prompts_score(repo_id) is None

            from app.fleet.prompts_score import PromptsScoreResult

            result = PromptsScoreResult(
                role_names=["a", "b"], blocked_roles=["b"], prompts_score=0.5
            )
            store_prompts_score(repo_id, result)

            latest = get_latest_prompts_score(repo_id)
            assert latest is not None
            assert latest.prompts_score == pytest.approx(0.5)
            assert latest.blocked_roles == ["b"]

            qs = get_quality_score(repo_id)
            by_name = {c.name: c for c in qs.categories}
            assert by_name["prompts"].status == "available"
            assert by_name["prompts"].score == pytest.approx(0.5)
        finally:
            _cleanup_sync(repo_id, task_id)
