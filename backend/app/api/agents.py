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
from app.repo_tools.worktree import create_worktree, get_diff, preserve_worktree
from app.services.alert import send_task_alert

logger = logging.getLogger(__name__)

# Haiku cost estimate: ~$0.80/M input, $4.00/M output (per Anthropic pricing)
_COST_PER_INPUT_TOKEN = 0.0000008
_COST_PER_OUTPUT_TOKEN = 0.000004


def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in * _COST_PER_INPUT_TOKEN + tokens_out * _COST_PER_OUTPUT_TOKEN, 6
    )


# ---- Planning pipeline (PM → Architect → Decomposer, with interrupt) ----


async def launch_planning_pipeline(
    task_id: int, title: str, description: str, repo_path: str | None = None
) -> None:
    """
    Fire-and-forget: run PM→Architect→Decomposer and pause at human_review.
    Sets pipeline_state.stage = 'awaiting_approval' — does NOT transition the
    task to ready_for_review yet; that happens after resume_planning_pipeline().
    """
    from app.pipeline.graph import run_planning_pipeline
    from app.artifacts.store import save_artifact_async

    factory = get_session_factory()

    async with factory() as db:
        try:
            await update_pipeline_state(db, task_id, "pm")
            await append_log(
                db,
                task_id,
                "pipeline",
                "Planning pipeline started (PM → Architect → Decomposer)",
            )

            from app.api.repo import get_active_repo_path

            result = await run_planning_pipeline(
                task_id=task_id,
                title=title,
                description=description,
                repo_path=repo_path or get_active_repo_path(),
                db=db,
            )

            stage = result.get("stage", "blocked")
            error = result.get("error")

            if stage == "blocked":
                await update_pipeline_state(db, task_id, "blocked")
                await transition_task(db, task_id, "blocked")
                await append_log(
                    db, task_id, "pipeline_error", error or "Pipeline blocked"
                )
                await send_task_alert(task_id, "blocked", error or "Pipeline blocked")
                return

            # LangGraph's interrupt() inside human_review_node causes ainvoke() to return
            # with stage="done" (what decomposer set) — the "awaiting_approval" value set
            # inside the node is never returned because the node is paused at interrupt().
            # ANY non-blocked result here means the graph is waiting at the human_review
            # checkpoint; we always need to ask for human approval.
            pm_brief = result.get("pm_brief", {}) or {}
            architect_plan = result.get("architect_plan", {}) or {}
            subtasks = result.get("subtasks", []) or []

            await update_pipeline_state(
                db,
                task_id,
                "awaiting_approval",
                pm_brief=pm_brief,
                architect_plan=architect_plan,
                subtasks_json=subtasks,
            )
            if subtasks:
                await save_subtasks(db, task_id, subtasks)

            # Day 13 — generic approvals index. Recorded here (after ainvoke()
            # confirms the real pause), never inside human_review_node itself —
            # LangGraph re-runs the whole node body on resume, so a write there
            # would duplicate on every approve/reject cycle.
            try:
                from app.fleet.approval_gate import arecord_pending

                await arecord_pending(
                    thread_id=f"task-{task_id}",
                    action="plan_review",
                    details={
                        "subtasks_count": len(subtasks),
                        "risk_level": architect_plan.get("risk_level", "unknown"),
                        "technical_approach": str(
                            architect_plan.get("technical_approach", "")
                        )[:500],
                    },
                    agent_name="decomposer",
                    task_id=task_id,
                )
            except Exception:
                logger.warning(
                    "Failed to record pending approval for task %d",
                    task_id,
                    exc_info=True,
                )

            if pm_brief:
                await save_artifact_async(
                    task_id, "pm_brief", pm_brief, "pm_agent", db=db
                )
            if architect_plan:
                await save_artifact_async(
                    task_id, "architect_plan", architect_plan, "architect_agent", db=db
                )
            if subtasks:
                await save_artifact_async(
                    task_id,
                    "subtasks",
                    {"subtasks": subtasks},
                    "decomposer_agent",
                    db=db,
                )

            await append_log(
                db,
                task_id,
                "pipeline",
                f"Planning complete — awaiting human approval. "
                f"{len(subtasks)} subtasks, "
                f"risk_level={architect_plan.get('risk_level', 'unknown')}",
            )

        except Exception as e:
            logger.exception("Planning pipeline failed for task %d", task_id)
            async with factory() as db2:
                await append_log(db2, task_id, "pipeline_error", str(e))
            await send_task_alert(
                task_id, "failed", f"Planning pipeline exception: {e}"
            )


async def resume_planning_pipeline(
    task_id: int, approved: bool, repo_path: str | None = None
) -> None:
    """
    Resume the LangGraph from its interrupt checkpoint.
    approved=True  → launch manager with subtasks (full Dev→QA→Review pipeline).
    approved=False → transition task to rejected.
    """
    from app.pipeline.graph import resume_pipeline

    factory = get_session_factory()

    async with factory() as db:
        try:
            result = await resume_pipeline(task_id=task_id, approved=approved)
            stage = result.get("stage", "rejected")

            try:
                from app.fleet.approval_gate import arecord_decision

                await arecord_decision(
                    thread_id=f"task-{task_id}", approved=approved, decided_by="user"
                )
            except Exception:
                logger.warning(
                    "Failed to record approval decision for task %d",
                    task_id,
                    exc_info=True,
                )

            try:
                from app.fleet.audit_log import get_audit_log

                get_audit_log().record_approval(
                    agent_name="decomposer",
                    action_type="plan_review",
                    description=f"Plan review for task {task_id}",
                    approved=approved,
                    task_id=str(task_id),
                )
            except Exception:
                logger.warning(
                    "Failed to write audit log entry for task %d",
                    task_id,
                    exc_info=True,
                )

            if approved and stage == "done":
                await update_pipeline_state(db, task_id, "done", approved=True)
                await transition_task(db, task_id, "ready_for_review")
                await append_log(
                    db, task_id, "pipeline", "Plan approved — coding agents launching"
                )
                plan = _build_plan_summary(result)
                subtasks = result.get("subtasks", [])
                # Launch multi-agent manager pipeline instead of single coder
                asyncio.create_task(launch_manager(task_id, subtasks, plan, repo_path))
            else:
                await update_pipeline_state(db, task_id, "rejected")
                await transition_task(db, task_id, "rejected")
                await append_log(
                    db, task_id, "pipeline", "Plan rejected by human reviewer"
                )

        except Exception as e:
            logger.exception("resume_planning_pipeline failed for task %d", task_id)
            async with factory() as db2:
                await append_log(db2, task_id, "pipeline_error", f"Resume failed: {e}")


def _build_plan_summary(pipeline_result: Any) -> str:
    """Convert pipeline state into a readable plan string for the coder."""
    arch = pipeline_result.get("architect_plan", {})
    subtasks = pipeline_result.get("subtasks", [])
    lines = [
        "## Architect Plan",
        arch.get("technical_approach", ""),
        "",
        "## Files To Inspect",
    ]
    for f in arch.get("impacted_files", []):
        lines.append(f"- {f.get('path', '')}: {f.get('reason', '')}")
    lines += ["", "## Implementation Steps"]
    for i, sub in enumerate(subtasks, 1):
        lines.append(
            f"{i}. [{sub.get('type', '')}] {sub.get('title', '')}: {sub.get('description', '')}"
        )
    return "\n".join(lines)


# ---- Manager (full multi-agent pipeline) ----


async def _record_git_push_approval(
    db: AsyncSession,
    task_id: int,
    effective_repo: str,
    all_files: list[str],
    diff: str,
    subtask_count: int,
) -> None:
    """Day 14 — Git Push Workflow. Registers into Day 13's generic approvals
    system (same table/API the plan-review pause already uses) rather than
    inventing a parallel one. Distinct thread_id from the plan-review pause
    (f"task-{id}") since this is a second, later decision point for the same
    task. Extracted as its own function (not inlined in launch_manager) so it
    can be tested directly against a real, isolated DB session without
    needing to drive the full pipeline+fire-and-forget-task machinery."""
    try:
        from sqlalchemy import select

        from app.db.models import Repo
        from app.db.repository import update_task_branch_name
        from app.fleet.approval_gate import arecord_pending

        branch_name = f"agent/task-{task_id}"
        await update_task_branch_name(db, task_id, branch_name)
        repo_row = (
            await db.execute(select(Repo).where(Repo.local_path == effective_repo))
        ).scalar_one_or_none()
        if repo_row is not None and repo_row.github_url:
            await arecord_pending(
                thread_id=f"task-{task_id}-push",
                action="git_push",
                details={
                    "branch": branch_name,
                    "files_changed": list(dict.fromkeys(all_files))[:20],
                    "subtask_count": subtask_count,
                    "diff_preview": diff[:500],
                },
                agent_name="manager",
                task_id=task_id,
            )
        else:
            logger.debug(
                "No GitHub-cloned repo found for task %d (path=%s) — skipping push approval",
                task_id, effective_repo,
            )
    except Exception:
        logger.warning("Failed to record git-push pending approval for task %d", task_id, exc_info=True)


async def launch_manager(
    task_id: int,
    subtasks: list[dict[str, Any]],
    plan: str,
    repo_path: str | None = None,
) -> None:
    """
    Fire-and-forget: dispatch each subtask through Dev → QA → Review.
    Updates pipeline stage and task status. Saves artifacts per subtask.
    """
    from app.agents.manager import run_manager
    from app.artifacts.store import save_artifact_async

    factory = get_session_factory()

    async with factory() as db:
        wt_path: str | None = None
        try:
            wt = create_worktree(task_id)
            wt_path = str(wt)
            await append_log(db, task_id, "worktree", f"Worktree created: {wt_path}")
            await update_pipeline_state(db, task_id, "dev_running")
            await transition_task(db, task_id, "coding")

            def on_status(subtask_id: int, status: str) -> None:
                asyncio.create_task(
                    append_log(
                        db, task_id, "pipeline", f"Subtask {subtask_id}: {status}"
                    )
                )

            from app.api.repo import get_active_repo_path

            effective_repo = repo_path or get_active_repo_path()
            result = await run_manager(
                task_id=task_id,
                subtasks=subtasks,
                worktree_path=wt_path,
                plan=plan,
                repo_path=effective_repo,
                on_status=on_status,
            )

            overall_status = result.get("status", "blocked")
            results = result.get("results", [])

            # Save per-subtask review findings as artifacts
            for r in results:
                if r.get("review_summary"):
                    await save_artifact_async(
                        task_id,
                        "review_findings",
                        {
                            "subtask_id": r["subtask_id"],
                            "review_summary": r["review_summary"],
                            "files_changed": r.get("files_changed", []),
                        },
                        "reviewer",
                        db=db,
                    )

            if overall_status == "completed":
                diff = get_diff(task_id, effective_repo)
                all_files: list[str] = []
                for r in results:
                    all_files.extend(r.get("files_changed", []))
                await update_task_diff(
                    db, task_id, diff, list(dict.fromkeys(all_files))
                )
                # Save diff artifact
                if diff:
                    await save_artifact_async(task_id, "diff", diff, "manager", db=db)
                preserve_worktree(task_id)
                await update_pipeline_state(db, task_id, "dev_complete")
                await transition_task(db, task_id, "testing")
                await transition_task(db, task_id, "ready_for_review")
                await append_log(
                    db,
                    task_id,
                    "pipeline",
                    f"All subtasks complete — {len(results)} subtasks, diff ready for review",
                )

                await _record_git_push_approval(db, task_id, effective_repo, all_files, diff, len(results))
            else:
                preserve_worktree(task_id)
                await update_pipeline_state(db, task_id, "blocked")
                await transition_task(db, task_id, "blocked")
                await append_log(
                    db,
                    task_id,
                    "pipeline_error",
                    "Manager blocked — max retries exceeded on a subtask",
                )
                await send_task_alert(
                    task_id,
                    "blocked",
                    "Manager blocked — max retries exceeded on a subtask",
                )

        except Exception as e:
            logger.exception("Manager pipeline failed for task %d", task_id)
            async with factory() as db2:
                await update_pipeline_state(db2, task_id, "blocked")
                await append_log(db2, task_id, "pipeline_error", f"Manager failed: {e}")
            await send_task_alert(task_id, "failed", f"Manager pipeline exception: {e}")


# ---- Planner Agent (simple mode: single plan, no LangGraph) ----


async def launch_planner(
    task_id: int, title: str, description: str, repo_path: str | None = None
) -> None:
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
            from app.api.repo import get_active_repo_path

            plan, error, tokens_in, tokens_out = await asyncio.to_thread(
                run_planner,
                task_id=task_id,
                title=title,
                description=description,
                repo_path=repo_path or get_active_repo_path(),
                on_heartbeat=heartbeat,
                on_tool_call=on_tool,
            )
        except Exception as e:
            error = str(e)
            plan = ""
            tokens_in = 0
            tokens_out = 0

        cost = _estimate_cost(tokens_in, tokens_out)

        if error:
            await finish_agent_run(
                db,
                run_id,
                "failed",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_estimate=cost,
                error=error,
            )
            await transition_task(db, task_id, "blocked")
            await append_log(db, task_id, "error", error)
        else:
            await update_task_plan(db, task_id, plan)
            await finish_agent_run(
                db,
                run_id,
                "completed",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_estimate=cost,
            )
            await transition_task(db, task_id, "ready_for_review")
            await append_log(
                db,
                task_id,
                "plan",
                f"Plan ready ({len(plan)} chars) — tokens_in={tokens_in} tokens_out={tokens_out} cost=${cost:.4f}",
            )


# ---- Coder Agent (simple mode: single coder after planner) ----


async def launch_coder(task_id: int, plan: str, repo_path: str | None = None) -> None:
    from app.agents.coder import run_coder
    from app.artifacts.store import save_artifact_async

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

            from app.api.repo import get_active_repo_path

            files_changed, error, tokens_in, tokens_out = await asyncio.to_thread(
                run_coder,
                task_id=task_id,
                plan=plan,
                worktree_path=wt_path,
                repo_path=repo_path or get_active_repo_path(),
                on_heartbeat=heartbeat,
            )

            cost = _estimate_cost(tokens_in, tokens_out)

            if error:
                await finish_agent_run(
                    db,
                    run_id,
                    "failed",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_estimate=cost,
                    error=error,
                )
                preserve_worktree(task_id)
                await transition_task(db, task_id, "blocked")
                await append_log(db, task_id, "error", error)
            else:
                diff = get_diff(task_id)
                await update_task_diff(db, task_id, diff, files_changed)
                if diff:
                    await save_artifact_async(task_id, "diff", diff, "coder", db=db)
                await finish_agent_run(
                    db,
                    run_id,
                    "completed",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_estimate=cost,
                )
                preserve_worktree(task_id)
                await transition_task(db, task_id, "testing")
                await transition_task(db, task_id, "ready_for_review")
                await append_log(
                    db,
                    task_id,
                    "diff",
                    f"Diff ready — {len(files_changed)} files changed, tokens_in={tokens_in} cost=${cost:.4f}",
                )

        except Exception as e:
            logger.exception("Coder failed for task %d", task_id)
            async with factory() as db2:
                await finish_agent_run(db2, run_id, "failed", error=str(e))
                await append_log(db2, task_id, "error", str(e))
