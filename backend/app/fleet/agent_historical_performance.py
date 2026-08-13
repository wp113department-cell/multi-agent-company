"""Agent Historical Performance — plan14 follow-on #3 (Memory-Aware Agent
Selection).

FleetManager.select() already scores candidates on real, but exclusively
in-process, signals: AgentInstance.total_runs/avg_confidence (Batch 2 audit
gap-closure) and MetricsCollector's cost/latency ring buffers (plan14 Day 3
Task 6) — all reset to neutral on every process restart. This module adds
the durable complement: a scheduled rollup (explicitly NOT a live join, per
the audit backing this plan) over memory_embeddings.agent_name, the real
per-run outcomes attributed to each agent via app.memory.hooks.
record_agent_run_outcome.

Two halves:
  - compute_and_upsert_all(db): the expensive half — aggregates
    memory_embeddings, upserts agent_historical_performance, refreshes the
    in-process read cache. Called by the periodic background loop
    (app.main._agent_historical_performance_rollup_loop), not on any
    request path.
  - get_cached_performance(agent_name, category): the cheap half —
    FleetManager.select()'s hot path is fully synchronous with no DB access
    (same constraint MetricsCollector's own methods respect), so this is a
    zero-I/O read against a module-level dict kept current by the rollup
    above. Returns None (neutral, same as a freshly-registered agent) for
    any agent/category the rollup hasn't seen yet — never fabricates a
    number.

load_cache_from_db(db) is the third piece: read (not recompute) existing
rows into the in-process cache once at startup, so a freshly restarted
process doesn't run with an empty cache for a full rollup interval before
its first scheduled recompute — the DB table itself is durable across
restarts even though the in-process cache is not.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentHistoricalPerformance, MemoryEmbedding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentPerformanceSnapshot:
    agent_name: str
    category: str
    sample_size: int
    success_rate: float | None
    avg_importance: float | None
    verified_rate: float | None


_cache: dict[tuple[str, str], AgentPerformanceSnapshot] = {}
_cache_lock = threading.Lock()


def get_cached_performance(
    agent_name: str, category: str = "task"
) -> AgentPerformanceSnapshot | None:
    """Sync, zero-I/O read — safe to call from FleetManager.select()'s hot
    path. None means "no rollup has ever seen this (agent_name, category)
    combination" — callers must treat that as neutral, not as zero/failure."""
    with _cache_lock:
        return _cache.get((agent_name, category))


def _row_to_snapshot(row: AgentHistoricalPerformance) -> AgentPerformanceSnapshot:
    return AgentPerformanceSnapshot(
        agent_name=row.agent_name,
        category=row.category,
        sample_size=row.sample_size,
        success_rate=row.success_rate,
        avg_importance=row.avg_importance,
        verified_rate=row.verified_rate,
    )


async def load_cache_from_db(db: AsyncSession) -> int:
    """Populates the in-process cache from whatever agent_historical_performance
    already contains, WITHOUT recomputing — cheap, meant for startup. Returns
    the number of rows loaded."""
    result = await db.execute(select(AgentHistoricalPerformance))
    rows = result.scalars().all()
    with _cache_lock:
        for row in rows:
            _cache[(row.agent_name, row.category)] = _row_to_snapshot(row)
    return len(rows)


async def compute_and_upsert_all(db: AsyncSession) -> int:
    """Real aggregation over memory_embeddings, grouped by (agent_name,
    category), for every row that has a real agent_name (see migration 048
    and store.py's embed_* functions for how/when that column is populated —
    never fabricated for rows where no agent was ever recorded).

    success_rate is only computed for category='task' (the only category
    whose `outcome` is a genuine completed/blocked binary — see
    AgentHistoricalPerformance's own docstring) — every other category's
    rollup row has success_rate=NULL, not a fabricated value.

    Upserts into agent_historical_performance (one row per agent/category,
    on_conflict_do_update — this table holds the current rollup, not a
    history of past rollups) and refreshes the in-process read cache from
    the freshly computed values. Returns the number of (agent_name,
    category) groups upserted.
    """
    from sqlalchemy import case
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    success_rate_expr = func.avg(
        case(
            (
                (MemoryEmbedding.category == "task")
                & (MemoryEmbedding.outcome == "completed"),
                1.0,
            ),
            (
                (MemoryEmbedding.category == "task")
                & (MemoryEmbedding.outcome == "blocked"),
                0.0,
            ),
            else_=None,
        )
    )
    verified_rate_expr = func.avg(
        case((MemoryEmbedding.verified.is_(True), 1.0), else_=0.0)
    )

    stmt = (
        select(
            MemoryEmbedding.agent_name,
            MemoryEmbedding.category,
            func.count().label("sample_size"),
            success_rate_expr.label("success_rate"),
            func.avg(MemoryEmbedding.importance).label("avg_importance"),
            verified_rate_expr.label("verified_rate"),
        )
        .where(
            MemoryEmbedding.agent_name.is_not(None),
            MemoryEmbedding.archived.is_(False),
        )
        .group_by(MemoryEmbedding.agent_name, MemoryEmbedding.category)
    )
    result = await db.execute(stmt)
    rows = result.all()

    upserted = 0
    fresh_cache: dict[tuple[str, str], AgentPerformanceSnapshot] = {}
    for row in rows:
        agent_name = str(row.agent_name)
        category = str(row.category)
        sample_size = int(row.sample_size)
        success_rate = float(row.success_rate) if row.success_rate is not None else None
        avg_importance = (
            float(row.avg_importance) if row.avg_importance is not None else None
        )
        verified_rate = (
            float(row.verified_rate) if row.verified_rate is not None else None
        )

        upsert_stmt = (
            pg_insert(AgentHistoricalPerformance)
            .values(
                agent_name=agent_name,
                category=category,
                sample_size=sample_size,
                success_rate=success_rate,
                avg_importance=avg_importance,
                verified_rate=verified_rate,
            )
            .on_conflict_do_update(
                constraint="uq_agent_historical_performance_agent_category",
                set_={
                    "sample_size": sample_size,
                    "success_rate": success_rate,
                    "avg_importance": avg_importance,
                    "verified_rate": verified_rate,
                    "computed_at": func.now(),
                },
            )
        )
        await db.execute(upsert_stmt)
        upserted += 1
        fresh_cache[(agent_name, category)] = AgentPerformanceSnapshot(
            agent_name=agent_name,
            category=category,
            sample_size=sample_size,
            success_rate=success_rate,
            avg_importance=avg_importance,
            verified_rate=verified_rate,
        )

    await db.commit()

    with _cache_lock:
        _cache.update(fresh_cache)

    logger.info("Agent historical performance rollup: %d agent/category rows", upserted)
    return upserted
