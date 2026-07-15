"""S3 artifact storage adapter.

Provides `save_artifact_s3` and `load_artifact_s3` for storing agent output
artifacts in AWS S3 instead of (or in addition to) the PostgreSQL artifacts table.

When `artifact_backend=db` (default), this module is never called.
When `artifact_backend=s3`, `save_artifact_async` in store.py delegates here.

Key format: {s3_key_prefix}{task_id}/{artifact_type}/{artifact_id}.json

Design notes:
- Boto3 client is lazily initialised from config fields.
- Falls back to environment credentials / IAM role when aws_access_key_id is empty.
- All operations are synchronous (boto3 is sync); callers use asyncio.to_thread.
- JSON content is gzip-compressed before upload to reduce storage cost.
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_s3_client: Any = None


def _get_s3() -> Any:
    """Lazy-initialise boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        import boto3
        from app.config import get_settings

        settings = get_settings()
        kwargs: dict[str, Any] = {"region_name": settings.s3_region}
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _s3_client = boto3.client("s3", **kwargs)
        logger.info("S3 client initialised (region=%s)", settings.s3_region)
    return _s3_client


def _make_key(task_id: int, artifact_type: str, artifact_id: str) -> str:
    from app.config import get_settings

    prefix = get_settings().s3_key_prefix.rstrip("/")
    return f"{prefix}/{task_id}/{artifact_type}/{artifact_id}.json.gz"


def save_artifact_s3(
    task_id: int,
    artifact_type: str,
    artifact_id: str,
    payload: dict[str, Any],
) -> str:
    """Compress and upload artifact JSON to S3. Returns the S3 key."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.s3_bucket:
        raise ValueError("s3_bucket must be set when artifact_backend=s3")

    key = _make_key(task_id, artifact_type, artifact_id)
    body = gzip.compress(json.dumps(payload).encode("utf-8"))

    _get_s3().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
        Metadata={
            "task_id": str(task_id),
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    logger.info("Artifact saved to s3://%s/%s", settings.s3_bucket, key)
    return key


def load_artifact_s3(
    task_id: int,
    artifact_type: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Download and decompress an artifact from S3. Returns the payload dict."""
    from app.config import get_settings

    settings = get_settings()
    key = _make_key(task_id, artifact_type, artifact_id)
    response = _get_s3().get_object(Bucket=settings.s3_bucket, Key=key)
    body: bytes = response["Body"].read()
    result: dict[str, Any] = json.loads(gzip.decompress(body).decode("utf-8"))
    return result


def list_artifacts_s3(task_id: int, artifact_type: str | None = None) -> list[str]:
    """List all artifact keys for a task (optionally filtered by type)."""
    from app.config import get_settings

    settings = get_settings()
    prefix = settings.s3_key_prefix.rstrip("/") + f"/{task_id}/"
    if artifact_type:
        prefix += f"{artifact_type}/"

    paginator = _get_s3().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def delete_artifact_s3(
    task_id: int,
    artifact_type: str,
    artifact_id: str,
) -> None:
    """Delete a single artifact from S3."""
    from app.config import get_settings

    settings = get_settings()
    key = _make_key(task_id, artifact_type, artifact_id)
    _get_s3().delete_object(Bucket=settings.s3_bucket, Key=key)
    logger.info("Deleted artifact s3://%s/%s", settings.s3_bucket, key)


def reset_client() -> None:
    """Reset the singleton S3 client (used in tests)."""
    global _s3_client
    _s3_client = None
