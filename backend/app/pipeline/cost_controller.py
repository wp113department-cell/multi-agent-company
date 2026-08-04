"""Cost Controller — estimate token/dollar cost before epic execution.

Uses historical averages from agent_runs when available, then falls back to
config-driven per-subtask coefficients. The estimate gates epic execution:
epics over COST_APPROVAL_THRESHOLD require explicit human approval.

Gap-closure Day 39 (Stage 2, answers.md Q42, "expected runtime estimate: NO")
added estimated_duration_seconds, computed the same way: a real historical
average of 'coder' agent_runs wall-clock duration when available
(reusing app.fleet.size_estimate.historical_avg_duration_seconds — the same
query Days 37-38 already built for the size pre-flight check, not a
duplicate), config fallback otherwise.

Stage 4 Cluster P (2026-08-05, STAGE4_BACKLOG.md) — cost_rates_for_tier()
added below: the fleet has 3 real cost tiers (haiku/sonnet/opus —
app/fleet/model_router.py's own _tiers table; "gpt" has zero registered
agents in agent_models.json today, Groq having been deprecated 2026-06-17
per that module's own comment, so it is not given a dedicated rate here and
falls back to the sonnet/default rate like any other unrecognized tier).
estimate_epic_cost()/estimate_epic_cost_sync() below were verified NOT to
need per-tier awareness themselves: both estimate before any subtask is
dispatched to a specific agent, and the real dev-dispatch decision
(app/agents/manager.py's run_manager(), selected_agent_name) only ever
chooses between backend_dev and frontend_dev — both sonnet-tier, same as the
fixed qa/reviewer agents — so there is no per-tier signal available yet at
either estimate call site to consult. Correcting the underlying
cost_per_input_token/cost_per_output_token defaults (now real Sonnet
pricing, see app/config.py) was the complete fix for the pre-run estimate.
cost_rates_for_tier() itself is consumed by app/fleet/metrics.py's
RunMetrics._recompute_cost(), which runs per real agent and does have a
real agent_name to resolve a tier from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings


def cost_rates_for_tier(tier: str, settings: Any) -> tuple[float, float]:
    """Return (input_rate, output_rate) USD-per-token for a model_router.py
    tier. Unrecognized tiers (including "gpt", which has no registered
    agents today) fall back to the sonnet/default rate — mirrors
    ModelRouter.route()'s own fallback-to-sonnet convention for unknown
    tiers."""
    if tier == "haiku":
        return settings.cost_per_input_token_haiku, settings.cost_per_output_token_haiku
    if tier == "opus":
        return settings.cost_per_input_token_opus, settings.cost_per_output_token_opus
    return settings.cost_per_input_token, settings.cost_per_output_token


@dataclass(frozen=True)
class CostEstimate:
    subtask_count: int
    estimated_tokens_in: int
    estimated_tokens_out: int
    estimated_cost_usd: float
    requires_approval: bool
    historical_avg_tokens_in: int | None  # None when no history available
    estimated_duration_seconds: float
    duration_source: str  # "historical" | "config_fallback"


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

    from app.fleet.size_estimate import historical_avg_duration_seconds

    hist_in, hist_out = await _historical_avg_tokens(db)

    duration_source = "config_fallback"
    duration_per_subtask = settings.size_processing_seconds_fallback_per_subtask
    hist_duration = await historical_avg_duration_seconds(db, "coder")
    if hist_duration is not None:
        duration_per_subtask = hist_duration
        duration_source = "historical"
    # No max()-clamp, unlike size_estimate.py's own use of this shape — a
    # 0-subtask epic must estimate 0 duration, consistent with this same
    # function's 0-subtask -> 0 cost/token behavior (test_estimate_zero_subtasks).
    estimated_duration_seconds = duration_per_subtask * subtask_count

    if hist_in is not None:
        tokens_in_per_subtask = int(hist_in * complexity_multiplier)
        tokens_out_per_subtask = (
            int(hist_out * complexity_multiplier)
            if hist_out
            else int(hist_in * settings.cost_output_ratio)
        )
    else:
        tokens_in_per_subtask = int(
            settings.cost_tokens_per_subtask * complexity_multiplier
        )
        tokens_out_per_subtask = int(tokens_in_per_subtask * settings.cost_output_ratio)

    total_in = tokens_in_per_subtask * subtask_count
    total_out = tokens_out_per_subtask * subtask_count

    cost = round(
        total_in * settings.cost_per_input_token
        + total_out * settings.cost_per_output_token,
        6,
    )

    return CostEstimate(
        subtask_count=subtask_count,
        estimated_tokens_in=total_in,
        estimated_tokens_out=total_out,
        estimated_cost_usd=cost,
        requires_approval=cost > settings.cost_approval_threshold,
        historical_avg_tokens_in=hist_in,
        estimated_duration_seconds=estimated_duration_seconds,
        duration_source=duration_source,
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
        tokens_out_per_sub = (
            int(avg_tokens_out * complexity_multiplier)
            if avg_tokens_out
            else int(avg_tokens_in * settings.cost_output_ratio)
        )
    else:
        tokens_in_per_sub = int(
            settings.cost_tokens_per_subtask * complexity_multiplier
        )
        tokens_out_per_sub = int(tokens_in_per_sub * settings.cost_output_ratio)

    total_in = tokens_in_per_sub * subtask_count
    total_out = tokens_out_per_sub * subtask_count

    cost = round(
        total_in * settings.cost_per_input_token
        + total_out * settings.cost_per_output_token,
        6,
    )

    return CostEstimate(
        subtask_count=subtask_count,
        estimated_tokens_in=total_in,
        estimated_tokens_out=total_out,
        estimated_cost_usd=cost,
        requires_approval=cost > settings.cost_approval_threshold,
        historical_avg_tokens_in=avg_tokens_in,
        estimated_duration_seconds=settings.size_processing_seconds_fallback_per_subtask
        * subtask_count,
        duration_source="config_fallback",
    )
