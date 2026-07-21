"""Specialized-agent dispatch router.

POST /api/specialized-agents/{agent_name}/run
  → runs any of the 27 worker agents on a task in a background thread
  → saves AgentResult as an artifact and writes to task_logs

Supported agent names:
  Day 2: bug_fix, security_reviewer, arch_reviewer, sql_agent, docker_agent,
          cicd_agent, refactor_agent, readme_agent, api_docs_agent,
          dependency_agent, monitoring_agent
  Day 3: performance_reviewer, style_reviewer, sprint_planner, business_analyst,
          migration_agent, schema_agent, ai_engineer, cleanup_agent, tech_debt_agent
  Gap: release_notes_agent, evaluation_agent, rag_engineer_agent, changelog_agent,
       user_story_generator, security_architect, database_architect
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import append_log, transition_task
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/specialized-agents", tags=["specialized-agents"])

# ──────────────────────────────────────────────────────────────────────────────
# Registry: agent_name → (module_path, function_name)
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, tuple[str, str]] = {
    # Day 2 worker agents
    "bug_fix": ("app.agents.bug_fix", "run_bug_fix"),
    "security_reviewer": ("app.agents.security_reviewer", "run_security_review"),
    "arch_reviewer": ("app.agents.architecture_reviewer", "run_arch_review"),
    "sql_agent": ("app.agents.sql_agent", "run_sql_agent"),
    "docker_agent": ("app.agents.docker_agent", "run_docker_agent"),
    "cicd_agent": ("app.agents.cicd_agent", "run_cicd_agent"),
    "refactor_agent": ("app.agents.refactor_agent", "run_refactor_agent"),
    "readme_agent": ("app.agents.readme_agent", "run_readme_agent"),
    "api_docs_agent": ("app.agents.api_docs_agent", "run_api_docs_agent"),
    "dependency_agent": ("app.agents.dependency_agent", "run_dependency_agent"),
    "monitoring_agent": ("app.agents.monitoring_agent", "run_monitoring_agent"),
    # Day 3 worker agents
    "performance_reviewer": (
        "app.agents.performance_reviewer",
        "run_performance_reviewer",
    ),
    "style_reviewer": ("app.agents.style_reviewer", "run_style_reviewer"),
    "sprint_planner": ("app.agents.sprint_planner", "run_sprint_planner"),
    "business_analyst": ("app.agents.business_analyst", "run_business_analyst"),
    "migration_agent": ("app.agents.migration_agent", "run_migration_agent"),
    "schema_agent": ("app.agents.schema_agent", "run_schema_agent"),
    "ai_engineer": ("app.agents.ai_engineer", "run_ai_engineer"),
    "cleanup_agent": ("app.agents.cleanup_agent", "run_cleanup_agent"),
    "tech_debt_agent": ("app.agents.tech_debt_agent", "run_tech_debt_agent"),
    # Gap agents
    "release_notes_agent": (
        "app.agents.release_notes_agent",
        "run_release_notes_agent",
    ),
    "evaluation_agent": ("app.agents.evaluation_agent", "run_evaluation_agent"),
    "rag_engineer_agent": ("app.agents.rag_engineer_agent", "run_rag_engineer_agent"),
    "changelog_agent": ("app.agents.changelog_agent", "run_changelog_agent"),
    "user_story_generator": (
        "app.agents.user_story_generator",
        "run_user_story_generator",
    ),
    "security_architect": ("app.agents.security_architect", "run_security_architect"),
    "database_architect": ("app.agents.database_architect", "run_database_architect"),
    # Batch 15 — 19 new agents reaching the 60-agent vision
    "infra_agent": ("app.agents.infra_agent", "run_infra_agent"),
    "test_writer_agent": ("app.agents.test_writer_agent", "run_test_writer_agent"),
    "code_explainer_agent": (
        "app.agents.code_explainer_agent",
        "run_code_explainer_agent",
    ),
    "data_pipeline_agent": (
        "app.agents.data_pipeline_agent",
        "run_data_pipeline_agent",
    ),
    "api_designer_agent": ("app.agents.api_designer_agent", "run_api_designer_agent"),
    "env_checker_agent": ("app.agents.env_checker_agent", "run_env_checker_agent"),
    "cost_estimator_agent": (
        "app.agents.cost_estimator_agent",
        "run_cost_estimator_agent",
    ),
    "incident_responder_agent": (
        "app.agents.incident_responder_agent",
        "run_incident_responder_agent",
    ),
    "onboarding_agent": ("app.agents.onboarding_agent", "run_onboarding_agent"),
    "localization_agent": ("app.agents.localization_agent", "run_localization_agent"),
    "accessibility_agent": (
        "app.agents.accessibility_agent",
        "run_accessibility_agent",
    ),
    "compliance_agent": ("app.agents.compliance_agent", "run_compliance_agent"),
    "load_test_agent": ("app.agents.load_test_agent", "run_load_test_agent"),
    "pair_programmer_agent": (
        "app.agents.pair_programmer_agent",
        "run_pair_programmer_agent",
    ),
    "spike_agent": ("app.agents.spike_agent", "run_spike_agent"),
    "rollback_agent": ("app.agents.rollback_agent", "run_rollback_agent"),
    "runbook_generator_agent": (
        "app.agents.runbook_generator_agent",
        "run_runbook_generator_agent",
    ),
    "slo_agent": ("app.agents.slo_agent", "run_slo_agent"),
    "feature_flag_agent": ("app.agents.feature_flag_agent", "run_feature_flag_agent"),
    # Existing pipeline agents also available as standalone dispatch
    "backend_dev": ("app.agents.backend_dev", "run_backend_dev"),
    "frontend_dev": ("app.agents.frontend_dev", "run_frontend_dev"),
    "devops": ("app.agents.devops", "run_devops"),
    "docs_agent": ("app.agents.docs", "run_docs"),
    "qa_agent": ("app.agents.qa", "run_qa"),
    "research_agent": ("app.agents.research", "run_research"),
    "reviewer_agent": ("app.agents.reviewer", "run_reviewer"),
    "executive_agent": ("app.agents.executive", "run_executive"),
    # Final 6 — reaching exactly 60 agents
    "debugger_agent": ("app.agents.debugger_agent", "run_debugger_agent"),
    "test_coverage_agent": (
        "app.agents.test_coverage_agent",
        "run_test_coverage_agent",
    ),
    "code_quality_agent": ("app.agents.code_quality_agent", "run_code_quality_agent"),
    "dependency_security_agent": (
        "app.agents.dependency_security_agent",
        "run_dependency_security_agent",
    ),
    "version_manager_agent": (
        "app.agents.version_manager_agent",
        "run_version_manager_agent",
    ),
    "devex_agent": ("app.agents.devex_agent", "run_devex_agent"),
}

SUPPORTED_AGENTS = sorted(_REGISTRY.keys())


def _load_agent_fn(agent_name: str) -> Callable[..., Any]:
    """Import and return the agent runner function. Raises ValueError for unknown agents."""
    entry = _REGISTRY.get(agent_name)
    if entry is None:
        raise ValueError(f"Unknown agent '{agent_name}'. Supported: {SUPPORTED_AGENTS}")
    module_path, fn_name = entry
    module = importlib.import_module(module_path)
    fn: Callable[..., Any] = getattr(module, fn_name)
    return fn


# ──────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────────────────────────────────────


class RunAgentRequest(BaseModel):
    task_id: int = Field(..., description="ID of the DevTask this agent is working on")
    description: str = Field(
        ..., description="Detailed description / instructions for the agent"
    )
    repo_path: str | None = Field(
        default=None,
        description="Absolute path to the repo. Falls back to active repo if omitted.",
    )


class RunAgentResponse(BaseModel):
    agent: str
    task_id: int
    status: str
    summary: str
    verified: bool
    tokens_in: int
    tokens_out: int
    files_touched: list[str]


# ──────────────────────────────────────────────────────────────────────────────
# Background runner
# ──────────────────────────────────────────────────────────────────────────────


async def _run_specialized_agent_bg(
    agent_name: str,
    task_id: int,
    description: str,
    repo_path: str | None,
) -> None:
    """Fire-and-forget: run a worker agent, save artifact, log result."""
    from app.artifacts.store import save_artifact_async
    from app.db.session import get_session_factory
    from app.services.alert import send_task_alert
    from app.api.repo import get_active_repo_path

    factory = get_session_factory()

    async with factory() as db:
        await append_log(db, task_id, "agent_dispatch", f"Starting {agent_name} …")

        try:
            fn = _load_agent_fn(agent_name)
            effective_repo = repo_path or get_active_repo_path()

            result = await asyncio.to_thread(
                fn,
                task_id=task_id,
                description=description,
                repo_path=effective_repo,
            )

            # Persist as artifact
            artifact_payload: dict[str, Any] = {
                "agent": agent_name,
                "summary": result.summary,
                "findings": result.findings,
                "files_touched": result.files_touched,
                "verified": result.verified,
                "status": result.status,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            }
            await save_artifact_async(
                task_id, agent_name, artifact_payload, agent_name, db=db
            )

            log_msg = (
                f"{agent_name} finished: status={result.status} "
                f"verified={result.verified} tokens_in={result.tokens_in}"
            )
            await append_log(db, task_id, "agent_result", log_msg)

            if result.status == "blocked":
                await transition_task(db, task_id, "blocked")
                await send_task_alert(
                    task_id=task_id,
                    event="blocked",
                    detail=f"{agent_name}: {result.summary[:300]}",
                )

        except Exception as exc:
            logger.exception(
                "Specialized agent %s failed for task %d", agent_name, task_id
            )
            async with factory() as db2:
                await append_log(
                    db2, task_id, "agent_error", f"{agent_name} error: {exc}"
                )
                await send_task_alert(
                    task_id=task_id,
                    event="failed",
                    detail=f"{agent_name} raised exception: {str(exc)[:300]}",
                )


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/agents", summary="List all supported specialized agents")
async def list_specialized_agents() -> dict[str, Any]:
    return {"agents": SUPPORTED_AGENTS, "count": len(SUPPORTED_AGENTS)}


@router.post("/{agent_name}/run", response_model=dict[str, str])
async def run_specialized_agent(
    agent_name: str,
    body: RunAgentRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Dispatch a specialized worker agent on a task asynchronously.

    Returns immediately with {status: "queued"}.
    Check task logs or artifacts for results.
    """
    if agent_name not in _REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown agent '{agent_name}'. Supported: {SUPPORTED_AGENTS}",
        )

    await append_log(
        db, body.task_id, "dispatch", f"Queuing {agent_name} on task {body.task_id}"
    )

    background_tasks.add_task(
        _run_specialized_agent_bg,
        agent_name=agent_name,
        task_id=body.task_id,
        description=body.description,
        repo_path=body.repo_path,
    )

    return {"status": "queued", "agent": agent_name, "task_id": str(body.task_id)}


@router.post("/{agent_name}/run-sync", response_model=RunAgentResponse)
async def run_specialized_agent_sync(
    agent_name: str,
    body: RunAgentRequest,
    db: AsyncSession = Depends(get_db),
) -> RunAgentResponse:
    """Run a specialized agent synchronously and return the full result.

    Use for testing or short-running agents (style_reviewer, business_analyst, etc.).
    For long-running agents prefer the async /run endpoint.
    """
    from app.api.repo import get_active_repo_path
    from app.artifacts.store import save_artifact_async

    if agent_name not in _REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown agent '{agent_name}'. Supported: {SUPPORTED_AGENTS}",
        )

    try:
        fn = _load_agent_fn(agent_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        effective_repo = body.repo_path or get_active_repo_path()
        result = await asyncio.to_thread(
            fn,
            task_id=body.task_id,
            description=body.description,
            repo_path=effective_repo,
        )
    except Exception as exc:
        logger.exception(
            "run-sync failed for agent %s task %d", agent_name, body.task_id
        )
        raise HTTPException(
            status_code=500, detail=f"{agent_name} failed: {exc}"
        ) from exc

    await save_artifact_async(
        body.task_id,
        agent_name,
        {
            "agent": agent_name,
            "summary": result.summary,
            "findings": result.findings,
            "files_touched": result.files_touched,
            "verified": result.verified,
            "status": result.status,
        },
        agent_name,
        db=db,
    )

    await append_log(
        db,
        body.task_id,
        "agent_result",
        f"{agent_name} sync: status={result.status} verified={result.verified}",
    )

    return RunAgentResponse(
        agent=agent_name,
        task_id=body.task_id,
        status=result.status,
        summary=result.summary,
        verified=result.verified,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        files_touched=result.files_touched,
    )
