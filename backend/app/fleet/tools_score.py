"""Tools Score — T2-B7 gap-closure (2026-09-24, GRIDIRON_PARTIAL #414
"Aggregate quality score across all categories (9/9)").

quality_score.py's own module docstring used to list "tools" as
not-implemented for a documented reason: "ToolCallRecord (app/fleet/
metrics.py) is transient in-memory per-run data only — never persisted to
any table, let alone one with repo scoping." That gap is closed by T2-B7's
own #407 work: `AgentRun.tool_accuracy` (migration 057) now persists each
run's real tool-call success rate (`RunMetrics.tool_accuracy`'s exact
value at finish time), giving this category a real, durable, repo-scoped
signal to read.

Mirrors app/fleet/agents_score.py's exact shape: resolve the real set of
agent_runs scoped to this repo_id (same join agents_score.py already
established — agent_runs.task_id -> dev_tasks.repo_id), average their
persisted tool_accuracy, never fabricate a score for a repo/window with no
real runs that have it recorded yet (legacy pre-migration-057 rows and
crashed runs both correctly have tool_accuracy=NULL and are excluded from
the average, not counted as 0).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolsScoreResult:
    run_count: int
    tools_score: float
    timestamp: str = field(default_factory=_now_iso)


async def compute_tools_score(
    repo_id: int, db: Any, window_days: int = 30
) -> ToolsScoreResult | None:
    """Real computation: mean AgentRun.tool_accuracy over recent finished
    runs scoped to repo_id. Returns None (never a fabricated score) when no
    run in the window has a recorded tool_accuracy yet."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.db.models import AgentRun, DevTask

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    result = await db.execute(
        select(func.count(AgentRun.id), func.avg(AgentRun.tool_accuracy))
        .join(DevTask, DevTask.id == AgentRun.task_id)
        .where(
            DevTask.repo_id == repo_id,
            AgentRun.started_at >= since,
            AgentRun.tool_accuracy.is_not(None),
        )
    )
    run_count, avg_accuracy = result.one()
    if not run_count or avg_accuracy is None:
        return None
    return ToolsScoreResult(
        run_count=int(run_count), tools_score=round(float(avg_accuracy), 6)
    )


async def _persist(repo_id: int, result: ToolsScoreResult) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import ToolsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                ToolsScore(
                    repo_id=repo_id,
                    run_count=result.run_count,
                    tools_score=result.tools_score,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def store_tools_score(repo_id: int, result: ToolsScoreResult) -> None:
    """Sync entry point mirroring agents_score.store_agents_score exactly.
    Non-fatal: logs and returns on any failure."""
    try:
        asyncio.run(_persist(repo_id, result))
    except Exception as exc:
        logger.warning("Failed to persist tools_score for repo %s: %s", repo_id, exc)


async def _read_latest(repo_id: int) -> ToolsScoreResult | None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import ToolsScore
    from app.db.session import new_isolated_async_engine

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = (
                await session.execute(
                    select(ToolsScore)
                    .where(ToolsScore.repo_id == repo_id)
                    .order_by(ToolsScore.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return ToolsScoreResult(
                run_count=row.run_count,
                tools_score=row.tools_score,
                timestamp=row.created_at.isoformat(),
            )
    finally:
        await engine.dispose()


def get_latest_tools_score(repo_id: int) -> ToolsScoreResult | None:
    """Read-only latest-row lookup — the exact shape quality_score.py's
    CategoryDefinition.get_latest expects (never recomputes; only reads
    the most recently persisted row)."""
    return asyncio.run(_read_latest(repo_id))
