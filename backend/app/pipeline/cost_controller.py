"""Cost Controller — estimate token/dollar cost before epic execution.

Uses historical averages from agent_runs when available, then falls back to
config-driven per-subtask coefficients. The estimate gates epic execution:
epics over COST_APPROVAL_THRESHOLD require explicit human approval.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings


@dataclass(frozen=True)
class CostEstimate:
    subtask_count: int
    estimated_tokens_in: int
    estimated_tokens_out: int
    estimated_cost_usd: float
    requires_approval: bool
    historical_avg_tokens_in: int | None  # None when no history available


async def _historical_avg_tokens(db: AsyncSession) -> tuple[int | None, int | None]:
    """Query average tokens per agent_run from completed runs."""
    from app.db.models import AgentRun

    result = await db.execute(
        select(
            func.avg(AgentRun.tokens_in).label("avg_in"),
            func.avg(AgentRun.tokens_out).label("avg_out"),
            func.count(AgentRun.id).label("run_count"),
        ).where(
            AgentRun.status == "completed",
            AgentRun.tokens_in.isnot(None),
        )
    )
    row = result.one()
    if row.run_count == 0 or row.avg_in is None:
        return None, None
    return int(row.avg_in), int(row.avg_out) if row.avg_out else None


async def estimate_epic_cost(
    subtask_count: int,
    db: AsyncSession,
    complexity_multiplier: float = 1.0,
) -> CostEstimate:
    """Estimate the cost of running an epic with the given subtask count.

    Prefers historical per-run averages; falls back to config coefficients.
    """
    settings = get_settings()

    hist_in, hist_out = await _historical_avg_tokens(db)

    if hist_in is not None:
        tokens_in_per_subtask = int(hist_in * complexity_multiplier)
        tokens_out_per_subtask = int(hist_out * complexity_multiplier) if hist_out else int(hist_in * settings.cost_output_ratio)
    else:
        tokens_in_per_subtask = int(settings.cost_tokens_per_subtask * complexity_multiplier)
        tokens_out_per_subtask = int(tokens_in_per_subtask * settings.cost_output_ratio)

    total_in = tokens_in_per_subtask * subtask_count
    total_out = tokens_out_per_subtask * subtask_count

    cost = round(
        total_in * settings.cost_per_input_token + total_out * settings.cost_per_output_token,
        6,
    )

    return CostEstimate(
        subtask_count=subtask_count,
        estimated_tokens_in=total_in,
        estimated_tokens_out=total_out,
        estimated_cost_usd=cost,
        requires_approval=cost > settings.cost_approval_threshold,
        historical_avg_tokens_in=hist_in,
    )


def estimate_epic_cost_sync(
    subtask_count: int,
    complexity_multiplier: float = 1.0,
    avg_tokens_in: int | None = None,
    avg_tokens_out: int | None = None,
) -> CostEstimate:
    """Pure sync estimate with no DB — used in tests and pre-DB contexts."""
    settings = get_settings()

    if avg_tokens_in is not None:
        tokens_in_per_sub = int(avg_tokens_in * complexity_multiplier)
        tokens_out_per_sub = int(avg_tokens_out * complexity_multiplier) if avg_tokens_out else int(avg_tokens_in * settings.cost_output_ratio)
    else:
        tokens_in_per_sub = int(settings.cost_tokens_per_subtask * complexity_multiplier)
        tokens_out_per_sub = int(tokens_in_per_sub * settings.cost_output_ratio)

    total_in = tokens_in_per_sub * subtask_count
    total_out = tokens_out_per_sub * subtask_count

    cost = round(
        total_in * settings.cost_per_input_token + total_out * settings.cost_per_output_token,
        6,
    )

    return CostEstimate(
        subtask_count=subtask_count,
        estimated_tokens_in=total_in,
        estimated_tokens_out=total_out,
        estimated_cost_usd=cost,
        requires_approval=cost > settings.cost_approval_threshold,
        historical_avg_tokens_in=avg_tokens_in,
    )
