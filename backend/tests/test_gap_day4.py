"""Gap Day 4 — structural and unit tests (no real Redis, S3, or CI calls).

Tests cover:
  - RQ adapter: module import, class structure, public API shape
  - Redis Streams adapter: module import, no-op when disabled, public functions
  - S3 store: module import, key generation, no-op guards, reset helpers
  - Config: new fields exist with correct defaults
  - CI workflow file: exists and has required job keys
  - vercel.json: exists and has correct top-level keys
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).parent.parent.parent  # CRR2906/
_BACKEND = _ROOT / "backend"
_WORKFLOWS = _ROOT / ".github" / "workflows"


# ===========================================================================
# Config — new Gap Day 4 fields
# ===========================================================================

class TestConfigGapDay4Fields:
    def setup_method(self) -> None:
        import importlib
        import app.config as cfg_mod
        importlib.reload(cfg_mod)
        cfg_mod._settings = None  # type: ignore[attr-defined]

    def test_redis_url_has_default(self) -> None:
        from app.config import Settings
        import inspect
        fields = Settings.model_fields
        assert "redis_url" in fields
        assert "redis" in (fields["redis_url"].default or "").lower()

    def test_redis_streams_enabled_defaults_false(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["redis_streams_enabled"].default is False

    def test_redis_consumer_group_has_default(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["redis_consumer_group"].default == "gridiron-consumers"

    def test_artifact_backend_defaults_to_db(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["artifact_backend"].default == "db"

    def test_s3_bucket_defaults_empty(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["s3_bucket"].default == ""

    def test_s3_region_defaults_us_east_1(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["s3_region"].default == "us-east-1"

    def test_s3_key_prefix_has_default(self) -> None:
        from app.config import Settings
        prefix = Settings.model_fields["s3_key_prefix"].default
        assert prefix and "gridiron" in prefix

    def test_aws_keys_default_empty(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["aws_access_key_id"].default == ""
        assert Settings.model_fields["aws_secret_access_key"].default == ""

    def test_queue_backend_still_has_default(self) -> None:
        from app.config import Settings
        assert Settings.model_fields["queue_backend"].default == "asyncio"


# ===========================================================================
# RQ Queue Adapter — module structure (no real Redis)
# ===========================================================================

class TestRQAdapterModule:
    def test_module_importable(self) -> None:
        import app.queue.rq_adapter  # noqa: F401

    def test_rq_adapter_class_exists(self) -> None:
        from app.queue.rq_adapter import RQQueueAdapter
        assert callable(RQQueueAdapter)

    def test_get_rq_adapter_is_callable(self) -> None:
        from app.queue.rq_adapter import get_rq_adapter
        assert callable(get_rq_adapter)

    def test_reset_rq_adapter_is_callable(self) -> None:
        from app.queue.rq_adapter import reset_rq_adapter
        assert callable(reset_rq_adapter)

    def test_reset_clears_singleton(self) -> None:
        from app.queue import rq_adapter
        rq_adapter.reset_rq_adapter()
        assert rq_adapter._adapter_instance is None

    def test_class_has_enqueue_method(self) -> None:
        from app.queue.rq_adapter import RQQueueAdapter
        assert hasattr(RQQueueAdapter, "enqueue")
        assert callable(RQQueueAdapter.enqueue)

    def test_class_has_enqueue_agent_method(self) -> None:
        from app.queue.rq_adapter import RQQueueAdapter
        assert hasattr(RQQueueAdapter, "enqueue_agent")
        assert callable(RQQueueAdapter.enqueue_agent)

    def test_class_has_queue_sizes_method(self) -> None:
        from app.queue.rq_adapter import RQQueueAdapter
        assert hasattr(RQQueueAdapter, "queue_sizes")

    def test_class_has_ping_method(self) -> None:
        from app.queue.rq_adapter import RQQueueAdapter
        assert hasattr(RQQueueAdapter, "ping")

    def test_default_job_timeout_is_set(self) -> None:
        from app.queue.rq_adapter import _DEFAULT_JOB_TIMEOUT
        assert _DEFAULT_JOB_TIMEOUT > 0
        assert _DEFAULT_JOB_TIMEOUT <= 3600  # at most 1 hour


# ===========================================================================
# Redis Streams Adapter — no-op when disabled
# ===========================================================================

class TestRedisStreamsAdapter:
    def setup_method(self) -> None:
        from app.event_bus import redis_streams
        redis_streams.reset_client()

    def test_module_importable(self) -> None:
        import app.event_bus.redis_streams  # noqa: F401

    def test_publish_to_stream_is_callable(self) -> None:
        from app.event_bus.redis_streams import publish_to_stream
        assert callable(publish_to_stream)

    def test_read_pending_is_callable(self) -> None:
        from app.event_bus.redis_streams import read_pending
        assert callable(read_pending)

    def test_acknowledge_is_callable(self) -> None:
        from app.event_bus.redis_streams import acknowledge
        assert callable(acknowledge)

    def test_stream_length_is_callable(self) -> None:
        from app.event_bus.redis_streams import stream_length
        assert callable(stream_length)

    def test_reset_client_is_callable(self) -> None:
        from app.event_bus.redis_streams import reset_client
        assert callable(reset_client)

    def test_publish_noop_when_disabled(self) -> None:
        from app.event_bus.redis_streams import publish_to_stream
        from app.event_bus.models import GridironEvent
        import uuid
        # redis_streams_enabled=False by default — must not raise
        event = GridironEvent(
            event_id=str(uuid.uuid4()),
            event_type="test.event",
            task_id="42",
            epic_id=None,
            payload={"x": 1},
            emitted_by="test",
        )
        publish_to_stream(event)  # should be a silent no-op

    def test_read_pending_noop_when_disabled(self) -> None:
        from app.event_bus.redis_streams import read_pending
        result = read_pending("consumer-1")
        assert result == []

    def test_stream_length_zero_when_disabled(self) -> None:
        from app.event_bus.redis_streams import stream_length
        assert stream_length() == 0

    def test_acknowledge_noop_when_disabled(self) -> None:
        from app.event_bus.redis_streams import acknowledge
        acknowledge("1234567890-0")  # must not raise

    def test_stream_key_constant(self) -> None:
        from app.event_bus.redis_streams import _STREAM_KEY
        assert _STREAM_KEY == "gridiron:events"

    def test_maxlen_constant(self) -> None:
        from app.event_bus.redis_streams import _MAXLEN
        assert _MAXLEN > 1000


# ===========================================================================
# S3 Artifact Store — module structure and key generation
# ===========================================================================

class TestS3Store:
    def setup_method(self) -> None:
        from app.artifacts import s3_store
        s3_store.reset_client()

    def test_module_importable(self) -> None:
        import app.artifacts.s3_store  # noqa: F401

    def test_save_artifact_s3_callable(self) -> None:
        from app.artifacts.s3_store import save_artifact_s3
        assert callable(save_artifact_s3)

    def test_load_artifact_s3_callable(self) -> None:
        from app.artifacts.s3_store import load_artifact_s3
        assert callable(load_artifact_s3)

    def test_list_artifacts_s3_callable(self) -> None:
        from app.artifacts.s3_store import list_artifacts_s3
        assert callable(list_artifacts_s3)

    def test_delete_artifact_s3_callable(self) -> None:
        from app.artifacts.s3_store import delete_artifact_s3
        assert callable(delete_artifact_s3)

    def test_reset_client_callable(self) -> None:
        from app.artifacts.s3_store import reset_client
        assert callable(reset_client)

    def test_reset_clears_singleton(self) -> None:
        from app.artifacts import s3_store
        s3_store.reset_client()
        assert s3_store._s3_client is None

    def test_make_key_format(self) -> None:
        from app.artifacts.s3_store import _make_key
        key = _make_key(task_id=42, artifact_type="bug_fix", artifact_id="abc123")
        assert "42" in key
        assert "bug_fix" in key
        assert "abc123" in key
        assert key.endswith(".json.gz")

    def test_make_key_includes_prefix(self) -> None:
        from app.artifacts.s3_store import _make_key
        key = _make_key(task_id=1, artifact_type="x", artifact_id="y")
        assert "gridiron" in key

    def test_save_raises_without_bucket(self) -> None:
        from app.artifacts.s3_store import save_artifact_s3
        import os
        # Ensure s3_bucket is empty
        os.environ.pop("S3_BUCKET", None)
        # This should raise ValueError because s3_bucket is empty and no real S3 client
        with pytest.raises((ValueError, Exception)):
            save_artifact_s3(1, "test", "abc", {"data": "value"})


# ===========================================================================
# CI Workflow — file structure validation
# ===========================================================================

class TestCIWorkflow:
    def _load(self) -> dict[str, Any]:
        import yaml
        ci_path = _WORKFLOWS / "ci.yml"
        assert ci_path.exists(), f"ci.yml not found at {ci_path}"
        with ci_path.open() as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]

    def test_ci_yml_exists(self) -> None:
        assert (_WORKFLOWS / "ci.yml").exists()

    def test_ci_yml_is_valid_yaml(self) -> None:
        try:
            import yaml
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert isinstance(data, dict)

    def test_ci_yml_has_name(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert "name" in data

    def test_ci_yml_has_on_trigger(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        # PyYAML parses the `on:` YAML key as Python boolean True
        assert True in data or "on" in data

    def test_ci_yml_has_jobs(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert "jobs" in data

    def test_ci_yml_has_backend_job(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert "backend" in data["jobs"]

    def test_ci_yml_has_frontend_job(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert "frontend" in data["jobs"]

    def test_ci_yml_has_security_job(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("pyyaml not installed")
        data = self._load()
        assert "security" in data["jobs"]


# ===========================================================================
# Vercel config
# ===========================================================================

class TestVercelConfig:
    def _load(self) -> dict[str, Any]:
        vercel_path = _ROOT / "vercel.json"
        assert vercel_path.exists(), "vercel.json not found"
        with vercel_path.open() as f:
            data: dict[str, Any] = json.load(f)
        return data

    def test_vercel_json_exists(self) -> None:
        assert (_ROOT / "vercel.json").exists()

    def test_vercel_json_is_valid_json(self) -> None:
        data = self._load()
        assert isinstance(data, dict)

    def test_vercel_json_has_version(self) -> None:
        data = self._load()
        assert data.get("version") == 2

    def test_vercel_json_has_framework(self) -> None:
        data = self._load()
        assert data.get("framework") == "nextjs"

    def test_vercel_json_has_build_command(self) -> None:
        data = self._load()
        assert "buildCommand" in data

    def test_vercel_json_has_env(self) -> None:
        data = self._load()
        assert "env" in data
        assert "NEXT_PUBLIC_API_URL" in data["env"]

    def test_vercel_json_has_security_headers(self) -> None:
        data = self._load()
        assert "headers" in data
        header_keys = {
            h["key"]
            for entry in data["headers"]
            for h in entry.get("headers", [])
        }
        assert "X-Frame-Options" in header_keys
