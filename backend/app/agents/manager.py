"""Manager Agent — orchestrates subtask dispatch through Dev → QA → Review pipeline.

Phase 5 upgrade adds epic-level supervision:
- run_epic_manager(): creates epic → runs planning pipeline → dispatches Dev/QA/Review
- Epic halt: ≥ MANAGER_MAX_EPIC_FAILURES blocked subtasks → emit epic.halted
- Batched approval package: all diffs, QA results, review findings assembled at epic completion
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT — Fleet OS capability declaration
# Note: manager is an async orchestrator, not a LangGraph node.
# It does not call run_agent_graph; fleet flags are N/A.
# ---------------------------------------------------------------------------
AGENT_CONTRACT: dict[str, Any] = {
    "name": "manager",
    "description": "Orchestrates the full Dev → QA → Review pipeline per subtask. Manages epic lifecycle, halt conditions, and assembles the approval package.",
    "allowed_tools": [],
    "input_types": ["task_id", "subtasks", "worktree_path", "plan", "repo_path", "epic_id"],
    "output_types": ["EpicApprovalPackage"],
    "side_effects": ["dispatches backend_dev/frontend_dev/qa/reviewer agents", "writes to DB", "publishes events"],
    "permissions": ["read_repo", "write_repo", "database_write", "event_bus_publish"],
    "risk_level": "high",
    "expected_verification": {},
    "dependencies": ["backend_dev", "frontend_dev", "qa", "reviewer"],
}

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import get_settings  # noqa: E402


@dataclass
class SubtaskResult:
    subtask_id: int
    subtask_type: str
    status: str  # completed | blocked
    files_changed: list[str]
    review_summary: str
    qa_summary: str
    diff: str


@dataclass
class EpicApprovalPackage:
    epic_id: str
    status: str  # ready_for_review | halted
    subtask_results: list[SubtaskResult]
    total_files_changed: list[str]
    all_diffs: str
    all_qa_summaries: list[str]
    all_review_findings: list[dict[str, Any]]
    cost_actual_usd: float
    halt_reason: str | None = None


async def run_manager(
    task_id: int,
    subtasks: list[dict[str, Any]],
    worktree_path: str,
    plan: str,
    repo_path: str | None = None,
    on_status: Any = None,
    epic_id: str | None = None,
) -> dict[str, Any]:
    """Orchestrate Dev → QA → Review per subtask.

    Returns {"status": "completed"|"blocked"|"halted", "results": [...], "blocked_count": N}
    """
    from app.agents.backend_dev import run_backend_dev
    from app.agents.frontend_dev import run_frontend_dev
    from app.agents.qa import run_qa
    from app.agents.reviewer import run_reviewer
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.repo_tools.worktree import get_diff

    settings = get_settings()
    max_retries = settings.max_retries
    max_epic_failures = settings.manager_max_epic_failures
    repo = repo_path or settings.target_repo_path

    results: list[dict[str, Any]] = []
    overall_status = "completed"
    blocked_count = 0

    for subtask in subtasks:
        subtask_id = int(subtask.get("id", 0))
        subtask_type = str(subtask.get("type", "backend"))
        subtask_title = str(subtask.get("title", ""))
        subtask_plan = str(subtask.get("description") or plan)

        logger.info("Manager dispatching subtask %d type=%s for task %d", subtask_id, subtask_type, task_id)

        # Day 12 Part 4 — hierarchy chain: fleet_manager selects an agent for
        # this capability and agent_bus publishes TaskCreated, alongside (not
        # replacing) the existing direct dispatch below. capability_registry/
        # fleet_manager/agent_bus already existed and were unit-tested in
        # isolation but nothing in the live task-flow ever called them —
        # additive instrumentation only, does not change which function runs.
        try:
            from app.fleet.fleet_events import publish, task_created
            from app.fleet.fleet_manager import get_fleet_manager

            required_capability = "frontend_development" if subtask_type == "frontend" else "backend_development"
            get_fleet_manager().select(required_capability=required_capability, verify_tool_availability=True)
            publish(task_created(task_id=str(task_id), title=subtask_title, agent_name="manager", trace_id=""))
        except Exception:
            pass

        await publish_event(GridironEvent(
            event_type="subtask.assigned",
            task_id=str(task_id),
            epic_id=epic_id,
            payload={"subtask_id": subtask_id, "type": subtask_type, "title": subtask_title},
            emitted_by="manager",
        ))

        if on_status:
            on_status(subtask_id, "dispatched")

        subtask_status = "blocked"
        files_changed: list[str] = []
        qa_errors: list[str] = []
        review_summary = ""
        qa_summary = ""
        review_findings: list[dict[str, Any]] = []
        subtask_diff = ""

        for attempt in range(max_retries):
            retry_context = ""
            if attempt > 0 and qa_errors:
                retry_context = f"\n\nPrevious QA/review errors (attempt {attempt}):\n" + "\n".join(qa_errors[:5])

            full_plan = subtask_plan + retry_context

            if subtask_type == "frontend":
                files_changed, dev_error = await asyncio.to_thread(
                    run_frontend_dev,
                    task_id=task_id,
                    subtask_id=subtask_id,
                    plan=full_plan,
                    worktree_path=worktree_path,
                    repo_path=repo,
                )
            else:
                files_changed, dev_error = await asyncio.to_thread(
                    run_backend_dev,
                    task_id=task_id,
                    subtask_id=subtask_id,
                    plan=full_plan,
                    worktree_path=worktree_path,
                    repo_path=repo,
                )

            if dev_error:
                qa_errors = [f"Dev agent error: {dev_error}"]
                logger.warning("Dev error attempt %d subtask %d: %s", attempt + 1, subtask_id, dev_error)
                if attempt == max_retries - 1:
                    break
                continue

            qa_result = await asyncio.to_thread(
                run_qa,
                task_id=task_id,
                subtask_id=subtask_id,
                files_changed=files_changed,
                worktree_path=worktree_path,
                repo_path=repo,
            )
            qa_summary = qa_result.summary

            if qa_result.status == "failed":
                qa_errors = qa_result.errors or [qa_result.summary]
                await publish_event(GridironEvent(
                    event_type="qa.failed",
                    task_id=str(task_id),
                    epic_id=epic_id,
                    payload={"subtask_id": subtask_id, "errors": qa_errors[:3]},
                    emitted_by="qa",
                ))
                logger.warning("QA failed attempt %d subtask %d", attempt + 1, subtask_id)
                if attempt == max_retries - 1:
                    break
                continue

            await publish_event(GridironEvent(
                event_type="qa.passed",
                task_id=str(task_id),
                epic_id=epic_id,
                payload={"subtask_id": subtask_id},
                emitted_by="qa",
            ))

            subtask_diff = get_diff(task_id, repo)
            review_result = await asyncio.to_thread(
                run_reviewer,
                task_id=task_id,
                subtask_id=subtask_id,
                diff=subtask_diff,
                plan=subtask_plan,
                repo_path=repo,
            )
            review_summary = review_result.summary
            review_findings = [
                {
                    "severity": f.severity,
                    "file": f.file,
                    "line": f.line,
                    "finding": f.finding,
                    "recommendation": f.recommendation,
                }
                for f in review_result.findings
            ]

            await publish_event(GridironEvent(
                event_type="review.completed",
                task_id=str(task_id),
                epic_id=epic_id,
                payload={
                    "subtask_id": subtask_id,
                    "verdict": review_result.verdict,
                    "blocking_count": review_result.blocking_count,
                },
                emitted_by="reviewer",
            ))

            if not review_result.has_blocking:
                subtask_status = "completed"
                break

            qa_errors = [
                f"Blocking review in {f.file}: {f.finding} → {f.recommendation}"
                for f in review_result.findings
                if f.severity == "blocking"
            ]
            logger.warning("Reviewer blocking findings attempt %d subtask %d", attempt + 1, subtask_id)
            if attempt == max_retries - 1:
                break

        results.append({
            "subtask_id": subtask_id,
            "type": subtask_type,
            "status": subtask_status,
            "files_changed": files_changed,
            "review_summary": review_summary,
            "qa_summary": qa_summary,
            "review_findings": review_findings,
            "diff": subtask_diff,
        })

        if subtask_status == "blocked":
            blocked_count += 1
            await publish_event(GridironEvent(
                event_type="task.blocked",
                task_id=str(task_id),
                epic_id=epic_id,
                payload={"subtask_id": subtask_id, "reason": "max retries exceeded"},
                emitted_by="manager",
            ))

            # Halt the epic early if too many subtasks failed
            if blocked_count >= max_epic_failures:
                overall_status = "halted"
                logger.error(
                    "Epic halted: %d/%d subtasks failed for task %d",
                    blocked_count, max_epic_failures, task_id,
                )
                # Day 12 — Failure Recovery Ladder: Abort. run_manager()'s own
                # retry loop (max_retries per subtask, already existed) is the
                # real Retry rung; this is what it escalates to once too many
                # subtasks exhaust their retries for the whole epic to continue.
                try:
                    from app.fleet.failure_ladder import abort
                    abort(str(task_id), f"epic halted — {blocked_count}/{max_epic_failures} subtasks failed")
                except Exception:
                    pass
                break

            # A single subtask exhausted its retries but the epic continues —
            # recoverable, not terminal: escalate (mark manager degraded) and
            # flag for human review rather than aborting the whole task.
            try:
                from app.fleet.failure_ladder import escalate, request_human_review
                escalate("manager", f"subtask {subtask_id} exhausted retries", trace_id="")
                request_human_review(str(task_id), "manager", f"subtask {subtask_id} blocked after retries", trace_id="")
            except Exception:
                pass

            overall_status = "blocked"
        else:
            if on_status:
                on_status(subtask_id, "completed")

    return {"status": overall_status, "results": results, "blocked_count": blocked_count}


async def run_epic_manager(
    epic_id: str,
    goal: str,
    db: AsyncSession,
    repo_path: str | None = None,
) -> EpicApprovalPackage:
    """Top-level epic orchestrator.

    Flow:
    1. Cost estimate → if over threshold → mark epic 'pending_cost_approval' and return early
    2. Mark epic 'planning' → run PM→Arch→Decomp planning pipeline
    3. Mark epic 'coding' → run per-subtask Dev→QA→Review pipeline
    4. If ≥ MANAGER_MAX_EPIC_FAILURES blocked → emit epic.halted, mark epic 'halted'
    5. On all complete → assemble batched approval package → emit epic.ready_for_review
    """
    from sqlalchemy import select, update as sa_update
    from app.db.models import Epic, DevTask
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent
    from app.pipeline.cost_controller import estimate_epic_cost
    from app.pipeline.graph import run_planning_pipeline
    from app.repo_tools.worktree import create_worktree

    settings = get_settings()
    repo = repo_path or settings.target_repo_path

    # Load the epic
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one()  # noqa: F841

    # --- Step 1: Rough cost estimate (subtask count unknown yet; use 5 as baseline) ---
    estimate = await estimate_epic_cost(subtask_count=5, db=db)
    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_estimate=Decimal(str(estimate.estimated_cost_usd)))
    )
    await db.commit()

    if estimate.requires_approval:
        await db.execute(
            sa_update(Epic).where(Epic.epic_id == epic_id).values(status="pending_cost_approval")
        )
        await db.commit()
        await publish_event(GridironEvent(
            event_type="epic.pending_cost_approval",
            epic_id=epic_id,
            payload={
                "estimated_cost_usd": estimate.estimated_cost_usd,
                "threshold": settings.cost_approval_threshold,
            },
            emitted_by="manager",
        ))
        return EpicApprovalPackage(
            epic_id=epic_id,
            status="pending_cost_approval",
            subtask_results=[],
            total_files_changed=[],
            all_diffs="",
            all_qa_summaries=[],
            all_review_findings=[],
            cost_actual_usd=0.0,
            halt_reason="Cost estimate exceeds approval threshold",
        )

    # --- Step 2: Planning pipeline ---
    await db.execute(sa_update(Epic).where(Epic.epic_id == epic_id).values(status="planning"))
    await db.commit()
    await publish_event(GridironEvent(
        event_type="epic.planning_started",
        epic_id=epic_id,
        payload={"goal": goal[:200]},
        emitted_by="manager",
    ))

    # Create a DevTask for this epic
    task = DevTask(
        title=goal[:500],
        description=goal,
        status="planning",
        epic_id=epic_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    task_id: int = task.id
    await db.commit()

    # Run the planning pipeline (LangGraph PM→Arch→Decomp — already async)
    # Pass db so planning pipeline can pre-fetch memory context for Architect Agent
    pipeline_result = await run_planning_pipeline(
        task_id=task_id,
        title=goal[:500],
        description=goal,
        repo_path=repo,
        db=db,
    )

    subtasks: list[dict[str, Any]] = pipeline_result.get("subtasks") or []
    plan_text: str = str(pipeline_result.get("task_description") or goal)

    if not subtasks:
        logger.warning("Planning pipeline returned no subtasks for epic %s", epic_id)
        subtasks = [{"id": 1, "type": "backend", "title": goal, "description": goal}]

    # Refine cost estimate now that we know subtask count
    refined_estimate = await estimate_epic_cost(subtask_count=len(subtasks), db=db)
    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_estimate=Decimal(str(refined_estimate.estimated_cost_usd)))
    )
    await db.commit()

    # --- Step 3: Coding pipeline ---
    await db.execute(sa_update(Epic).where(Epic.epic_id == epic_id).values(status="coding"))
    await db.commit()

    worktree_path = str(create_worktree(task_id, repo))

    manager_result = await run_manager(
        task_id=task_id,
        subtasks=subtasks,
        worktree_path=worktree_path,
        plan=plan_text,
        repo_path=repo,
        epic_id=epic_id,
    )

    final_status = manager_result["status"]
    results: list[dict[str, Any]] = manager_result["results"]
    blocked_count: int = manager_result["blocked_count"]

    # Collect tokens from agent_runs for cost_actual
    from sqlalchemy import func as sqlfunc
    token_result = await db.execute(  # noqa: F841
        select(sqlfunc.sum(DevTask.id))  # placeholder — real token sum via agent_runs
    )
    # Approximate: use refined estimate as fallback
    cost_actual = refined_estimate.estimated_cost_usd

    await db.execute(
        sa_update(Epic)
        .where(Epic.epic_id == epic_id)
        .values(cost_actual=Decimal(str(cost_actual)))
    )

    # --- Step 4/5: Assemble approval package or halt ---
    subtask_result_objs = [
        SubtaskResult(
            subtask_id=r["subtask_id"],
            subtask_type=r["type"],
            status=r["status"],
            files_changed=r.get("files_changed", []),
            review_summary=r.get("review_summary", ""),
            qa_summary=r.get("qa_summary", ""),
            diff=r.get("diff", ""),
        )
        for r in results
    ]

    all_files: list[str] = []
    for r in subtask_result_objs:
        all_files.extend(r.files_changed)

    all_diffs = "\n\n".join(f"# Subtask {r.subtask_id}\n{r.diff}" for r in subtask_result_objs if r.diff)
    all_qa = [r.qa_summary for r in subtask_result_objs if r.qa_summary]
    all_findings: list[dict[str, Any]] = []
    for raw in results:
        all_findings.extend(raw.get("review_findings", []))

    from app.memory.store import embed_task_outcome

    if final_status == "halted":
        halt_reason = f"{blocked_count} subtasks exhausted all retries"
        await db.execute(
            sa_update(Epic)
            .where(Epic.epic_id == epic_id)
            .values(status="halted", halt_reason=halt_reason)
        )
        await db.commit()
        await publish_event(GridironEvent(
            event_type="epic.halted",
            epic_id=epic_id,
            payload={"blocked_count": blocked_count, "halt_reason": halt_reason},
            emitted_by="manager",
        ))
        # Store outcome in engineering memory
        await embed_task_outcome(
            task_id=str(task_id),
            description=goal,
            summary=halt_reason,
            outcome="blocked",
            files_changed=list(set(all_files)),
            db=db,
            epic_id=epic_id,
        )
        return EpicApprovalPackage(
            epic_id=epic_id,
            status="halted",
            subtask_results=subtask_result_objs,
            total_files_changed=list(set(all_files)),
            all_diffs=all_diffs,
            all_qa_summaries=all_qa,
            all_review_findings=all_findings,
            cost_actual_usd=cost_actual,
            halt_reason=halt_reason,
        )

    await db.execute(sa_update(Epic).where(Epic.epic_id == epic_id).values(status="ready_for_review"))
    await db.commit()
    await publish_event(GridironEvent(
        event_type="epic.ready_for_review",
        epic_id=epic_id,
        payload={
            "subtask_count": len(subtasks),
            "files_changed": len(all_files),
            "cost_actual_usd": cost_actual,
        },
        emitted_by="manager",
    ))

    # Store outcome in engineering memory
    summary = "; ".join(all_qa[:3]) or f"Epic completed with {len(subtasks)} subtasks"
    await embed_task_outcome(
        task_id=str(task_id),
        description=goal,
        summary=summary,
        outcome="completed",
        files_changed=list(set(all_files)),
        db=db,
        epic_id=epic_id,
    )

    return EpicApprovalPackage(
        epic_id=epic_id,
        status="ready_for_review",
        subtask_results=subtask_result_objs,
        total_files_changed=list(set(all_files)),
        all_diffs=all_diffs,
        all_qa_summaries=all_qa,
        all_review_findings=all_findings,
        cost_actual_usd=cost_actual,
    )


# ---------------------------------------------------------------------------
# Capability registry registration
# ---------------------------------------------------------------------------

def _register() -> None:
    try:
        from app.fleet.capability_registry import AgentCapability, register
        from app.fleet.agent_registry import get_agent_registry
        register(AgentCapability(
            name=AGENT_CONTRACT["name"],
            description=AGENT_CONTRACT["description"],
            tools=AGENT_CONTRACT["allowed_tools"],
            input_types=AGENT_CONTRACT["input_types"],
            output_types=AGENT_CONTRACT["output_types"],
            capabilities=["task_orchestration", "epic_management", "pipeline_coordination"],
            risk_level=AGENT_CONTRACT["risk_level"],
            dependencies=AGENT_CONTRACT["dependencies"],
        ))
        get_agent_registry().register(AGENT_CONTRACT["name"])
    except Exception as exc:
        logger.debug("Fleet registry not available: %s", exc)


_register()
