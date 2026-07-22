"""Human Approval UI — Day 13.

Generic list/get/approve/reject over app/fleet/approval_gate.py's
pending_approvals index. Today's only real registrant is
app/pipeline/graph.py's human_review_node (via launch_planning_pipeline/
resume_planning_pipeline, already proven correct in Day 12's smoke test) —
approve/reject here call the SAME resume_planning_pipeline() the existing
/pipeline/approve endpoint already calls, reused rather than duplicated.
Day 14's git-push approval gate registers into this same table/API.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.fleet.approval_gate import PendingApprovalRecord, aget_pending, alist_pending

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _serialize(row: PendingApprovalRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "threadId": row.thread_id,
        "taskId": row.task_id,
        "agentName": row.agent_name,
        "action": row.action,
        "details": row.details,
        "status": row.status,
        "createdAt": row.created_at,
        "decidedAt": row.decided_at,
        "decidedBy": row.decided_by,
    }


@router.get("/pending")
async def list_pending_approvals() -> dict[str, Any]:
    rows = await alist_pending()
    return {"approvals": [_serialize(r) for r in rows]}


@router.get("/{thread_id}")
async def get_approval(thread_id: str) -> dict[str, Any]:
    row = await aget_pending(thread_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No approval request for thread {thread_id!r}"
        )
    return _serialize(row)


async def _dispatch_decision(row: PendingApprovalRecord, approved: bool) -> None:
    """Route a decision to whichever flow actually owns this thread's
    interrupt() call. plan_review -> pipeline/graph.py (Day 13). git_push ->
    the actual push+PR creation (Day 14)."""
    if row.action == "plan_review" and row.task_id is not None:
        from app.api.agents import resume_planning_pipeline

        await resume_planning_pipeline(task_id=row.task_id, approved=approved)
    elif row.action == "git_push" and row.task_id is not None:
        await dispatch_git_push_decision(row.task_id, approved)


async def dispatch_git_push_decision(task_id: int, approved: bool) -> None:
    """Day 14 — Git Push Workflow. On reject: mark pr_status="failed" (no
    push attempted). On approve: push the already-committed agent/task-{id}
    branch and create a PR. Also used directly by POST /api/tasks/{id}/push
    for a manual retry, bypassing the approval gate since approval already
    happened once for that path."""
    from app.config import get_settings
    from app.db.repository import get_setting, get_task, update_task_pr
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        task = await get_task(db, task_id)
        if task is None:
            logger.warning("git_push dispatch: task %d not found", task_id)
            return

        if not approved:
            await update_task_pr(db, task_id, None, "failed")
            return

        if task.repo is None or not task.repo.github_url:
            logger.warning(
                "git_push dispatch: task %d has no GitHub-linked repo", task_id
            )
            await update_task_pr(db, task_id, None, "failed")
            return

        token = (await get_setting(db, "github_token")) or get_settings().github_token

        from app.tools.git_push_tool import push_and_create_pr

        result = await push_and_create_pr(
            task_id=task_id,
            task_title=task.title,
            task_description=task.description,
            repo_path=task.repo.local_path,
            github_url=task.repo.github_url,
            token=token,
        )
        await update_task_pr(
            db, task_id, result.pr_url, "pushed" if result.pushed else "failed"
        )


@router.post("/{thread_id}/approve")
async def approve_approval(
    thread_id: str, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    row = await aget_pending(thread_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No approval request for thread {thread_id!r}"
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval {thread_id!r} is already {row.status!r}, not pending",
        )

    background_tasks.add_task(_dispatch_decision, row, True)
    return {"approved": True, "threadId": thread_id}


@router.post("/{thread_id}/reject")
async def reject_approval(
    thread_id: str, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    row = await aget_pending(thread_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No approval request for thread {thread_id!r}"
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval {thread_id!r} is already {row.status!r}, not pending",
        )

    background_tasks.add_task(_dispatch_decision, row, False)
    return {"rejected": True, "threadId": thread_id}
