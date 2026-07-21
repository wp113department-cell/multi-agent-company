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

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.fleet.approval_gate import PendingApprovalRecord, aget_pending, alist_pending

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
        raise HTTPException(status_code=404, detail=f"No approval request for thread {thread_id!r}")
    return _serialize(row)


async def _dispatch_decision(row: PendingApprovalRecord, approved: bool) -> None:
    """Route a decision to whichever flow actually owns this thread's
    interrupt() call. Today: only plan_review (pipeline/graph.py)."""
    if row.action == "plan_review" and row.task_id is not None:
        from app.api.agents import resume_planning_pipeline
        await resume_planning_pipeline(task_id=row.task_id, approved=approved)


@router.post("/{thread_id}/approve")
async def approve_approval(thread_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    row = await aget_pending(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No approval request for thread {thread_id!r}")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval {thread_id!r} is already {row.status!r}, not pending")

    background_tasks.add_task(_dispatch_decision, row, True)
    return {"approved": True, "threadId": thread_id}


@router.post("/{thread_id}/reject")
async def reject_approval(thread_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    row = await aget_pending(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No approval request for thread {thread_id!r}")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval {thread_id!r} is already {row.status!r}, not pending")

    background_tasks.add_task(_dispatch_decision, row, False)
    return {"rejected": True, "threadId": thread_id}
