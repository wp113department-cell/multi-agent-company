"""Background task launchers — wire agents into FastAPI via BackgroundTasks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repository import (
    TransitionError,
    append_log,
    create_agent_run,
    finish_agent_run,
    heartbeat_agent_run,
    save_subtasks,
    transition_task,
    update_pipeline_state,
    update_task_assigned_agent,
    update_task_diff,
    update_task_final_summary,
    update_task_plan,
)
from app.db.session import get_session_factory
from app.repo_tools.worktree import create_worktree, get_diff, preserve_worktree
from app.services.alert import send_task_alert

logger = logging.getLogger(__name__)

# Haiku cost estimate: ~$0.80/M input, $4.00/M output (per Anthropic pricing)
_COST_PER_INPUT_TOKEN = 0.0000008
_COST_PER_OUTPUT_TOKEN = 0.000004

# Gap-closure (Audit 04 fix, ORCH-04-014): asyncio.create_task()'s own docs
# warn "save a reference to the result of this function, to avoid a task
# disappearing mid-execution" — the event loop only holds a weak reference,
# so a task with no other referent can in principle be garbage collected
# before it completes. Several real dispatch points here previously
# discarded the return value outright. This module-level set + done-callback
# is the standard idiom: retains a strong reference until the task finishes,
# then discards it automatically.
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn_tracked(coro: Any) -> "asyncio.Task[Any]":
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_finish_tracked)
    return task


def _finish_tracked(task: "asyncio.Task[Any]") -> None:
    """Production audit 08 (2026-09-30): these fire-and-forget tasks
    (heartbeats, log writes) used to be dropped on completion without anyone
    looking at their exception — without Sentry configured, a failing DB write
    here vanished silently."""
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning(
            "Background task failed: %r", task.exception(), exc_info=task.exception()
        )


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
            await update_task_assigned_agent(db, task_id, "pm")
            await append_log(
                db,
                task_id,
                "pipeline",
                "Planning pipeline started (PM → Architect → Decomposer)",
            )

            from app.api.repo import get_active_repo_path

            effective_repo_path = repo_path or get_active_repo_path()

            # Day 15 — Blank Repo Bootstrap. Must run (and commit) BEFORE any
            # worktree is ever created for this repo: create_worktree() runs
            # `git worktree add -b branch`, which requires an existing commit
            # to branch from and fails outright against a zero-commit repo.
            from app.pipeline.bootstrap import bootstrap, is_blank_repo

            if is_blank_repo(effective_repo_path):
                from app.fleet.fleet_events import publish, task_started, task_completed

                # Gap-closure (Days 0-18 audit): Gap 10's own exit criteria
                # wants a real trace_id on every bus event — stable per task
                # (matches the convention already used for thread_id
                # elsewhere, e.g. f"task-{task_id}" for approval recording).
                bootstrap_trace_id = f"task-{task_id}"
                publish(
                    task_started(
                        str(task_id),
                        agent_name="bootstrap",
                        trace_id=bootstrap_trace_id,
                    )
                )
                bootstrap_result = await bootstrap(
                    task_id, effective_repo_path, description, db=db
                )
                if bootstrap_result.bootstrapped:
                    await append_log(
                        db,
                        task_id,
                        "pipeline",
                        f"Repo bootstrapped ({bootstrap_result.project_type}) — "
                        f"{len(bootstrap_result.files_created)} files, "
                        f"commit {bootstrap_result.commit_sha}",
                    )
                    publish(
                        task_completed(
                            str(task_id),
                            agent_name="bootstrap",
                            summary=f"Scaffolded {bootstrap_result.project_type} project",
                            trace_id=bootstrap_trace_id,
                        )
                    )
                elif bootstrap_result.error:
                    await append_log(
                        db,
                        task_id,
                        "pipeline",
                        f"Bootstrap skipped: {bootstrap_result.error}",
                    )

            result = await run_planning_pipeline(
                task_id=task_id,
                title=title,
                description=description,
                repo_path=effective_repo_path,
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
                from app.fleet.approval_gate import arequest_human_input

                await arequest_human_input(
                    kind="plan_review",
                    details={
                        "subtasks_count": len(subtasks),
                        "risk_level": architect_plan.get("risk_level", "unknown"),
                        "technical_approach": str(
                            architect_plan.get("technical_approach", "")
                        )[:500],
                    },
                    agent_name="decomposer",
                    thread_id=f"task-{task_id}",
                    task_id=task_id,
                    blocking=True,
                    description=f"Plan review for task {task_id}",
                )
            except Exception:
                logger.warning(
                    "Failed to record pending approval for task %d",
                    task_id,
                    exc_info=True,
                )

            # Day 18 — Real-Time Streaming. Separate try/except from the
            # recording above so a stream-push hiccup is never misattributed
            # as an approval-recording failure in the log.
            try:
                from app.services.activity_stream import push_approval_required

                push_approval_required(str(task_id), f"task-{task_id}", "plan_review")
            except Exception:
                pass

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
                # Blocker (audit_v1.md 4.3 #2): this handler used to log and
                # alert but never transition the task out of "planning" —
                # status stayed "planning" forever, and restart_task
                # explicitly refuses tasks in ("planning","coding","testing")
                # (409), leaving no self-service recovery path (only manual
                # DB intervention). Move it to the terminal-ish "blocked"
                # status, which restart_task DOES accept, restoring a real
                # recovery path for the exact failure this except clause
                # catches (e.g. save_subtasks() raising on malformed
                # Decomposer output).
                try:
                    await update_pipeline_state(db2, task_id, "blocked")
                    await transition_task(db2, task_id, "blocked")
                except (TransitionError, ValueError):
                    # Already in a terminal status (e.g. a concurrent
                    # request already moved it) — nothing more to do.
                    pass
            await send_task_alert(
                task_id, "failed", f"Planning pipeline exception: {e}"
            )


async def resume_planning_pipeline(
    task_id: int,
    approved: bool,
    repo_path: str | None = None,
    subtask_edits: list[dict[str, Any]] | None = None,
) -> None:
    """
    Resume the LangGraph from its interrupt checkpoint.
    approved=True  → launch manager with subtasks (full Dev→QA→Review pipeline).
    approved=False → transition task to rejected.

    subtask_edits (#227, 2026-09-28): see
    app.pipeline.graph.apply_subtask_edits's own docstring. A malformed
    edit (bad index, or rejecting a step another step still depends on)
    raises SubtaskEditError, caught below and logged as a pipeline error —
    the plan stays exactly as it was (still awaiting_approval), never
    half-applied.
    """
    from app.pipeline.graph import SubtaskEditError, resume_pipeline

    factory = get_session_factory()

    async with factory() as db:
        try:
            result = await resume_pipeline(
                task_id=task_id, approved=approved, subtask_edits=subtask_edits
            )
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
                    trace_id=f"task-{task_id}",
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
                _spawn_tracked(launch_manager(task_id, subtasks, plan, repo_path))
            else:
                await update_pipeline_state(db, task_id, "rejected")
                await transition_task(db, task_id, "rejected")
                await append_log(
                    db, task_id, "pipeline", "Plan rejected by human reviewer"
                )

        except SubtaskEditError as e:
            # #227 — a malformed edit must never half-apply or corrupt the
            # plan's dependency graph. The graph.ainvoke() call above raised
            # BEFORE human_review_node returned any updated state, so
            # LangGraph's own checkpoint is untouched — the task stays
            # exactly as it was (still awaiting_approval), a real retry is
            # always safe.
            logger.warning("Subtask edit rejected for task %d: %s", task_id, e)
            async with factory() as db2:
                await append_log(
                    db2, task_id, "pipeline_error", f"Subtask edit rejected: {e}"
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
    agent_name: str = "manager",
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
        from app.fleet.approval_gate import arequest_human_input

        branch_name = f"agent/task-{task_id}"
        await update_task_branch_name(db, task_id, branch_name)
        repo_row = (
            await db.execute(select(Repo).where(Repo.local_path == effective_repo))
        ).scalar_one_or_none()
        if repo_row is not None and repo_row.github_url:
            await arequest_human_input(
                kind="git_push",
                details={
                    "branch": branch_name,
                    "files_changed": list(dict.fromkeys(all_files))[:20],
                    "subtask_count": subtask_count,
                    "diff_preview": diff[:500],
                },
                agent_name=agent_name,
                thread_id=f"task-{task_id}-push",
                task_id=task_id,
                blocking=True,
                description=f"Git push review for task {task_id} (branch {branch_name})",
            )
            # pr_status is documented none|pending|pushed|failed, but nothing
            # ever set "pending" (production audit 2026-09-29).
            from app.db.repository import update_task_pr

            await update_task_pr(db, task_id, None, "pending")
            # Day 18 — Real-Time Streaming.
            try:
                from app.services.activity_stream import push_approval_required

                push_approval_required(str(task_id), f"task-{task_id}-push", "git_push")
            except Exception:
                pass
        else:
            logger.debug(
                "No GitHub-cloned repo found for task %d (path=%s) — skipping push approval",
                task_id,
                effective_repo,
            )
    except Exception:
        logger.warning(
            "Failed to record git-push pending approval for task %d",
            task_id,
            exc_info=True,
        )


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
            from app.api.repo import get_active_repo_path

            effective_repo = repo_path or get_active_repo_path()

            # Gap-closure (Days 11-15 audit, 2026-07-22): create_worktree() was
            # called with no repo_path, silently defaulting to
            # settings.target_repo_path instead of this task's actual assigned
            # repo — broken for any task not on the global default repo.
            wt = create_worktree(task_id, effective_repo)
            wt_path = str(wt)
            await append_log(db, task_id, "worktree", f"Worktree created: {wt_path}")
            await update_pipeline_state(db, task_id, "dev_running")
            await transition_task(db, task_id, "coding")
            await update_task_assigned_agent(db, task_id, "manager")

            def on_status(subtask_id: int, status: str) -> None:
                _spawn_tracked(
                    append_log(
                        db, task_id, "pipeline", f"Subtask {subtask_id}: {status}"
                    )
                )

            # Day 16 — Image Input Pipeline. Fetch once here (launch_manager
            # has db access; run_manager()/run_frontend_dev()/run_reviewer()
            # don't) and thread through.
            from app.db.repository import list_task_images

            image_rows = await list_task_images(db, task_id)
            task_images = [
                {"media_type": r.mime_type, "data": r.base64_data} for r in image_rows
            ]

            # Day 17 — Credential Vault. Custom secrets, if any, injected
            # into the coding agents' bash tool env.
            # AUDIT_Q_BATCH14 §95 gap-closure — resolve this task's repo_id
            # so a repo-scoped credential (if one was ever stored) wins over
            # the global fallback; task_id is already in scope here.
            from app.db.repository import get_task_repo_id
            from app.security.credential_vault import get_credential_vault

            _repo_id = await get_task_repo_id(db, task_id)
            custom_secrets_env = (
                await get_credential_vault().load(db, repo_id=_repo_id)
            ).get_env_vars()
            custom_secrets_env.pop("GITHUB_TOKEN", None)
            custom_secrets_env.pop("ANTHROPIC_API_KEY", None)

            # Gap-closure Day 54 (Stage 2, answers.md Q8 "Orchestration
            # speed") — same standalone tracker manager.py's own epic-manager
            # graph call site uses.
            import time as _time

            from app.fleet.orchestration_analytics import record_orchestration_time

            _t0 = _time.monotonic()
            result = await run_manager(
                task_id=task_id,
                subtasks=subtasks,
                worktree_path=wt_path,
                plan=plan,
                repo_path=effective_repo,
                on_status=on_status,
                images=task_images,
                extra_env=custom_secrets_env or None,
                db=db,
            )
            record_orchestration_time("run_manager", (_time.monotonic() - _t0) * 1000)

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
                summary = (
                    f"All subtasks complete — {len(results)} subtasks, "
                    "diff ready for review"
                )
                await update_task_final_summary(db, task_id, summary)
                await append_log(db, task_id, "pipeline", summary)

                await _record_git_push_approval(
                    db, task_id, effective_repo, all_files, diff, len(results)
                )
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


async def _task_images(db: AsyncSession, task_id: int) -> list[dict[str, str]]:
    """Task's attached reference images as Anthropic image-block inputs — the
    same shape launch_manager builds (Day 16). Production audit 2026-09-29
    (ORCH-04-002): used by simple mode, which previously dropped them."""
    from app.db.repository import list_task_images

    rows = await list_task_images(db, task_id)
    return [{"media_type": r.mime_type, "data": r.base64_data} for r in rows]


async def launch_router(
    task_id: int, title: str, description: str, repo_path: str | None = None
) -> None:
    """PIPELINE_MODE=auto (smart router, 2026-09-29): pick the fewest agents.

    small / medium → no planning agents at all: the routed plan (the task
    itself + which specialist(s) will do it and why) goes straight to the
    usual plan-approval gate; on approval launch_coder runs exactly those
    specialists. large → the full PM → Architect → Decomposer pipeline.
    Routing costs nothing (keyword rules) or one tiny Haiku call."""
    from app.pipeline.task_router import route_task

    decision = await asyncio.to_thread(route_task, title, description)
    factory = get_session_factory()
    async with factory() as db:
        await append_log(
            db,
            task_id,
            "routing",
            f"Routed as {decision.tier} → "
            f"{', '.join(decision.agents) or 'full pipeline'} ({decision.source})",
            rationale=decision.reason,
        )
    if decision.tier == "large":
        await launch_planning_pipeline(task_id, title, description, repo_path)
        return

    plan = (
        f"{description.strip()}\n\n---\n"
        f"Routing: {decision.tier} task → {' then '.join(decision.agents)} "
        f"(reason: {decision.reason}). No separate planning agents were run."
    )
    async with factory() as db:
        try:
            await update_task_plan(db, task_id, plan)
            await update_task_assigned_agent(db, task_id, decision.assigned_agent)
            await transition_task(db, task_id, "ready_for_review")
            await append_log(
                db,
                task_id,
                "plan",
                "Routed plan ready — approve to start "
                f"{' then '.join(decision.agents)}",
            )
        except Exception as exc:
            logger.exception("Routing failed for task %d", task_id)
            await transition_task(db, task_id, "blocked")
            await append_log(db, task_id, "error", f"Routing failed: {exc}")


async def launch_planner(
    task_id: int, title: str, description: str, repo_path: str | None = None
) -> None:
    from app.agents.planner import run_planner

    settings = get_settings()
    factory = get_session_factory()

    async with factory() as db:
        run = await create_agent_run(db, task_id, "planner", settings.model_coder)
        run_id = str(run.id)
        await update_task_assigned_agent(db, task_id, "planner")

        def heartbeat() -> None:
            _spawn_tracked(heartbeat_agent_run(db, run_id))

        def on_tool(name: str, inp: Any, result: Any) -> None:
            _spawn_tracked(
                append_log(db, task_id, "tool_call", f"{name}: {str(result)[:200]}")
            )

        try:
            from app.api.repo import get_active_repo_path

            task_images = await _task_images(db, task_id)
            plan, error, tokens_in, tokens_out = await asyncio.to_thread(
                run_planner,
                task_id=task_id,
                title=title,
                description=description,
                repo_path=repo_path or get_active_repo_path(),
                on_heartbeat=heartbeat,
                on_tool_call=on_tool,
                images=task_images or None,
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


async def resume_planner_after_clarification(task_id: int, answer: str) -> None:
    """AUDIT_Q_BATCH12 §27 gap-closure (2026-08-11) — request_clarification's
    own tool description promises "a future run receives that answer in its
    task context"; nothing previously implemented that promise. planner.py
    returning a "[NEEDS_CLARIFICATION]"-prefixed error made launch_planner
    treat it exactly like any other failure (task -> "blocked"), and the
    separately-recorded "clarification" PendingApproval row had no dispatch
    branch in api/approvals.py::_dispatch_decision — approving it only
    flipped the row's DB status, nothing re-ran the planner.

    Called from api/approvals.py when a human approves a "clarification"
    action with an answer: folds the answer into a fresh planner dispatch,
    mirroring resume_planning_pipeline's "decision recorded -> re-invoke the
    owning flow" shape already used for the "plan_review" action in the same
    file. The task's stored description is left untouched — the answer is
    only folded into THIS run's initial_message/task_description, the same
    way an ordinary re-run's title/description are read fresh from the task
    each time, not persisted as a retroactive edit to the original request.
    """
    from app.db.models import can_transition
    from app.db.repository import get_task, resolve_task_repo_path

    factory = get_session_factory()
    async with factory() as db:
        task = await get_task(db, task_id)
        if task is None:
            logger.warning(
                "resume_planner_after_clarification: task %d not found", task_id
            )
            return
        if not can_transition(str(task.status), "planning"):
            logger.warning(
                "resume_planner_after_clarification: task %d in status %r "
                "cannot resume planning — leaving as-is",
                task_id,
                task.status,
            )
            return

        title = str(task.title)
        description = str(task.description)
        repo_path = resolve_task_repo_path(task)

        await transition_task(db, task_id, "planning")
        await append_log(
            db,
            task_id,
            "pipeline",
            f"Clarification answered — resuming planning. Answer: {answer[:500]}",
        )

    augmented_description = (
        f"{description}\n\n"
        "## Clarification\n"
        "The planner previously paused this task to ask a human a question. "
        f"Here is the human's answer — use it, do not ask the same question "
        f"again:\n{answer}"
    )
    await launch_planner(task_id, title, augmented_description, repo_path)


# ---- Coder Agent (simple mode: single coder after planner) ----


_EXECUTOR_FNS: dict[str, tuple[str, str]] = {
    "coder": ("app.agents.coder", "run_coder"),
    "frontend_dev": ("app.agents.frontend_dev", "run_frontend_dev"),
    "backend_dev": ("app.agents.backend_dev", "run_backend_dev"),
}


async def _run_executors(
    executors: list[str], **kwargs: Any
) -> tuple[list[str], str | None, int, int]:
    """Run each chosen specialist in turn in the same worktree. Each later one
    is told what the earlier ones already changed. Stops at the first error.
    Only the parameters an agent actually accepts are passed (frontend_dev
    takes images, backend_dev doesn't, coder has no subtask_id)."""
    import importlib
    import inspect

    files: list[str] = []
    tokens_in = tokens_out = 0
    base_plan = str(kwargs.pop("plan"))
    for step, name in enumerate(executors, start=1):
        module, fn_name = _EXECUTOR_FNS[name]
        fn = getattr(importlib.import_module(module), fn_name)
        plan = base_plan
        if files:
            plan += (
                "\n\n[Already done in this worktree by the previous step: "
                f"{', '.join(dict.fromkeys(files))}. Build on it; do not redo it.]"
            )
        call: dict[str, Any] = {**kwargs, "plan": plan, "subtask_id": step}
        params = inspect.signature(fn).parameters
        if not any(p.kind is p.VAR_KEYWORD for p in params.values()):
            call = {k: v for k, v in call.items() if k in params}
        changed, error, t_in, t_out = await asyncio.to_thread(fn, **call)
        files.extend(changed or [])
        tokens_in += t_in
        tokens_out += t_out
        if error:
            return files, f"{name}: {error}", tokens_in, tokens_out
    return list(dict.fromkeys(files)), None, tokens_in, tokens_out


async def launch_coder(
    task_id: int,
    plan: str,
    repo_path: str | None = None,
    agents: list[str] | None = None,
) -> None:
    """Run the approved plan in the task's worktree.

    agents (smart router, 2026-09-29): the specialists chosen for this task,
    run in order in the SAME worktree — e.g. ["frontend_dev"] for a UI-only
    change, ["backend_dev", "frontend_dev"] for a change touching both.
    None keeps the original behaviour: the general `coder` agent."""
    from app.artifacts.store import save_artifact_async

    settings = get_settings()
    factory = get_session_factory()
    executors = [a for a in (agents or ["coder"]) if a in _EXECUTOR_FNS] or ["coder"]
    run_label = "+".join(executors)

    async with factory() as db:
        run = await create_agent_run(db, task_id, run_label, settings.model_coder)
        run_id = str(run.id)
        await update_task_assigned_agent(db, task_id, run_label)

        wt_path = None
        try:
            from app.api.repo import get_active_repo_path

            effective_repo = repo_path or get_active_repo_path()

            # Day 15 — Blank Repo Bootstrap. "Simple" pipeline mode never goes
            # through launch_planning_pipeline() (where bootstrap is normally
            # wired) — it needs its own check here, since create_worktree()
            # below fails outright ("invalid reference: HEAD") against a
            # zero-commit repo.
            from app.pipeline.bootstrap import bootstrap, is_blank_repo

            if is_blank_repo(effective_repo):
                await append_log(
                    db,
                    task_id,
                    "pipeline",
                    "Blank repo detected — bootstrapping before coding",
                )
                bootstrap_result = await bootstrap(task_id, effective_repo, plan, db=db)
                if bootstrap_result.bootstrapped:
                    await append_log(
                        db,
                        task_id,
                        "pipeline",
                        f"Repo bootstrapped ({bootstrap_result.project_type}) — "
                        f"{len(bootstrap_result.files_created)} files, "
                        f"commit {bootstrap_result.commit_sha}",
                    )
                elif bootstrap_result.error:
                    await append_log(
                        db,
                        task_id,
                        "pipeline",
                        f"Bootstrap skipped: {bootstrap_result.error}",
                    )

            wt = create_worktree(task_id, effective_repo)
            wt_path = str(wt)
            await append_log(db, task_id, "worktree", f"Worktree created: {wt_path}")

            def heartbeat() -> None:
                _spawn_tracked(heartbeat_agent_run(db, run_id))

            # Day 17 — Credential Vault. Custom secrets, if any.
            # AUDIT_Q_BATCH14 §95 gap-closure — same repo-scoped-with-
            # global-fallback lookup as launch_manager above.
            from app.db.repository import get_task_repo_id
            from app.security.credential_vault import get_credential_vault

            _repo_id = await get_task_repo_id(db, task_id)
            custom_secrets_env = (
                await get_credential_vault().load(db, repo_id=_repo_id)
            ).get_env_vars()
            custom_secrets_env.pop("GITHUB_TOKEN", None)
            custom_secrets_env.pop("ANTHROPIC_API_KEY", None)

            task_images = await _task_images(db, task_id)
            files_changed, error, tokens_in, tokens_out = await _run_executors(
                executors,
                task_id=task_id,
                plan=plan,
                worktree_path=wt_path,
                repo_path=effective_repo,
                on_heartbeat=heartbeat,
                extra_env=custom_secrets_env or None,
                images=task_images or None,
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
                # Gap-closure (Audit 04, ORCH-04-001): nothing in this path ever
                # committed files_changed to the worktree's branch — the same
                # bug Day 14 fixed for run_manager()'s full-mode loop
                # (manager.py's git_add+git_commit step), never applied here.
                # Without a commit, get_diff() (HEAD...branch) always returns
                # empty even though files_changed is non-empty, so the human
                # reviewer sees no diff for a task that actually wrote code.
                if files_changed:
                    from app.services.git_service import git_add, git_commit

                    add_result = await git_add(wt_path, files_changed)
                    if add_result["ok"]:
                        commit_result = await git_commit(
                            wt_path,
                            f"coder: task {task_id}",
                            author_name="Gridiron Agent",
                            author_email="agent@gridiron.local",
                        )
                        if not commit_result["ok"]:
                            logger.warning(
                                "Commit failed for task %d: %s",
                                task_id,
                                commit_result["stderr"][:300],
                            )
                    else:
                        logger.warning(
                            "git add failed for task %d: %s",
                            task_id,
                            add_result["stderr"][:300],
                        )

                diff = get_diff(task_id, effective_repo)
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
                summary = (
                    f"Diff ready — {len(files_changed)} files changed, "
                    f"tokens_in={tokens_in} cost=${cost:.4f}"
                )
                await update_task_final_summary(db, task_id, summary)
                await append_log(db, task_id, "diff", summary)
                # Production audit 2026-09-29 (ORCH-04-003): simple mode never
                # recorded the git-push approval full mode records — and that
                # call is also what sets branch_name, which POST
                # /api/tasks/{id}/push requires, so a simple-mode task could
                # never be pushed or turned into a PR at all.
                await _record_git_push_approval(
                    db,
                    task_id,
                    effective_repo,
                    files_changed,
                    diff,
                    1,
                    agent_name="coder",
                )

        except Exception as e:
            logger.exception("Coder failed for task %d", task_id)
            async with factory() as db2:
                await finish_agent_run(db2, run_id, "failed", error=str(e))
                await transition_task(db2, task_id, "blocked")
                await append_log(db2, task_id, "error", str(e))


async def resume_coder_after_clarification(task_id: int, answer: str) -> None:
    """AUDIT_Q_BATCH12 §25/§29 gap-closure (2026-08-11) — extends the same
    real "clean stop, resume with a fresh run" pattern §27 already fixed for
    planner.py to coder.py, the other flagship autonomous-authoring agent:
    coder.py can now call request_clarification (app/agents/coder.py), and
    run_coder() surfaces that as a "[NEEDS_CLARIFICATION]"-prefixed error
    (same parseable-prefix convention as run_planner) instead of silently
    reporting a false zero-files-changed success.

    Called from api/approvals.py when a human approves a "clarification"
    action whose agent_name is "coder": folds the answer into the task's
    already-approved plan (read fresh from the DB, not mutated there) and
    re-invokes launch_coder() — the exact same call POST /{task_id}/approve
    makes, reusing create_worktree()'s existing idempotency (a still-valid
    worktree for this task_id is reused as-is, so any partial progress from
    before the pause is preserved, not discarded).
    """
    from app.db.models import can_transition
    from app.db.repository import get_task, resolve_task_repo_path

    factory = get_session_factory()
    async with factory() as db:
        task = await get_task(db, task_id)
        if task is None:
            logger.warning(
                "resume_coder_after_clarification: task %d not found", task_id
            )
            return
        if not can_transition(str(task.status), "coding"):
            logger.warning(
                "resume_coder_after_clarification: task %d in status %r "
                "cannot resume coding — leaving as-is",
                task_id,
                task.status,
            )
            return

        plan = str(task.plan or "")
        repo_path = resolve_task_repo_path(task)

        await transition_task(db, task_id, "coding")
        await append_log(
            db,
            task_id,
            "pipeline",
            f"Clarification answered — resuming coding. Answer: {answer[:500]}",
        )

    augmented_plan = (
        f"{plan}\n\n"
        "## Clarification\n"
        "You previously paused implementation to ask a human a question. "
        f"Here is the human's answer — use it, do not ask the same question "
        f"again:\n{answer}"
    )
    await launch_coder(task_id, augmented_plan, repo_path)
