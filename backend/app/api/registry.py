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


@router.get("/{name}/metrics")
async def get_agent_metrics(
    name: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return live-computed metrics for the agent, then persist the snapshot."""
    result = await db.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Count runs from agent_runs for this agent type
    runs_result = await db.execute(
        select(AgentRun).where(AgentRun.agent_type == name)
    )
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
        "lastComputedAt": agent.last_computed_at.isoformat(),
    }


@router.post("")
async def register_agent(
    body: RegisterAgentRequest,
    db: AsyncSession = Depends(get_db),
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
