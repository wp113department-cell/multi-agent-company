"""
Artifact Store — local disk adapter with DB metadata.

Every pipeline step writes versioned artifacts:
  plan, diff, test_results, review_findings

Storage path: {ARTIFACTS_DIR}/{artifact_id}
Adapter pattern: swap local disk → S3-compatible via env var in a future stage.
No paths, keys, or bucket names are hardcoded.
"""
from __future__ import annotations

import asyncio
import hashlib
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
    content_sha256: str | None = None


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

    # Blocker (audit_v1.md 4.6 #4): no integrity verification existed on
    # artifacts in either backend — silent disk corruption (or a corrupted
    # S3 object) would be returned to a caller with no detection. Computed
    # at save time from the exact bytes written; get_artifact_content()
    # recomputes and compares on read.
    content_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    record = ArtifactRecord(
        artifact_id=artifact_id,
        task_id=str(task_id),
        artifact_type=artifact_type,
        version=1,
        storage_path=storage_path,
        created_by_agent=created_by_agent,
        created_at=datetime.now(timezone.utc),
        content_sha256=content_sha256,
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
        # Checksum computed over the exact same serialization
        # get_artifact_content()'s S3 read path reconstructs (json.dumps(...,
        # indent=2, default=str)) so a later comparison is meaningful.
        content_sha256: str | None = hashlib.sha256(
            json.dumps(payload, indent=2, default=str).encode("utf-8")
        ).hexdigest()
        artifact_id = str(uuid.uuid4())
        try:
            from app.artifacts.s3_store import save_artifact_s3

            s3_key = await asyncio.to_thread(
                save_artifact_s3, int(task_id), artifact_type, artifact_id, payload
            )
            storage_path = f"s3://{settings.s3_bucket}/{s3_key}"
        except Exception:
            logger.exception("S3 upload failed for artifact %s — falling back to disk", artifact_id)
            record = await asyncio.to_thread(
                save_artifact, task_id, artifact_type, content, created_by_agent
            )
            artifact_id = record.artifact_id
            storage_path = record.storage_path
            content_sha256 = record.content_sha256

        record = ArtifactRecord(
            artifact_id=artifact_id,
            task_id=str(task_id),
            artifact_type=artifact_type,
            version=1,
            storage_path=storage_path,
            created_by_agent=created_by_agent,
            created_at=datetime.now(timezone.utc),
            content_sha256=content_sha256,
        )
    else:
        # Blocker (audit_v1.md 4.6 #2): the non-S3 branch called a plain
        # sync disk-write function with no asyncio.to_thread wrapping,
        # unlike the S3 branch — every artifact save under the default
        # backend blocked the event loop for the write's duration.
        record = await asyncio.to_thread(
            save_artifact, task_id, artifact_type, content, created_by_agent
        )

    if db is not None:
        try:
            from sqlalchemy import text
            await db.execute(
                text(
                    "INSERT INTO artifacts (artifact_id, task_id, type, version, storage_path, "
                    "created_by_agent, created_at, content_sha256) VALUES "
                    "(:aid, :tid, :atype, :version, :spath, :agent, :created_at, :sha256)"
                ),
                {
                    "aid": record.artifact_id,
                    "tid": record.task_id,
                    "atype": record.artifact_type,
                    "version": record.version,
                    "spath": record.storage_path,
                    "agent": record.created_by_agent,
                    "created_at": record.created_at,
                    "sha256": record.content_sha256,
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


async def get_artifact_content(artifact_id: str, db: Any) -> str | None:
    """Retrieve artifact content regardless of storage backend.

    Gap-closure (Audit 06, INFRA-06-002): get_artifact() (above) only ever
    reads local disk -- when ARTIFACT_BACKEND=s3, save_artifact_async()
    correctly uploads to S3, but nothing on the retrieval side ever looked
    there, so S3-backed artifacts 404'd on every read, permanently. This
    looks up the real storage_path recorded at save time (works for both
    backends, and doesn't depend on ARTIFACT_BACKEND's *current* value
    matching whatever it was when this specific artifact was saved) and
    dispatches based on its scheme.
    """
    if db is None:
        # No DB configured -- fall back to the local-disk-only path (matches
        # get_artifact()'s existing behavior for db=None callers).
        return await asyncio.to_thread(get_artifact, artifact_id)

    try:
        from sqlalchemy import text

        row = (
            await db.execute(
                text(
                    "SELECT storage_path, content_sha256 FROM artifacts "
                    "WHERE artifact_id = :aid"
                ),
                {"aid": artifact_id},
            )
        ).mappings().first()
    except Exception:
        logger.exception("Failed to look up artifact %s in DB", artifact_id)
        row = None

    if row is None:
        # No DB row (or DB lookup failed) -- fall back to local disk, since
        # older artifacts saved before this DB-lookup path existed may still
        # be retrievable there even without a matching artifacts row.
        return await asyncio.to_thread(get_artifact, artifact_id)

    storage_path = str(row["storage_path"])
    expected_sha256 = row["content_sha256"]
    if storage_path.startswith("s3://"):
        from app.artifacts.s3_store import load_artifact_s3_by_key

        # s3://{bucket}/{key} -- bucket is whatever it was at save time;
        # strip the scheme and the (already-known) bucket segment, keep key.
        _, _, rest = storage_path.partition("s3://")
        _, _, key = rest.partition("/")
        try:
            payload = await asyncio.to_thread(load_artifact_s3_by_key, key)
        except Exception:
            logger.exception("Failed to load artifact %s from S3", artifact_id)
            return None
        text_content = json.dumps(payload, indent=2, default=str)
        _verify_checksum(artifact_id, text_content, expected_sha256)
        return text_content

    def _read_disk() -> str | None:
        p = Path(storage_path)
        if not p.exists():
            logger.warning("Artifact not found on disk: %s (%s)", artifact_id, storage_path)
            return None
        return p.read_text(encoding="utf-8")

    # Blocker (audit_v1.md 4.6 #2): plain sync disk read inside an async
    # function — same event-loop-blocking issue as the save path.
    disk_content: str | None = await asyncio.to_thread(_read_disk)
    if disk_content is not None:
        _verify_checksum(artifact_id, disk_content, expected_sha256)
    return disk_content


def _verify_checksum(artifact_id: str, content: str, expected_sha256: Any) -> None:
    """Blocker (audit_v1.md 4.6 #4): no integrity verification existed on
    artifacts in either backend. Logs loudly on mismatch rather than
    raising — a corrupted artifact should still be visible to a human
    (e.g. rendered in Mission Control) with a clear warning, not silently
    swallowed as a 500. expected_sha256 is None for any artifact saved
    before this column existed — nothing to compare against, not an error.
    """
    if not expected_sha256:
        return
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual != expected_sha256:
        logger.warning(
            "Artifact %s failed integrity check: expected sha256=%s, got %s "
            "— content may be corrupted",
            artifact_id,
            expected_sha256,
            actual,
        )


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
