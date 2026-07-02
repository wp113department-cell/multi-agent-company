"""Manager Agent — orchestrates subtask dispatch through Dev → QA → Review pipeline."""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_manager(
    task_id: int,
    subtasks: list[dict[str, Any]],
    worktree_path: str,
    plan: str,
    repo_path: str | None = None,
    on_status: Any = None,
) -> dict[str, Any]:
    """
    Orchestrate the Dev → QA → Review pipeline for each subtask.

    Per doc-06: Manager does routing/tracking — no direct code writes.
    Each subtask goes through: dispatch → QA → Review.
    qa.failed or blocking review → retry (up to max_retries).
    After max_retries exhausted → task.blocked.

    Returns {"status": "completed"|"blocked", "results": [...per subtask...]}
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
    repo = repo_path or settings.target_repo_path

    results: list[dict[str, Any]] = []
    overall_status = "completed"

    for subtask in subtasks:
        subtask_id = int(subtask.get("id", 0))
        subtask_type = str(subtask.get("type", "backend"))
        subtask_title = str(subtask.get("title", ""))
        subtask_plan = str(subtask.get("description") or plan)

        logger.info("Manager dispatching subtask %d type=%s for task %d", subtask_id, subtask_type, task_id)

        await publish_event(GridironEvent(
            event_type="subtask.assigned",
            task_id=str(task_id),
            payload={"subtask_id": subtask_id, "type": subtask_type, "title": subtask_title},
            emitted_by="manager",
        ))

        if on_status:
            on_status(subtask_id, "dispatched")

        subtask_status = "blocked"
        files_changed: list[str] = []
        qa_errors: list[str] = []
        review_summary = ""

        for attempt in range(max_retries):
            retry_context = ""
            if attempt > 0 and qa_errors:
                retry_context = f"\n\nPrevious QA/review errors (attempt {attempt}):\n" + "\n".join(qa_errors[:5])

            full_plan = subtask_plan + retry_context

            # Dispatch to appropriate developer agent
            if subtask_type == "frontend":
                files_changed, dev_error = run_frontend_dev(
                    task_id=task_id,
                    subtask_id=subtask_id,
                    plan=full_plan,
                    worktree_path=worktree_path,
                    repo_path=repo,
                )
            else:
                files_changed, dev_error = run_backend_dev(
                    task_id=task_id,
                    subtask_id=subtask_id,
                    plan=full_plan,
                    worktree_path=worktree_path,
                    repo_path=repo,
                )

            if dev_error:
                qa_errors = [f"Dev agent error: {dev_error}"]
                logger.warning("Dev agent error on attempt %d for subtask %d: %s", attempt + 1, subtask_id, dev_error)
                if attempt == max_retries - 1:
                    break
                continue

            # QA phase
            qa_result = run_qa(
                task_id=task_id,
                subtask_id=subtask_id,
                files_changed=files_changed,
                worktree_path=worktree_path,
                repo_path=repo,
            )

            if qa_result.status == "failed":
                qa_errors = qa_result.errors or [qa_result.summary]
                await publish_event(GridironEvent(
                    event_type="qa.failed",
                    task_id=str(task_id),
                    payload={"subtask_id": subtask_id, "errors": qa_errors[:3]},
                    emitted_by="qa",
                ))
                logger.warning("QA failed on attempt %d for subtask %d", attempt + 1, subtask_id)
                if attempt == max_retries - 1:
                    break
                continue

            await publish_event(GridironEvent(
                event_type="qa.passed",
                task_id=str(task_id),
                payload={"subtask_id": subtask_id},
                emitted_by="qa",
            ))

            # Review phase
            diff = get_diff(task_id, repo)
            review_result = run_reviewer(
                task_id=task_id,
                subtask_id=subtask_id,
                diff=diff,
                plan=subtask_plan,
                repo_path=repo,
            )

            review_summary = review_result.summary
            await publish_event(GridironEvent(
                event_type="review.completed",
                task_id=str(task_id),
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

            # Blocking findings — feed back to dev agent
            qa_errors = [
                f"Blocking review finding in {f.file}: {f.finding} → {f.recommendation}"
                for f in review_result.findings
                if f.severity == "blocking"
            ]
            logger.warning("Reviewer blocking findings on attempt %d for subtask %d", attempt + 1, subtask_id)
            if attempt == max_retries - 1:
                break

        results.append({
            "subtask_id": subtask_id,
            "type": subtask_type,
            "status": subtask_status,
            "files_changed": files_changed,
            "review_summary": review_summary,
        })

        if subtask_status == "blocked":
            overall_status = "blocked"
            await publish_event(GridironEvent(
                event_type="task.blocked",
                task_id=str(task_id),
                payload={"subtask_id": subtask_id, "reason": "max retries exceeded"},
                emitted_by="manager",
            ))
            # Stop processing further subtasks when one blocks
            break

        if on_status:
            on_status(subtask_id, "completed")

    return {"status": overall_status, "results": results}
