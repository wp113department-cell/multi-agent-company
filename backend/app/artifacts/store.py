"""
Artifact Store — local disk adapter with DB metadata.

Every pipeline step writes versioned artifacts:
  plan, diff, test_results, review_findings

Storage path: {ARTIFACTS_DIR}/{artifact_id}
Adapter pattern: swap local disk → S3-compatible via env var in a future stage.
No paths, keys, or bucket names are hardcoded.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Artifact types (matches doc-09)
ARTIFACT_TYPES = frozenset({
    "plan",
    "diff",
    "test_results",
    "review_findings",
    "pm_brief",
    "architect_plan",
    "subtasks",
})


@dataclass
class ArtifactRecord:
    artifact_id: str
    task_id: str
    artifact_type: str
    version: int
    storage_path: str
    created_by_agent: str
    created_at: datetime


def _artifacts_dir() -> Path:
    settings = get_settings()
    return Path(settings.worktrees_dir).parent / "artifacts"


def _artifact_path(artifact_id: str) -> Path:
    return _artifacts_dir() / artifact_id


def save_artifact(
    task_id: str | int,
    artifact_type: str,
    content: str | dict[str, Any],
    created_by_agent: str,
    db: Any = None,
) -> ArtifactRecord:
    """
    Save an artifact to local disk and optionally record metadata in DB.

    Content can be a string (diff, plan text) or a dict (will be JSON-serialized).
    Returns an ArtifactRecord with the artifact_id and storage path.
    """
    artifacts_dir = _artifacts_dir()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifact_id = str(uuid.uuid4())
    storage_path = str(_artifact_path(artifact_id))

    if isinstance(content, dict):
        raw = json.dumps(content, indent=2, default=str)
    else:
        raw = str(content)

    Path(storage_path).write_text(raw, encoding="utf-8")

    record = ArtifactRecord(
        artifact_id=artifact_id,
        task_id=str(task_id),
        artifact_type=artifact_type,
        version=1,
        storage_path=storage_path,
        created_by_agent=created_by_agent,
        created_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Artifact saved: id=%s type=%s task=%s agent=%s",
        artifact_id, artifact_type, task_id, created_by_agent,
    )

    return record


async def save_artifact_async(
    task_id: str | int,
    artifact_type: str,
    content: str | dict[str, Any],
    created_by_agent: str,
    db: Any = None,
) -> ArtifactRecord:
    """Async version of save_artifact — persists to configured backend then writes DB row."""
    settings = get_settings()

    if settings.artifact_backend == "s3":
        # S3 path: upload to S3, record the S3 key as storage_path
        payload: dict[str, Any] = (
            content if isinstance(content, dict) else {"content": content}
        )
        artifact_id = str(uuid.uuid4())
        try:
            import asyncio
            from app.artifacts.s3_store import save_artifact_s3

            s3_key = await asyncio.to_thread(
                save_artifact_s3, int(task_id), artifact_type, artifact_id, payload
            )
            storage_path = f"s3://{settings.s3_bucket}/{s3_key}"
        except Exception:
            logger.exception("S3 upload failed for artifact %s — falling back to disk", artifact_id)
            record = save_artifact(task_id, artifact_type, content, created_by_agent)
            artifact_id = record.artifact_id
            storage_path = record.storage_path

        record = ArtifactRecord(
            artifact_id=artifact_id,
            task_id=str(task_id),
            artifact_type=artifact_type,
            version=1,
            storage_path=storage_path,
            created_by_agent=created_by_agent,
            created_at=datetime.now(timezone.utc),
        )
    else:
        record = save_artifact(task_id, artifact_type, content, created_by_agent)

    if db is not None:
        try:
            from sqlalchemy import text
            await db.execute(
                text(
                    "INSERT INTO artifacts (artifact_id, task_id, type, version, storage_path, "
                    "created_by_agent, created_at) VALUES "
                    "(:aid, :tid, :atype, :version, :spath, :agent, :created_at)"
                ),
                {
                    "aid": record.artifact_id,
                    "tid": record.task_id,
                    "atype": record.artifact_type,
                    "version": record.version,
                    "spath": record.storage_path,
                    "agent": record.created_by_agent,
                    "created_at": record.created_at,
                },
            )
            await db.commit()
        except Exception:
            logger.exception("Failed to persist artifact metadata for %s", record.artifact_id)

    return record


def get_artifact(artifact_id: str) -> str | None:
    """Read artifact content from local disk. Returns None if not found."""
    p = _artifact_path(artifact_id)
    if not p.exists():
        logger.warning("Artifact not found on disk: %s", artifact_id)
        return None
    return p.read_text(encoding="utf-8")


async def list_artifacts(task_id: str | int, db: Any = None) -> list[ArtifactRecord]:
    """List all artifacts for a task, newest first."""
    if db is None:
        # Fallback: scan disk for artifacts with task_id in filename is not feasible
        # (artifact_id is UUID, not prefixed by task). Return empty without DB.
        return []

    try:
        from sqlalchemy import text
        rows = await db.execute(
            text(
                "SELECT artifact_id, task_id, type, version, storage_path, created_by_agent, created_at "
                "FROM artifacts WHERE task_id = :tid ORDER BY created_at DESC"
            ),
            {"tid": str(task_id)},
        )
        result = rows.mappings().all()
        return [
            ArtifactRecord(
                artifact_id=str(r["artifact_id"]),
                task_id=str(r["task_id"]),
                artifact_type=str(r["type"]),
                version=int(r["version"]),
                storage_path=str(r["storage_path"]),
                created_by_agent=str(r["created_by_agent"]),
                created_at=r["created_at"],
            )
            for r in result
        ]
    except Exception:
        logger.exception("Failed to list artifacts for task %s", task_id)
        return []
