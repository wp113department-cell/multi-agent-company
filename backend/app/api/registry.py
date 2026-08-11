"""Agent Registry API — GET /api/agents, GET /api/agents/:name, PATCH /api/agents/:name/metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import Agent, AgentRun
from app.middleware.rbac import require_approver

router = APIRouter(prefix="/api/agents", tags=["registry"])


# ---- Schemas ----


class AgentResponse(BaseModel):
    agent_id: str
    name: str
    capability_tags: list[str]
    tool_list: list[str]
    prompt_ref: str | None
    version: str
    success_rate: float
    avg_retries: float
    last_computed_at: str
    created_at: str


class RegisterAgentRequest(BaseModel):
    name: str
    capability_tags: list[str]
    tool_list: list[str]
    prompt_ref: str | None = None
    version: str = "1.0"


class MetricsResponse(BaseModel):
    agent_id: str
    name: str
    success_rate: float
    avg_retries: float
    total_runs: int
    last_computed_at: str


# ---- Helpers ----


def _agent_to_response(a: Agent) -> dict[str, Any]:
    return {
        "agentId": a.agent_id,
        "name": a.name,
        "capabilityTags": list(a.capability_tags or []),
        "toolList": list(a.tool_list or []),
        "promptRef": a.prompt_ref,
        "version": a.version,
        "successRate": a.success_rate,
        "avgRetries": a.avg_retries,
        "lastComputedAt": a.last_computed_at.isoformat(),
        "createdAt": a.created_at.isoformat(),
    }


# ---- Routes ----


@router.get("")
async def list_agents(
    tag: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all registered agents. Optional ?tag= filter by capability tag."""
    stmt = select(Agent).order_by(Agent.name)
    result = await db.execute(stmt)
    agents = list(result.scalars().all())

    if tag:
        agents = [a for a in agents if tag in (a.capability_tags or [])]

    return [_agent_to_response(a) for a in agents]


@router.get("/{name}")
async def get_agent(name: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get a single agent by name."""
    result = await db.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return _agent_to_response(agent)


async def _compute_user_approval_rate(db: AsyncSession, name: str) -> float | None:
    """AUDIT_Q_BATCH16 §87 gap-closure (2026-08-11) — "User approval rate":
    there is no dedicated Approval model, but every real approve/reject
    decision is already durably logged (task_logs.category in
    ("approval", "rejection") — see api/tasks.py's approve_task/reject_task/
    pipeline_approve/pipeline_reject, every one of which calls append_log
    with exactly one of those two categories) and attributable to an agent
    via DevTask.assigned_agent (the same column already surfaced on every
    task response). Returns None (not 0.0) when this agent has no logged
    approval decisions yet — "no data" and "0% approved" are different
    claims, and only the former is honest here."""
    from sqlalchemy import func

    from app.db.models import DevTask, TaskLog

    result = await db.execute(
        select(TaskLog.category, func.count(TaskLog.id))
        .join(DevTask, DevTask.id == TaskLog.task_id)
        .where(
            DevTask.assigned_agent == name,
            TaskLog.category.in_(("approval", "rejection")),
        )
        .group_by(TaskLog.category)
    )
    counts: dict[str, int] = {category: int(n) for category, n in result.all()}
    approvals = counts.get("approval", 0)
    rejections = counts.get("rejection", 0)
    total = approvals + rejections
    if total == 0:
        return None
    return round(approvals / total, 4)


@router.get("/{name}/metrics")
async def get_agent_metrics(
    name: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return live-computed metrics for the agent, then persist the snapshot.

    AUDIT_Q_BATCH16 §87 gap-closure (2026-08-11) — "Avg execution time" and
    "Tool usage" were real, correctly computed (MetricsCollector.
    p50_latency_ms/p95_latency_ms/avg_tool_accuracy, Day 10) but only
    reachable via the fleet_metrics_read agent tool (app/agents/tools.py),
    not any HTTP route — a human operator had no way to query them without
    going through an agent. Reuses the exact same collector methods that
    tool already calls, exposed on this existing REST endpoint instead of a
    new one. "Reliability score" (previously NO — no field existed under
    that name) is a real, documented composite of two already-real,
    already-computed numbers, not a new tracked metric or a fabricated one.
    "User approval rate" (previously NO) is computed in
    _compute_user_approval_rate() above.
    """
    from app.fleet.metrics import get_metrics_collector

    result = await db.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Count runs from agent_runs for this agent type
    runs_result = await db.execute(select(AgentRun).where(AgentRun.agent_type == name))
    runs = list(runs_result.scalars().all())
    total_runs = len(runs)

    if total_runs == 0:
        success_rate = agent.success_rate
        avg_retries = agent.avg_retries
    else:
        successes = sum(1 for r in runs if r.status == "completed")
        success_rate = successes / total_runs
        # avg_retries: approximated from tokens — real retry count not stored per-run
        # use the agent table value (updated separately by manager)
        avg_retries = agent.avg_retries

    collector = get_metrics_collector()
    p50_latency_ms = collector.p50_latency_ms(name)
    p95_latency_ms = collector.p95_latency_ms(name)
    avg_tool_accuracy = collector.avg_tool_accuracy(name)

    # Reliability score: a real, documented composite of success_rate and
    # avg_tool_accuracy (equal weight when both are known; falls back to
    # success_rate alone when there's no tool-call history yet to judge
    # accuracy by — never a fabricated number when inputs are missing).
    if avg_tool_accuracy is not None:
        reliability_score = round(0.5 * success_rate + 0.5 * avg_tool_accuracy, 4)
    else:
        reliability_score = round(success_rate, 4)

    user_approval_rate = await _compute_user_approval_rate(db, name)

    # Persist computed metrics back
    agent.success_rate = success_rate
    agent.last_computed_at = datetime.now(tz=timezone.utc)
    await db.commit()

    return {
        "agentId": agent.agent_id,
        "name": name,
        "successRate": success_rate,
        "avgRetries": avg_retries,
        "totalRuns": total_runs,
        "p50LatencyMs": p50_latency_ms,
        "p95LatencyMs": p95_latency_ms,
        "avgToolAccuracy": avg_tool_accuracy,
        "reliabilityScore": reliability_score,
        "userApprovalRate": user_approval_rate,
        "lastComputedAt": agent.last_computed_at.isoformat(),
    }


@router.post("")
async def register_agent(
    body: RegisterAgentRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Register a new agent. If name already exists, updates capability_tags and tool_list."""
    result = await db.execute(select(Agent).where(Agent.name == body.name))
    existing = result.scalar_one_or_none()

    if existing:
        existing.capability_tags = body.capability_tags
        existing.tool_list = body.tool_list
        existing.prompt_ref = body.prompt_ref
        existing.version = body.version
        await db.commit()
        await db.refresh(existing)
        return {**_agent_to_response(existing), "updated": True}

    agent = Agent(
        agent_id=str(uuid.uuid4()),
        name=body.name,
        capability_tags=body.capability_tags,
        tool_list=body.tool_list,
        prompt_ref=body.prompt_ref,
        version=body.version,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return {**_agent_to_response(agent), "updated": False}
