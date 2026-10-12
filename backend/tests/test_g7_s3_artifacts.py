"""G7 (2026-10-12): the S3 artifact path, run for real against a local
S3-compatible store (SeaweedFS in a throwaway container).

Before: ARTIFACT_BACKEND=s3 had never been run live, and the client could
only talk to AWS (no endpoint setting), so MinIO, Cloudflare R2 or
Backblaze B2 could not be used at all. Now S3_ENDPOINT_URL exists and an
artifact makes the full trip: saved through the app's own store, recorded
in the database as s3://…, read back by id with its checksum verified, and
deleted. Skips without Docker.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
import uuid
from typing import Any

import pytest

# MinIO no longer publishes public images; SeaweedFS is a small, openly
# published S3-compatible server that accepts any credentials by default.
IMAGE = "chrislusf/seaweedfs:3.80"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def minio() -> Any:
    if not shutil.which("docker"):
        pytest.skip("needs Docker")
    name, port = f"g7-minio-{uuid.uuid4().hex[:8]}", _free_port()
    started = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-p", f"127.0.0.1:{port}:8333",
            IMAGE, "server", "-s3", "-dir=/data",
        ],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    if started.returncode:
        pytest.skip(f"the S3 server could not start: {started.stderr[-300:]}")
    url = f"http://127.0.0.1:{port}"
    try:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=url,
            aws_access_key_id="g7user",
            aws_secret_access_key="g7password1",
            region_name="us-east-1",
        )
        for _ in range(60):
            try:
                client.create_bucket(Bucket="g7-artifacts")
                break
            except Exception:
                time.sleep(1)
        else:
            pytest.skip("the S3 server did not become ready")
        yield url, client
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


@pytest.fixture
def s3_backend(minio: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.artifacts import s3_store
    from app.config import get_settings

    url, client = minio
    s = get_settings()
    for key, value in {
        "artifact_backend": "s3",
        "s3_bucket": "g7-artifacts",
        "s3_endpoint_url": url,
        "aws_access_key_id": "g7user",
        "aws_secret_access_key": "g7password1",
    }.items():
        monkeypatch.setattr(s, key, value)
    s3_store.reset_client()
    yield client
    s3_store.reset_client()


def test_an_artifact_makes_the_full_trip_through_s3(s3_backend: Any) -> None:
    from sqlalchemy import delete, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.artifacts.store import get_artifact_content, save_artifact_async
    from app.config import get_settings
    from app.db.repository import create_task

    payload = {"summary": "G7 live S3 trip", "findings": ["a", "b"], "n": 3}

    async def go() -> tuple[Any, Any, list[str]]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                task = await create_task(db, "g7 s3 artifact", "d")
                record = await save_artifact_async(
                    str(task.id), "agent_result", payload, "g7_test", db=db
                )
                loaded = await get_artifact_content(record.artifact_id, db=db)
                stored = (
                    await db.execute(
                        text(
                            "SELECT storage_path FROM artifacts WHERE artifact_id = :a"
                        ),
                        {"a": record.artifact_id},
                    )
                ).scalar_one()
                from app.db.models import DevTask

                await db.execute(delete(DevTask).where(DevTask.id == task.id))
                await db.commit()
                listed = [
                    o["Key"]
                    for o in s3_backend.list_objects_v2(Bucket="g7-artifacts").get(
                        "Contents", []
                    )
                ]
                return stored, loaded, listed
        finally:
            await engine.dispose()

    stored, loaded, listed = asyncio.run(go())
    assert str(stored).startswith("s3://g7-artifacts/gridiron/artifacts/")
    assert any(k.endswith(".json.gz") for k in listed)  # really in the bucket
    assert loaded is not None and '"G7 live S3 trip"' in str(loaded)


def test_save_list_and_delete_by_key(s3_backend: Any) -> None:
    from app.artifacts import s3_store

    key = s3_store.save_artifact_s3(424242, "plan", "abc", {"x": 1})
    assert s3_store.load_artifact_s3(424242, "plan", "abc") == {"x": 1}
    assert key in s3_store.list_artifacts_s3(424242)
    s3_store.delete_artifact_s3(424242, "plan", "abc")
    assert s3_store.list_artifacts_s3(424242) == []
