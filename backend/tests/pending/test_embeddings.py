"""Voyage AI embedding pipeline tests — require VOYAGE_API_KEY."""
from __future__ import annotations

import pytest
from tests.pending.conftest import requires_voyage


@requires_voyage
class TestEmbeddings:
    """Voyage AI: generate_embeddings + semantic_search."""

    def test_generate_embeddings_returns_list(self, tmp_path: pytest.TempPathFactory) -> None:
        """generate_embeddings returns one embedding dict per file in the index."""
        from app.repo_tools.scanner import index_repository
        from app.repo_tools.embeddings import generate_embeddings

        # Create 3 real Python files in tmp_path
        files = {
            "a.py": "def add(x: int, y: int) -> int:\n    return x + y\n",
            "b.py": "def greet(name: str) -> str:\n    return f'Hello {name}'\n",
            "c.py": "class Config:\n    debug: bool = False\n",
        }
        for name, content in files.items():
            (tmp_path / name).write_text(content)

        index = index_repository(str(tmp_path))
        assert len(index.files) == 3

        embeddings = generate_embeddings(index)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert "file_path" in emb
            assert "embedding" in emb
            assert isinstance(emb["embedding"], list)
            assert len(emb["embedding"]) > 0

    def test_semantic_search_returns_relevant_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """semantic_search returns the most relevant file for a query."""
        from app.repo_tools.scanner import index_repository
        from app.repo_tools.embeddings import generate_embeddings, semantic_search

        files = {
            "auth.py": "def authenticate(token: str) -> bool:\n    return token == 'secret'\n",
            "routes.py": "def get_users() -> list:\n    return []\n",
            "config.py": "DATABASE_URL = 'sqlite:///test.db'\n",
        }
        for name, content in files.items():
            (tmp_path / name).write_text(content)

        index = index_repository(str(tmp_path))
        embeddings = generate_embeddings(index)

        results = semantic_search("user authentication token verification", embeddings, top_k=1)

        assert len(results) == 1
        assert "auth" in results[0], (
            f"Expected auth.py to be most relevant for auth query, got: {results[0]}"
        )

    def test_semantic_search_top_k_respected(self, tmp_path: pytest.TempPathFactory) -> None:
        """semantic_search returns at most top_k results."""
        from app.repo_tools.scanner import index_repository
        from app.repo_tools.embeddings import generate_embeddings, semantic_search

        for i in range(5):
            (tmp_path / f"module_{i}.py").write_text(f"def func_{i}() -> None:\n    pass\n")

        index = index_repository(str(tmp_path))
        embeddings = generate_embeddings(index)

        results_3 = semantic_search("function", embeddings, top_k=3)
        results_1 = semantic_search("function", embeddings, top_k=1)

        assert len(results_3) <= 3
        assert len(results_1) <= 1

    def test_semantic_search_empty_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """semantic_search returns [] gracefully when VOYAGE_API_KEY is empty."""
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)

        import app.config as cfg_module
        cfg_module._settings = None

        from app.repo_tools.embeddings import semantic_search

        results = semantic_search("anything", [{"file_path": "x.py", "embedding": [0.1, 0.2]}])
        assert results == []

        cfg_module._settings = None
