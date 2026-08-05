"""Test Score — Stage 4 Cluster Q, Tests slice dedicated persistence added
2026-08-05 while building the cross-category aggregation layer
(app/fleet/quality_score.py), STAGE4_BACKLOG.md.

The Tests slice's `coverage_pct` (added to test_coverage_agent's submit
schema — see STAGE4_BACKLOG.md's Tests slice entry) was already captured
and persisted, but only inside the generic `artifacts` table's opaque JSON
payload (app/api/specialized_agents.py's artifact_payload) — that table
has no `repo_id` column and no dedicated read-back function, unlike
app/fleet/architecture_score.py / security_score.py. This module brings
Tests to the same structural bar as those two — a real prerequisite for
uniform cross-category aggregation, found while building it, not assumed
in advance. The existing artifact-persistence path is unchanged; this is
additive.

Mirrors architecture_score.py / security_score.py's exact shape: pure
computation separate from persistence, sync-facing entry points using
new_isolated_async_engine() per call. Only ever persisted for a verified
run (coverage_measured=True, the same graph-enforced flag
AgentResult.verified already uses) with a real, non-omitted coverage_pct
— an unverified run's claim isn't grounded, and an omitted coverage_pct
(the schema's own explicit "never estimate" escape hatch for a blocked
tool run) has nothing real to score.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TestScoreResult:
    coverage_pct: float
    test_score: float
    timestamp: str = field(default_factory=_now_iso)


def compute_test_score(coverage_pct: float) -> TestScoreResult:
    """Pure function: the real, agent-measured coverage_pct (0-100) ->
    a bounded [0.0, 1.0] score comparable to architecture_score/
    security_score. No weighting/thresholds involved — coverage_pct is
    already the real, direct signal; normalizing it to [0,1] is the only
    transformation, clamped defensively in case of an out-of-range input."""
    clamped = max(0.0, min(100.0, coverage_pct))
    return TestScoreResult(
        coverage_pct=coverage_pct, test_score=round(clamped / 100.0, 6)
    )


async def _persist(task_id: str, repo_id: int | None, result: TestScoreResult) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import TestScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                TestScore(
                    task_id=task_id,
                    repo_id=repo_id,
                    coverage_pct=result.coverage_pct,
                    test_score=result.test_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_test_score(
    task_id: str, repo_id: int | None, result: TestScoreResult
) -> None:
    """Sync entry point for run_test_coverage_agent() (itself sync) to
    persist a score — mirrors store_architecture_score()/
    store_security_score()'s own asyncio.run()-over-an-isolated-engine
    shape exactly. Non-fatal: logs and returns on any failure rather than
    raising, so a persistence failure can never break the real coverage
    review it's derived from."""
    try:
        asyncio.run(_persist(task_id, repo_id, result))
    except Exception as exc:
        logger.warning("Failed to persist test_score for task %s: %s", task_id, exc)


async def _read_latest(repo_id: int) -> TestScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import TestScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(TestScore)
                    .where(TestScore.repo_id == repo_id)
                    .order_by(TestScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return TestScoreResult(
                coverage_pct=row.coverage_pct,
                test_score=row.test_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_test_score(repo_id: int) -> TestScoreResult | None:
    """The intra-category 'aggregation' this slice delivers: the most
    recently persisted score for a repo. Analogous to
    architecture_score.py's get_latest_architecture_score() and
    security_score.py's get_latest_security_score()."""
    return asyncio.run(_read_latest(repo_id))


async def _read_trend(repo_id: int, limit: int) -> list[TestScoreResult]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import TestScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(TestScore)
                        .where(TestScore.repo_id == repo_id)
                        .order_by(TestScore.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [
                TestScoreResult(
                    coverage_pct=row.coverage_pct,
                    test_score=row.test_score,
                    timestamp=row.created_at.isoformat(),
                )
                for row in rows
            ]
    finally:
        await engine.dispose()


def get_test_score_trend(repo_id: int, limit: int = 20) -> list[TestScoreResult]:
    """Newest-first score history for a repo."""
    return asyncio.run(_read_trend(repo_id, limit))
