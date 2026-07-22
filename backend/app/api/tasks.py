from typing import Any
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.repository import (
    TransitionError,
    append_log,
    create_task,
    create_task_image,
    delete_task_image,
    get_task,
    get_task_image,
    get_pipeline_state,
    list_logs,
    list_subtasks,
    list_task_images,
    list_tasks,
    transition_task,
    get_or_create_pipeline_state,
)
from app.config import get_settings

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    repo_id: int | None = None


class TransitionRequest(BaseModel):
    status: str


class LogRequest(BaseModel):
    category: str
    message: str
    extra_data: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    reason: str | None = None


class RunRequest(BaseModel):
    mode: str | None = (
        None  # "full" | "simple" — overrides PIPELINE_MODE env for this request
    )


def _log_to_dict(log: Any) -> dict[str, Any]:
    return {
        "logId": log.id,
        "taskId": log.task_id,
        "category": log.category,
        "message": log.message,
        "extraData": log.extra_data,
        "createdAt": log.created_at.isoformat() if log.created_at else None,
    }


def _task_to_dict(task: Any, logs: list[Any] | None = None) -> dict[str, Any]:
    repo = getattr(task, "repo", None)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "plan": task.plan,
        "diff": task.diff,
        "filesTouched": task.files_touched or [],
        "project": None,
        "priority": "medium",
        "assignedAgent": None,
        "finalSummary": None,
        "repoId": task.repo_id,
        "repoName": repo.name if repo else None,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        "logs": [_log_to_dict(lg) for lg in (logs or [])],
    }


@router.post("", status_code=201)
async def create(
    body: CreateTaskRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    task = await create_task(db, body.title, body.description, repo_id=body.repo_id)
    return _task_to_dict(task)


@router.get("")
async def list_all(
    status: str | None = Query(None),
    repo_id: int | None = Query(None),
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks, next_cursor = await list_tasks(
        db, status=status, repo_id=repo_id, cursor=cursor, limit=limit
    )
    return {"tasks": [_task_to_dict(t) for t in tasks], "nextCursor": next_cursor}


@router.get("/{task_id}")
async def get_one(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = await list_logs(db, task_id)
    return _task_to_dict(task, logs=logs)


@router.patch("/{task_id}")
async def patch_status(
    task_id: int, body: TransitionRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        task = await transition_task(db, task_id, body.status)
    except TransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_to_dict(task)


@router.post("/{task_id}/logs", status_code=201)
async def add_log(
    task_id: int, body: LogRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    log = await append_log(db, task_id, body.category, body.message, body.extra_data)
    return _log_to_dict(log)


@router.get("/{task_id}/logs")
async def get_logs(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    logs = await list_logs(db, task_id)
    return {"logs": [_log_to_dict(lg) for lg in logs]}


@router.post("/{task_id}/run")
async def run_task(
    task_id: int,
    body: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger planning pipeline or simple planner for a pending/blocked/rejected task."""
    from app.api.agents import launch_planning_pipeline, launch_planner
    from app.db.models import Repo
    from sqlalchemy import select

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("pending", "rejected", "blocked"):
        raise HTTPException(
            status_code=400, detail=f"Cannot start planning from status {task.status!r}"
        )

    # Resolve which repo path agents should use for this task
    repo_path: str | None = None
    if task.repo_id:
        result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
        repo_obj = result.scalar_one_or_none()
        if repo_obj and repo_obj.status == "ready":
            repo_path = repo_obj.local_path

    await transition_task(db, task_id, "planning")
    await append_log(db, task_id, "pipeline", "Planning triggered")

    settings = get_settings()
    mode = body.mode or settings.pipeline_mode

    if mode == "full":
        background_tasks.add_task(
            launch_planning_pipeline,
            task_id,
            str(task.title),
            str(task.description),
            repo_path,
        )
    else:
        background_tasks.add_task(
            launch_planner, task_id, str(task.title), str(task.description), repo_path
        )

    return {"triggered": True, "mode": mode}


@router.post("/{task_id}/restart")
async def restart_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reset a failed/blocked/error task back to pending and re-trigger the planning pipeline."""
    from app.api.agents import launch_planning_pipeline
    from app.db.models import Repo, DevTask
    from sqlalchemy import select, update

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Force-reset to pending regardless of current status
    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(status="pending")
    )
    await db.commit()

    # Re-fetch to get fresh state for the pipeline
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found after reset")

    repo_path: str | None = None
    if task.repo_id:
        result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
        repo_obj = result.scalar_one_or_none()
        if repo_obj and repo_obj.status == "ready":
            repo_path = repo_obj.local_path

    await transition_task(db, task_id, "planning")
    await append_log(
        db, task_id, "pipeline", "Task restarted — planning pipeline re-triggered"
    )

    background_tasks.add_task(
        launch_planning_pipeline,
        task_id,
        str(task.title),
        str(task.description),
        repo_path,
    )

    return {"restarted": True, "taskId": task_id}


@router.post("/{task_id}/approve")
async def approve_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve diff after coding — start coder or mark completed."""
    from app.api.agents import launch_coder
    from app.db.models import Repo
    from sqlalchemy import select

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "ready_for_review":
        raise HTTPException(
            status_code=400,
            detail=f"Task must be ready_for_review, got {task.status!r}",
        )

    # Gap-closure (Days 11-15 audit, 2026-07-22): this endpoint never resolved
    # the task's assigned repo (task.repo_id), unlike /run, /restart, and
    # /pipeline/approve — launch_coder silently fell back to the single
    # global active repo, ignoring per-task repo selection entirely.
    repo_path: str | None = None
    if task.repo_id:
        result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
        repo_obj = result.scalar_one_or_none()
        if repo_obj and repo_obj.status == "ready":
            repo_path = repo_obj.local_path

    plan = str(task.plan or "")
    task = await transition_task(db, task_id, "coding")
    await append_log(db, task_id, "approval", "Plan approved — coding agent starting")

    background_tasks.add_task(launch_coder, task_id, plan, repo_path)
    return {"approved": True, "task": _task_to_dict(task)}


@router.post("/{task_id}/reject")
async def reject_task(
    task_id: int, body: RejectRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = await transition_task(db, task_id, "rejected")
    msg = f"Task rejected. Reason: {body.reason}" if body.reason else "Task rejected"
    await append_log(db, task_id, "rejection", msg)
    return {"rejected": True, "task": _task_to_dict(task)}


@router.post("/{task_id}/pipeline/approve")
async def pipeline_approve(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Resume the LangGraph pipeline with approval → launch coder."""
    from app.api.agents import resume_planning_pipeline
    from app.db.models import Repo
    from sqlalchemy import select

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ps = await get_or_create_pipeline_state(db, task_id)
    if ps.stage != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline is not awaiting approval (stage={ps.stage!r})",
        )

    repo_path: str | None = None
    if task.repo_id:
        result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
        repo_obj = result.scalar_one_or_none()
        if repo_obj and repo_obj.status == "ready":
            repo_path = repo_obj.local_path

    await append_log(db, task_id, "approval", "Plan approved — resuming pipeline")
    background_tasks.add_task(resume_planning_pipeline, task_id, True, repo_path)
    return {"approved": True}


@router.post("/{task_id}/pipeline/reject")
async def pipeline_reject(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Resume the LangGraph pipeline with rejection."""
    from app.api.agents import resume_planning_pipeline

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ps = await get_or_create_pipeline_state(db, task_id)
    if ps.stage != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline is not awaiting approval (stage={ps.stage!r})",
        )

    await append_log(db, task_id, "rejection", "Plan rejected — pipeline cancelled")
    background_tasks.add_task(resume_planning_pipeline, task_id, False)
    return {"rejected": True}


@router.get("/{task_id}/subtasks")
async def get_subtasks(
    task_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    subtasks = await list_subtasks(db, task_id)
    return {
        "subtasks": [
            {
                "id": s.id,
                "type": s.type,
                "title": s.title,
                "description": s.description,
                "filesToEdit": s.files_to_edit,
                "dependsOn": s.depends_on,
                "status": s.status,
            }
            for s in subtasks
        ]
    }


@router.get("/{task_id}/pipeline")
async def get_pipeline(
    task_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    ps = await get_pipeline_state(db, task_id)
    if ps is None:
        raise HTTPException(status_code=404, detail="No pipeline state for this task")
    return {
        "taskId": task_id,
        "stage": ps.stage,
        "pmBrief": ps.pm_brief,
        "architectPlan": ps.architect_plan,
        "subtasks": ps.subtasks_json,
        "approved": ps.approved,
    }


@router.get("/{task_id}/diff")
async def get_diff(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"diff": task.diff, "filesTouched": task.files_touched or []}


@router.get("/{task_id}/pr")
async def get_pr(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Day 14 — Git Push Workflow."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "branchName": task.branch_name,
        "prUrl": task.pr_url,
        "prStatus": task.pr_status,
    }


@router.post("/{task_id}/push")
async def push_task(
    task_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Day 14 — Git Push Workflow. Manual retry: re-runs push+PR creation
    directly, bypassing the approval gate since approval already happened
    once for a previously-approved push that failed transiently."""
    from app.api.approvals import dispatch_git_push_decision

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.branch_name is None:
        raise HTTPException(
            status_code=400,
            detail="Task has no branch to push — has coding completed yet?",
        )

    background_tasks.add_task(dispatch_git_push_decision, task_id, True)
    return {"triggered": True, "taskId": task_id}


# ---------------------------------------------------------------------------
# PDF attachment extraction — POST /api/tasks/extract-pdfs
# Up to 5 PDF files; returns extracted text from each.
# ---------------------------------------------------------------------------

MAX_PDF_FILES = 5
MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB per file


@router.post("/extract-pdfs")
async def extract_pdfs(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Extract text from up to 5 PDF files. Returns extracted text for each file.

    The caller can then append this text to the task description before submitting.
    """
    if len(files) > MAX_PDF_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_PDF_FILES} PDF files allowed. Got {len(files)}.",
        )

    results = []
    for upload in files:
        fname = upload.filename or "file.pdf"
        if not fname.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"'{fname}' is not a PDF file.")

        raw = await upload.read()
        if len(raw) > MAX_PDF_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' exceeds 20 MB limit ({len(raw) // 1024 // 1024} MB).",
            )

        text = _extract_pdf_text(raw, fname)
        results.append({"filename": fname, "text": text, "chars": len(text)})

    return {"ok": True, "files": results}


def _extract_pdf_text(raw: bytes, fname: str) -> str:
    """Extract plain text from PDF bytes using pdfplumber."""
    try:
        import io
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = []
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"[Page {i + 1}]\n{page_text}")
            return "\n\n".join(pages)
    except Exception as exc:
        return f"[Could not extract text from '{fname}': {exc}]"


# ---------------------------------------------------------------------------
# Day 16 — Image Input Pipeline. Reference images (e.g. a website design
# screenshot), injected as Anthropic ImageBlockParam content blocks into
# pm/architect/frontend_dev/reviewer's initial calls. Limits per REPO-FIRST
# research (roo-code's DEFAULT_MAX_IMAGE_FILE_SIZE_MB/DEFAULT_MAX_TOTAL_IMAGE_SIZE_MB/
# MAX_IMAGES_PER_MESSAGE) — same shape as the extract-pdfs section above.
# Format allowlist matches the Anthropic Messages API's actual supported
# vision media types exactly (not a superset like roo-code's local-file list,
# which also covers formats the API itself would reject).
# ---------------------------------------------------------------------------

MAX_IMAGES_PER_TASK = 20
MAX_IMAGE_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB per file
MAX_TOTAL_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB total per task

_IMAGE_EXT_TO_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _image_media_type(filename: str) -> str | None:
    import os

    ext = os.path.splitext(filename.lower())[1]
    return _IMAGE_EXT_TO_MEDIA_TYPE.get(ext)


@router.post("/{task_id}/images")
async def upload_task_images(
    task_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload reference images for a task (e.g. a website design screenshot).
    Multipart, same shape as /extract-pdfs. Per-file 5MB limit, 20MB total
    across the task's existing + new images, max 20 images per task."""
    import base64

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    existing = await list_task_images(db, task_id)
    if len(existing) + len(files) > MAX_IMAGES_PER_TASK:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_IMAGES_PER_TASK} images per task "
            f"(already have {len(existing)}, uploading {len(files)}).",
        )

    total_bytes = sum(len(base64.b64decode(img.base64_data)) for img in existing)
    next_order = max((img.display_order for img in existing), default=-1) + 1

    created = []
    for upload in files:
        fname = upload.filename or "image"
        media_type = _image_media_type(fname)
        if media_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' is not a supported image format "
                "(png, jpg, jpeg, gif, webp).",
            )

        raw = await upload.read()
        if len(raw) > MAX_IMAGE_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' exceeds 5 MB limit ({len(raw) // 1024 // 1024} MB).",
            )
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Total image size exceeds 20 MB limit at '{fname}'.",
            )

        b64 = base64.b64encode(raw).decode("ascii")
        image = await create_task_image(db, task_id, b64, media_type, next_order)
        next_order += 1
        created.append(
            {"id": image.id, "mimeType": image.mime_type, "order": image.display_order}
        )

    return {"created": created}


@router.get("/{task_id}/images")
async def get_task_images(
    task_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Metadata only (id/mimeType/order) — never the base64 blob, to keep this
    poll-friendly. Use GET /{task_id}/images/{image_id} for the raw bytes."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    images = await list_task_images(db, task_id)
    return {
        "images": [
            {
                "id": img.id,
                "mimeType": img.mime_type,
                "order": img.display_order,
                "createdAt": img.created_at.isoformat(),
            }
            for img in images
        ]
    }


@router.get("/{task_id}/images/{image_id}")
async def get_task_image_bytes(
    task_id: int, image_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    """Raw image bytes with the correct Content-Type — for <img src=...>."""
    import base64

    image = await get_task_image(db, image_id)
    if not image or image.task_id != task_id:
        raise HTTPException(status_code=404, detail="Image not found")

    return Response(
        content=base64.b64decode(image.base64_data), media_type=image.mime_type
    )


@router.delete("/{task_id}/images/{image_id}")
async def remove_task_image(
    task_id: int, image_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    image = await get_task_image(db, image_id)
    if not image or image.task_id != task_id:
        raise HTTPException(status_code=404, detail="Image not found")

    deleted = await delete_task_image(db, image_id)
    return {"deleted": deleted}
