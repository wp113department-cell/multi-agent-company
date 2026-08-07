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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.fleet.approval_gate import (
    PendingApprovalRecord,
    aget_pending,
    alist_pending,
    arecord_decision,
)
from app.middleware.rbac import require_approver, require_authenticated

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
async def list_pending_approvals(
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    rows = await alist_pending()
    return {"approvals": [_serialize(r) for r in rows]}


@router.get("/{thread_id}")
async def get_approval(
    thread_id: str, _actor: str = Depends(require_authenticated)
) -> dict[str, Any]:
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
        from app.db.repository import get_task, resolve_task_repo_path
        from app.db.session import get_session_factory

        # Gap-closure Day 4 (root cause 1c, answers.md Q51/Q94/Q95): this was
        # the one real remaining gap in an otherwise-consistent pattern —
        # resume_planning_pipeline was always called with repo_path=None
        # here, so it (and launch_manager downstream of it) fell back to
        # whichever repo happens to be globally active at the arbitrarily
        # later moment a human clicks Approve, not the repo the task was
        # actually created against. See resolve_task_repo_path's docstring.
        repo_path: str | None = None
        factory = get_session_factory()
        async with factory() as db:
            task = await get_task(db, row.task_id)
            if task is not None:
                repo_path = resolve_task_repo_path(task)

        await resume_planning_pipeline(
            task_id=row.task_id, approved=approved, repo_path=repo_path
        )
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

        # Gap-closure (Audit 04 fix, ORCH-04-002): a successful push is a
        # real "this task is done" signal — without this, DevTask.status
        # never reaches a terminal state even after the PR is live. Best
        # effort / non-fatal: task.status may not be exactly
        # "ready_for_review" in some edge case (e.g. a manual retry via
        # POST /{task_id}/push after the task moved on some other way), in
        # which case can_transition() rejects it and transition_task()
        # raises — swallowed here since the push itself already succeeded
        # and that is the primary outcome this function is responsible for.
        if result.pushed:
            try:
                from app.db.repository import transition_task

                await transition_task(db, task_id, "completed")
            except Exception:
                logger.debug(
                    "Could not auto-complete task %d after push (non-fatal)",
                    task_id,
                    exc_info=True,
                )

            # Gap-closure (Audit 04 fix, ORCH-04-012): worktree no longer
            # needed once the branch is pushed and the task is complete.
            try:
                from app.repo_tools.worktree import remove_worktree

                remove_worktree(task_id, task.repo.local_path)
            except Exception:
                logger.debug(
                    "Could not remove worktree for task %d after push (non-fatal)",
                    task_id,
                    exc_info=True,
                )


async def _decide_or_409(thread_id: str, approved: bool) -> PendingApprovalRecord:
    """Gap-closure (Audit 04 fix, ORCH-04-007): the old approve/reject
    endpoints read PendingApproval.status once, then scheduled the actual
    decision-recording (arecord_decision, inside resume_planning_pipeline)
    as a BackgroundTask that only runs AFTER the HTTP response is returned —
    leaving a window where the row still reads "pending" and a second
    concurrent call would also pass the check and dispatch a second decision.
    Flipping the status HERE, synchronously, before returning, closes that
    window: arecord_decision()'s own UPDATE ... WHERE status='pending' is
    the actual source of truth for whether THIS request won the race, not a
    separate read-then-check. (Also fixes a second, separate gap: the
    git_push action path never called arecord_decision() at all before this
    change, so its PendingApproval rows never left "pending" even after
    being decided.)
    """
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

    decided = await arecord_decision(
        thread_id=thread_id, approved=approved, decided_by="user"
    )
    if decided is None:
        raise HTTPException(
            status_code=409,
            detail=f"Approval {thread_id!r} was already decided",
        )
    return row


@router.post("/{thread_id}/approve")
async def approve_approval(
    thread_id: str,
    background_tasks: BackgroundTasks,
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    row = await _decide_or_409(thread_id, True)
    background_tasks.add_task(_dispatch_decision, row, True)
    return {"approved": True, "threadId": thread_id}


@router.post("/{thread_id}/reject")
async def reject_approval(
    thread_id: str,
    background_tasks: BackgroundTasks,
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    row = await _decide_or_409(thread_id, False)
    background_tasks.add_task(_dispatch_decision, row, False)
    return {"rejected": True, "threadId": thread_id}
