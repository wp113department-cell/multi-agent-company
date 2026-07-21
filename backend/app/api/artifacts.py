"""Artifact API — GET /api/tasks/:id/artifacts, GET /api/artifacts/:id"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.artifacts.store import get_artifact, list_artifacts

router = APIRouter(prefix="/api", tags=["artifacts"])


@router.get("/tasks/{task_id}/artifacts")
async def list_task_artifacts(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """List all artifacts for a task (newest first)."""
    records = await list_artifacts(str(task_id), db=db)
    return [
        {
            "artifactId": r.artifact_id,
            "taskId": r.task_id,
            "artifactType": r.artifact_type,
            "version": r.version,
            "createdByAgent": r.created_by_agent,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.get("/artifacts/{artifact_id}")
async def get_artifact_content(artifact_id: str) -> PlainTextResponse:
    """Download artifact content by ID."""
    content = get_artifact(artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    return PlainTextResponse(content=content, media_type="text/plain")
