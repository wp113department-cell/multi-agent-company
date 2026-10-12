"""Sol A40 (2026-10-12): /ready says whether this instance can actually do
work; /health stays the liveness probe.

Before: /health could be green with no agents loaded, no queue worker, no
code sandbox and storage the app could not write. /ready checks each and
answers 503 naming what is missing. No AI runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def ready_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    s = get_settings()
    monkeypatch.setattr(s, "worktrees_dir", str(tmp_path / "wt"))
    monkeypatch.setattr(s, "repos_dir", str(tmp_path / "repos"))
    monkeypatch.setattr(s, "queue_backend", "asyncio")
    monkeypatch.setattr(s, "bash_sandbox_enabled", True)
    monkeypatch.setattr(s, "require_durable_checkpoints", False)
    with (
        patch("app.services.capabilities.check", return_value={"sandbox": True}),
        patch("app.pipeline.queue_adapter.durability_problem", return_value=None),
    ):
        yield tmp_path


def _ready() -> Any:
    return TestClient(app).get("/ready")


def test_ready_when_everything_works(ready_setup: Path) -> None:
    r = _ready()
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "ready"


def test_not_ready_without_a_sandbox(ready_setup: Path) -> None:
    with patch(
        "app.services.capabilities.check",
        return_value={"sandbox": False, "note": "Docker is not reachable"},
    ):
        r = _ready()
    assert r.status_code == 503
    assert "Docker is not reachable" in r.json()["checks"]["sandbox"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_not_ready_when_storage_is_not_writable(
    ready_setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = ready_setup / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setattr(get_settings(), "repos_dir", str(locked))
    try:
        r = _ready()
    finally:
        locked.chmod(0o700)
    assert r.status_code == 503
    assert r.json()["checks"]["repos"].startswith("error: cannot write")


def test_not_ready_without_agents(ready_setup: Path) -> None:
    with patch("app.fleet.capability_registry.get_capability_registry") as reg:
        reg.return_value.all.return_value = []
        r = _ready()
    assert r.status_code == 503
    assert r.json()["checks"]["agents"] == "error: no agents loaded"


def test_not_ready_without_a_queue_worker(
    ready_setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "queue_backend", "rq")
    with patch("rq.Worker.all", return_value=[]):
        r = _ready()
    assert r.status_code == 503
    assert r.json()["checks"]["worker"] == "error: no queue worker is running"


def test_not_ready_when_progress_cannot_be_saved_and_that_is_required(
    ready_setup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "require_durable_checkpoints", True)
    with patch(
        "app.pipeline.queue_adapter.durability_problem",
        return_value="database saver unavailable",
    ):
        r = _ready()
    assert r.status_code == 503
    assert "database saver unavailable" in r.json()["checks"]["progress"]
