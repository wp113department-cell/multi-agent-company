"""Artifact store tests — save, get, list, content types."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.artifacts.store import (
    save_artifact,
    get_artifact,
    list_artifacts,
    ArtifactRecord,
)


@pytest.fixture()
def tmp_artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect artifact storage to a temp dir for test isolation."""
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    # Monkeypatch the settings worktrees_dir so _artifacts_dir() uses tmp_path
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.worktrees_dir = str(worktrees)
    monkeypatch.setattr("app.artifacts.store.get_settings", lambda: mock_settings)
    return tmp_path / "artifacts"


def test_save_artifact_string_content(tmp_artifacts_dir: Path) -> None:
    record = save_artifact("1", "plan", "Implement add_user endpoint", "pm")
    assert record.artifact_id
    assert record.task_id == "1"
    assert record.artifact_type == "plan"
    assert record.version == 1
    assert record.created_by_agent == "pm"
    assert Path(record.storage_path).exists()


def test_save_artifact_dict_content(tmp_artifacts_dir: Path) -> None:
    content = {"subtasks": [{"id": 1, "type": "backend"}], "risk_level": "low"}
    record = save_artifact("2", "architect_plan", content, "architect")
    raw = Path(record.storage_path).read_text()
    parsed = json.loads(raw)
    assert parsed["risk_level"] == "low"
    assert len(parsed["subtasks"]) == 1


def test_get_artifact_returns_content(tmp_artifacts_dir: Path) -> None:
    record = save_artifact("3", "diff", "--- a/foo.py\n+++ b/foo.py\n", "coder")
    content = get_artifact(record.artifact_id)
    assert content is not None
    assert "foo.py" in content


def test_get_artifact_nonexistent_returns_none(tmp_artifacts_dir: Path) -> None:
    result = get_artifact("nonexistent-uuid-1234")
    assert result is None


def test_multiple_artifacts_different_ids(tmp_artifacts_dir: Path) -> None:
    r1 = save_artifact("5", "test_results", '{"passed": 10}', "qa")
    r2 = save_artifact("5", "review_findings", '{"verdict": "approved"}', "reviewer")
    assert r1.artifact_id != r2.artifact_id
    assert Path(r1.storage_path).exists()
    assert Path(r2.storage_path).exists()


def test_save_artifact_content_roundtrip(tmp_artifacts_dir: Path) -> None:
    content = "QA passed: 63/63 tests"
    record = save_artifact("6", "test_results", content, "qa")
    retrieved = get_artifact(record.artifact_id)
    assert retrieved == content


def test_artifact_record_fields(tmp_artifacts_dir: Path) -> None:
    record = save_artifact("7", "pm_brief", {"goals": ["improve perf"]}, "pm")
    assert isinstance(record, ArtifactRecord)
    assert record.task_id == "7"
    assert record.artifact_type == "pm_brief"
    assert record.created_at is not None


@pytest.mark.asyncio
async def test_list_artifacts_without_db_returns_empty(tmp_artifacts_dir: Path) -> None:
    """Without a DB, list_artifacts returns empty (UUID filenames don't encode task_id)."""
    save_artifact("10", "plan", "plan text", "pm")
    result = await list_artifacts("10", db=None)
    assert result == []
