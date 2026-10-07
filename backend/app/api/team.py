"""Team API for the Agents page (UI redesign, 2026-10-07).

GET    /api/team/agents                        — every built-in agent, by category
GET    /api/team/tools                         — tools a custom agent may use
GET    /api/team/custom-agents                 — user-created agents
POST   /api/team/custom-agents                 — create one
DELETE /api/team/custom-agents/{id}            — delete one (and its runs)
POST   /api/team/custom-agents/{id}/runs       — run it on a project
GET    /api/team/custom-agents/{id}/runs       — its runs, newest first

A custom agent runs on demand against one project's folder through the same
read-only agent runtime barot_agent's temporary agents use
(make_temporary_agent_tools_and_handlers + run_agent_graph): it can read,
search and analyse code and report back, never edit files or run commands.
It is not registered for automatic dispatch, so it is only ever used when a
user runs it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.budget_gate import require_daily_budget
from app.db import get_db
from app.db.models import CustomAgent, CustomAgentRun, Project, Repo
from app.middleware.rbac import require_approver, require_authenticated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team", tags=["team"])

_NOT_FOR_CUSTOM_AGENTS = {"bhaskar_tool"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{1,99}$")


def _tool_choices() -> list[dict[str, str]]:
    from app.agents.tools import READ_ONLY_TOOLS

    return [
        {
            "name": str(t["name"]),
            "description": str(t.get("description", "")).split("\n")[0][:200],
        }
        for t in READ_ONLY_TOOLS
        # bhaskar_tool writes and runs code (in its sandbox) and searches the
        # web: not "read and analyse", so not offered to custom agents
        if t["name"] not in _NOT_FOR_CUSTOM_AGENTS
    ]


class CreateCustomAgentRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    purpose: str = Field(..., min_length=10, max_length=8000)
    tools: list[str] = Field(..., min_length=1)
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not _NAME_RE.match(v):
            raise ValueError(
                "Use 2-100 letters, numbers, spaces, dots, dashes or underscores."
            )
        return v


class RunRequest(BaseModel):
    project_id: int
    request: str = Field(..., min_length=3, max_length=20000)


def _agent_dict(a: CustomAgent) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "purpose": a.purpose,
        "tools": list(a.tools or []),
        "capabilities": list(a.capabilities or []),
        "createdBy": a.created_by,
        "createdAt": a.created_at.isoformat() if a.created_at else None,
    }


def _run_dict(r: CustomAgentRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "agentId": r.agent_id,
        "projectId": r.project_id,
        "request": r.request,
        "status": r.status,
        "summary": r.summary,
        "result": r.result,
        "tokensIn": r.tokens_in,
        "tokensOut": r.tokens_out,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
    }


# ---------------------------------------------------------------- catalog


@router.get("/agents")
async def list_built_in_agents(
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    from app.fleet.agent_catalog import build_catalog

    return await asyncio.to_thread(build_catalog)


@router.get("/tools")
async def list_tools(_actor: str = Depends(require_authenticated)) -> dict[str, Any]:
    return {"tools": _tool_choices()}


# ---------------------------------------------------------------- custom agents


@router.get("/custom-agents")
async def list_custom_agents(
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    rows = (
        await db.execute(select(CustomAgent).order_by(CustomAgent.created_at.desc()))
    ).scalars()
    return {"agents": [_agent_dict(a) for a in rows]}


@router.post("/custom-agents", status_code=201)
async def create_custom_agent(
    body: CreateCustomAgentRequest,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, Any]:
    from app.fleet.capability_registry import (
        ensure_all_agents_registered,
        get_capability_registry,
    )

    allowed = {t["name"] for t in _tool_choices()}
    unknown = sorted(set(body.tools) - allowed)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Custom agents can only use read-only tools; not allowed: {unknown}",
        )
    await asyncio.to_thread(ensure_all_agents_registered)
    built_in = {n.lower() for n in get_capability_registry().names()}
    if body.name.lower().replace(" ", "_") in built_in:
        raise HTTPException(
            status_code=400, detail="That name belongs to a built-in agent."
        )
    exists = (
        await db.execute(select(CustomAgent).where(CustomAgent.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(
            status_code=400, detail="An agent with this name already exists."
        )
    agent = CustomAgent(
        name=body.name,
        purpose=body.purpose.strip(),
        tools=sorted(set(body.tools)),
        capabilities=[c.strip() for c in body.capabilities if c.strip()],
        created_by=actor,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return _agent_dict(agent)


@router.delete("/custom-agents/{agent_id}")
async def delete_custom_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    agent = await db.get(CustomAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.commit()
    return {"deleted": True, "id": agent_id}


@router.get("/custom-agents/{agent_id}/runs")
async def list_runs(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(CustomAgentRun)
            .where(CustomAgentRun.agent_id == agent_id)
            .order_by(CustomAgentRun.id.desc())
            .limit(50)
        )
    ).scalars()
    return {"runs": [_run_dict(r) for r in rows]}


@router.post(
    "/custom-agents/{agent_id}/runs",
    status_code=202,
    dependencies=[Depends(require_daily_budget)],
)
async def run_custom_agent(
    agent_id: int,
    body: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_approver),
) -> dict[str, Any]:
    agent = await db.get(CustomAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    project = await db.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = await db.get(Repo, project.repo_id) if project.repo_id else None
    folder = (repo.local_path if repo and repo.status == "ready" else None) or (
        project.local_path if not project.repo_id else None
    )
    if not folder:
        raise HTTPException(
            status_code=400,
            detail="This project's files are not ready yet (still downloading?).",
        )
    run = CustomAgentRun(
        agent_id=agent.id,
        project_id=project.id,
        request=body.request.strip(),
        status="running",
        created_by=actor,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background_tasks.add_task(
        _execute_run,
        run.id,
        agent.name,
        agent.purpose,
        list(agent.tools or []),
        folder,
        run.request,
    )
    return _run_dict(run)


def _run_agent(
    run_id: int, name: str, purpose: str, tools: list[str], folder: str, request: str
) -> dict[str, Any]:
    """The agent run itself (blocking; called in a worker thread)."""
    from app.agents.base_graph import VerificationConfig, run_agent_graph
    from app.agents.temporary_agent import make_temporary_agent_tools_and_handlers
    from app.config import get_settings

    specs, handlers = make_temporary_agent_tools_and_handlers(
        tool_names=tools, scope="planned", repo_path=folder
    )
    initial_message = (
        f"You are '{name}', a specialist created by the user.\n\n"
        f"Your job:\n{purpose}\n\n"
        f"The user asks:\n{request}\n\n"
        f"You may use only these read-only tools: {', '.join(sorted(tools))}. "
        "Look at the project's files as needed, then call "
        "submit_temporary_agent_result with a clear, plain-language summary."
    )
    state = run_agent_graph(
        task_id=f"custom-agent-run-{run_id}",
        role_name="temporary_agent",
        model=get_settings().model_coder,
        tools=specs,
        tool_handlers=handlers,
        verification_cfg=VerificationConfig(),
        initial_message=initial_message,
        task_description=f"Custom agent {name}: {request[:200]}",
        repo_path=folder,
        enable_planning=False,
        enable_memory=False,
        enable_reflection=False,
        enable_lesson=False,
        enable_critique=False,
        enable_replanning=False,
        max_turns=12,
    )
    return dict(state)


async def _execute_run(
    run_id: int, name: str, purpose: str, tools: list[str], folder: str, request: str
) -> None:
    from app.db.session import get_async_session

    status, summary, result, tin, tout = "failed", None, None, 0, 0
    try:
        state = await asyncio.to_thread(
            _run_agent, run_id, name, purpose, tools, folder, request
        )
        raw = state.get("result") or {}
        tin, tout = int(state.get("tokens_in", 0)), int(state.get("tokens_out", 0))
        if state.get("submitted"):
            status = "blocked" if raw.get("status") == "blocked" else "completed"
            summary = str(raw.get("summary") or "Finished with no summary.")
            result = raw
        else:
            status = "blocked"
            summary = "The agent stopped before giving its answer (turn limit)."
    except Exception as exc:
        logger.exception("custom agent run %s failed", run_id)
        summary = f"The run failed: {type(exc).__name__}: {exc}"[:2000]
    async with get_async_session() as db:
        run = await db.get(CustomAgentRun, run_id)
        if run is not None:
            run.status = status
            run.summary = summary
            run.result = result
            run.tokens_in = tin
            run.tokens_out = tout
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
