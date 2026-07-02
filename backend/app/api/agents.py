"""Background task launchers — wire agents into FastAPI via BackgroundTasks."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repository import (
    append_log,
    create_agent_run,
    finish_agent_run,
    heartbeat_agent_run,
    save_subtasks,
    transition_task,
    update_pipeline_state,
    update_task_diff,
    update_task_plan,
)
from app.db.session import get_session_factory
from app.repo_tools.worktree import create_worktree, get_diff, remove_worktree

logger = logging.getLogger(__name__)


async def _get_db() -> AsyncSession:
    factory = get_session_factory()
    return factory()


# ---- Planning pipeline (PM → Architect → Decomposer) ----

async def launch_planning_pipeline(task_id: int, title: str, description: str) -> None:
    """Fire-and-forget: run planning pipeline and persist state to DB."""
    from app.pipeline.graph import run_planning_pipeline

    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        try:
            await update_pipeline_state(db, task_id, "pm")
            await append_log(db, task_id, "pipeline", "Planning pipeline started")

            result = await run_planning_pipeline(
                task_id=task_id,
                title=title,
                description=description,
                repo_path=settings.target_repo_path,
            )

            stage = result.get("stage", "blocked")
            error = result.get("error")

            if stage == "blocked":
                await update_pipeline_state(db, task_id, "blocked")
                await transition_task(db, task_id, "blocked")
                await append_log(db, task_id, "pipeline_error", error or "Pipeline blocked")
                return

            # Persist outputs
            pm_brief = result.get("pm_brief", {})
            architect_plan = result.get("architect_plan", {})
            subtasks = result.get("subtasks", [])

            await update_pipeline_state(
                db,
                task_id,
                "done",
                pm_brief=pm_brief,
                architect_plan=architect_plan,
                subtasks_json=subtasks,
            )

            if subtasks:
                await save_subtasks(db, task_id, subtasks)

            await transition_task(db, task_id, "ready_for_review")
            await append_log(
                db, task_id, "pipeline",
                f"Pipeline complete — {len(subtasks)} subtasks, risk_level={architect_plan.get('risk_level', 'unknown')}"
            )
        except Exception as e:
            logger.exception("Planning pipeline failed for task %d", task_id)
            async with factory() as db2:
                await append_log(db2, task_id, "pipeline_error", str(e))


# ---- Planner Agent (single plan without full pipeline) ----

async def launch_planner(task_id: int, title: str, description: str) -> None:
    """Fire-and-forget: run planner agent in simple mode."""
    from app.agents.planner import run_planner

    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        run = await create_agent_run(db, task_id, "planner", settings.model_coder)
        run_id = str(run.id)

        def heartbeat() -> None:
            asyncio.create_task(heartbeat_agent_run(db, run_id))

        def on_tool(name: str, inp: Any, result: Any) -> None:
            asyncio.create_task(
                append_log(db, task_id, "tool_call", f"{name}: {str(result)[:200]}")
            )

        try:
            plan, error = await asyncio.to_thread(
                run_planner,
                task_id=task_id,
                title=title,
                description=description,
                repo_path=settings.target_repo_path,
                on_heartbeat=heartbeat,
                on_tool_call=on_tool,
            )
        except Exception as e:
            error = str(e)
            plan = ""

        if error:
            await finish_agent_run(db, run_id, "failed", error=error)
            await transition_task(db, task_id, "blocked")
            await append_log(db, task_id, "error", error)
        else:
            await update_task_plan(db, task_id, plan)
            await finish_agent_run(db, run_id, "completed")
            await transition_task(db, task_id, "ready_for_review")
            await append_log(db, task_id, "plan", f"Plan ready ({len(plan)} chars)")


# ---- Coder Agent ----

async def launch_coder(task_id: int, plan: str) -> None:
    """Fire-and-forget: create worktree, run coder agent, store diff."""
    from app.agents.coder import run_coder

    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        run = await create_agent_run(db, task_id, "coder", settings.model_coder)
        run_id = str(run.id)

        wt_path = None
        try:
            wt = create_worktree(task_id)
            wt_path = str(wt)

            await append_log(db, task_id, "worktree", f"Worktree created: {wt_path}")

            def heartbeat() -> None:
                asyncio.create_task(heartbeat_agent_run(db, run_id))

            files_changed, error = await asyncio.to_thread(
                run_coder,
                task_id=task_id,
                plan=plan,
                worktree_path=wt_path,
                repo_path=settings.target_repo_path,
                on_heartbeat=heartbeat,
            )

            if error:
                await finish_agent_run(db, run_id, "failed", error=error)
                await transition_task(db, task_id, "blocked")
                await append_log(db, task_id, "error", error)
            else:
                diff = get_diff(task_id)
                await update_task_diff(db, task_id, diff, files_changed)
                await finish_agent_run(db, run_id, "completed")
                await transition_task(db, task_id, "testing")
                await transition_task(db, task_id, "ready_for_review")
                await append_log(db, task_id, "diff", f"Diff ready — {len(files_changed)} files changed")
        except Exception as e:
            logger.exception("Coder failed for task %d", task_id)
            async with factory() as db2:
                await finish_agent_run(db2, run_id, "failed", error=str(e))
                await append_log(db2, task_id, "error", str(e))
