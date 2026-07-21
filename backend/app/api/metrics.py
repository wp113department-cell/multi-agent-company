"""Metrics API — productivity dashboard data.

GET /api/metrics         — aggregate system metrics
GET /api/metrics/epics   — per-epic cost breakdown
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Epic
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/metrics", tags=["metrics"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AgentTypeSummary(_CamelModel):
    agent_type: str
    run_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    cache_hit_rate: float


class SystemMetrics(_CamelModel):
    total_epics: int
    epics_by_status: dict[str, int]
    total_agent_runs: int
    total_tokens_in: int
    total_tokens_out: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    cache_hit_rate: float
    agent_type_breakdown: list[AgentTypeSummary]


class EpicCostSummary(_CamelModel):
    epic_id: str
    title: str
    status: str
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_hit_rate: float
    cost_estimate: float | None
    cost_actual: float | None


@router.get("", response_model=SystemMetrics, response_model_by_alias=True)
async def get_system_metrics(db: AsyncSession = Depends(get_db)) -> Any:
    # Epic status counts
    epic_result = await db.execute(
        select(Epic.status, func.count(Epic.epic_id)).group_by(Epic.status)
    )
    epics_by_status: dict[str, int] = {row[0]: row[1] for row in epic_result}
    total_epics = sum(epics_by_status.values())

    # Aggregate agent_runs token totals
    run_agg = await db.execute(
        select(
            func.count(AgentRun.id),
            func.coalesce(func.sum(AgentRun.tokens_in), 0),
            func.coalesce(func.sum(AgentRun.tokens_out), 0),
            func.coalesce(func.sum(AgentRun.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentRun.cache_creation_tokens), 0),
        )
    )
    row = run_agg.one()
    total_runs, total_in, total_out, total_cache_read, total_cache_creation = (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
        int(row[4]),
    )

    cache_hit_rate = _hit_rate(total_cache_read, total_cache_creation)

    # Per-agent-type breakdown
    type_result = await db.execute(
        select(
            AgentRun.agent_type,
            func.count(AgentRun.id),
            func.coalesce(func.sum(AgentRun.tokens_in), 0),
            func.coalesce(func.sum(AgentRun.tokens_out), 0),
            func.coalesce(func.sum(AgentRun.cache_read_tokens), 0),
            func.coalesce(func.sum(AgentRun.cache_creation_tokens), 0),
        ).group_by(AgentRun.agent_type)
    )
    breakdown = [
        AgentTypeSummary(
            agent_type=r[0],
            run_count=int(r[1]),
            total_tokens_in=int(r[2]),
            total_tokens_out=int(r[3]),
            total_cache_read_tokens=int(r[4]),
            total_cache_creation_tokens=int(r[5]),
            cache_hit_rate=_hit_rate(int(r[4]), int(r[5])),
        )
        for r in type_result
    ]

    return SystemMetrics(
        total_epics=total_epics,
        epics_by_status=epics_by_status,
        total_agent_runs=total_runs,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        total_cache_read_tokens=total_cache_read,
        total_cache_creation_tokens=total_cache_creation,
        cache_hit_rate=cache_hit_rate,
        agent_type_breakdown=breakdown,
    )


@router.get(
    "/epics", response_model=list[EpicCostSummary], response_model_by_alias=True
)
async def get_epic_cost_breakdown(db: AsyncSession = Depends(get_db)) -> Any:
    epics_result = await db.execute(select(Epic).order_by(Epic.created_at.desc()))
    epics = epics_result.scalars().all()

    results = []
    for epic in epics:
        # Sum agent_runs for tasks belonging to this epic
        from app.db.models import DevTask

        run_agg = await db.execute(
            select(
                func.coalesce(func.sum(AgentRun.tokens_in), 0),
                func.coalesce(func.sum(AgentRun.tokens_out), 0),
                func.coalesce(func.sum(AgentRun.cache_read_tokens), 0),
                func.coalesce(func.sum(AgentRun.cache_creation_tokens), 0),
            )
            .join(DevTask, DevTask.id == AgentRun.task_id)
            .where(DevTask.epic_id == epic.epic_id)
        )
        r = run_agg.one()
        cr, cc = int(r[2]), int(r[3])
        results.append(
            EpicCostSummary(
                epic_id=epic.epic_id,
                title=epic.title,
                status=epic.status,
                tokens_in=int(r[0]),
                tokens_out=int(r[1]),
                cache_read_tokens=cr,
                cache_creation_tokens=cc,
                cache_hit_rate=_hit_rate(cr, cc),
                cost_estimate=float(epic.cost_estimate) if epic.cost_estimate else None,
                cost_actual=float(epic.cost_actual) if epic.cost_actual else None,
            )
        )
    return results


def _hit_rate(cache_read: int, cache_creation: int) -> float:
    total = cache_read + cache_creation
    if total == 0:
        return 0.0
    return round(cache_read / total, 4)
