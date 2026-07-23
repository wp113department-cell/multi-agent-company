"""Architecture Mapper tests (files/GAPS_ALL_FILES_REPORT.md gap-closure,
2026-07-23). REPO-FIRST research found no static-analysis precedent for
this in any of the 10 reference repos — this is deliberately a single,
JSON-schema-validated LLM call over real structural signals (folder
structure, READMEs, cross-file-graph PageRank), not a novel algorithm.
Every test here mocks the Anthropic client — no real API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.repo_tools.architecture_mapper import (
    ArchitectureMap,
    _gather_folder_structure,
    _gather_readmes,
    build_architecture_map,
)
from app.repo_tools.scanner import index_repository


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "api.py").write_text("def route():\n    pass\n")
    (tmp_path / "app" / "README.md").write_text("# App layer\nHandles requests.\n")
    (tmp_path / "README.md").write_text("# Demo Project\nA small demo.\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "README.md").write_text("should be ignored")
    return tmp_path


def _fake_anthropic_response(payload: dict) -> MagicMock:
    text_block = MagicMock()
    text_block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [text_block]
    return response


VALID_PAYLOAD = {
    "summary": "A small FastAPI backend with one API layer.",
    "components": [
        {
            "name": "API layer",
            "description": "Handles HTTP routes.",
            "files": ["app/api.py"],
            "depends_on": [],
        }
    ],
}


class TestGatherFolderStructure:
    def test_lists_real_directories(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        structure = _gather_folder_structure(str(repo))
        assert any("app/" in s for s in structure)

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        structure = _gather_folder_structure(str(repo))
        assert not any("node_modules" in s for s in structure)


class TestGatherReadmes:
    def test_finds_real_readmes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        readmes = _gather_readmes(str(repo))
        assert "README.md" in readmes
        assert "app/README.md" in readmes
        assert "Demo Project" in readmes["README.md"]

    def test_ignores_node_modules_readme(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        readmes = _gather_readmes(str(repo))
        assert not any("node_modules" in k for k in readmes)


class TestBuildArchitectureMap:
    def test_returns_validated_map_on_success(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        idx = index_repository(str(repo))

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _fake_anthropic_response(
                VALID_PAYLOAD
            )
            mock_anthropic.return_value = mock_client

            result = build_architecture_map(str(repo), idx)

        assert isinstance(result, ArchitectureMap)
        assert result.summary == VALID_PAYLOAD["summary"]
        assert len(result.components) == 1
        assert result.components[0].name == "API layer"

    def test_retries_once_on_invalid_json_then_succeeds(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        idx = index_repository(str(repo))

        bad_block = MagicMock()
        bad_block.text = "not valid json at all"
        bad_response = MagicMock()
        bad_response.content = [bad_block]

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [
                bad_response,
                _fake_anthropic_response(VALID_PAYLOAD),
            ]
            mock_anthropic.return_value = mock_client

            result = build_architecture_map(str(repo), idx)

        assert result.summary == VALID_PAYLOAD["summary"]
        assert mock_client.messages.create.call_count == 2

    def test_soft_failure_after_all_retries_exhausted(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        idx = index_repository(str(repo))

        bad_block = MagicMock()
        bad_block.text = "still not json"
        bad_response = MagicMock()
        bad_response.content = [bad_block]

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = bad_response
            mock_anthropic.return_value = mock_client

            result = build_architecture_map(str(repo), idx)

        # Never raises — soft failure, matching this codebase's convention
        # for best-effort repo-intelligence features.
        assert isinstance(result, ArchitectureMap)
        assert result.components == []
        assert "Failed to generate architecture map" in result.summary

    def test_missing_required_field_triggers_retry(self, tmp_path: Path) -> None:
        """A JSON-valid but schema-invalid response (missing "summary")
        must be treated the same as invalid JSON — retried, not accepted."""
        repo = _make_repo(tmp_path)
        idx = index_repository(str(repo))

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [
                _fake_anthropic_response({"components": []}),  # missing "summary"
                _fake_anthropic_response(VALID_PAYLOAD),
            ]
            mock_anthropic.return_value = mock_client

            result = build_architecture_map(str(repo), idx)

        assert result.summary == VALID_PAYLOAD["summary"]
        assert mock_client.messages.create.call_count == 2


class TestArchitectureEndpoint:
    """Endpoint-level test — proves GET /api/repo/architecture is really
    wired to build_architecture_map(), not just unit-tested in isolation."""

    def test_get_architecture_returns_the_mapped_result(self, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        import app.api.repo as repo_module
        from app.main import app

        repo = _make_repo(tmp_path)

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _fake_anthropic_response(
                VALID_PAYLOAD
            )
            mock_anthropic.return_value = mock_client

            with patch.object(
                repo_module, "get_active_repo_path", return_value=str(repo)
            ), patch.object(repo_module, "_cached_index", None):
                with TestClient(app) as client:
                    resp = client.get("/api/repo/architecture")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"] == VALID_PAYLOAD["summary"]
        assert body["components"][0]["name"] == "API layer"
