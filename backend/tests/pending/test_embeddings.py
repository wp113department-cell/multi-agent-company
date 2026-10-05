"""Voyage AI embedding pipeline tests — require VOYAGE_API_KEY.

semantic_search() searches the code_embeddings table by repo_path (it no
longer takes an in-memory list), so the search tests persist first and clean
up after. The Voyage free tier allows 3 requests/minute, so calls are paced.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from tests.pending.conftest import requires_voyage

_VOYAGE_GAP_S = 21.0  # free tier: 3 requests/minute
_last_call = [0.0]


def _pace() -> None:
    wait = _last_call[0] + _VOYAGE_GAP_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _persist(repo_path: str, embeddings: list[dict[str, Any]]) -> None:
    from app.db.session import new_isolated_async_engine
    from app.repo_tools.embeddings import persist_code_embeddings
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine)() as db:
                await persist_code_embeddings(repo_path, embeddings, db)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _cleanup(repo_path: str) -> None:
    from app.db.session import new_isolated_async_engine
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine)() as db:
                await db.execute(
                    text("DELETE FROM code_embeddings WHERE repo_path = :r"),
                    {"r": repo_path},
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


@requires_voyage
class TestEmbeddings:
    """Voyage AI: generate_embeddings + semantic_search."""

    def test_generate_embeddings_returns_list(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
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

        _pace()
        embeddings = generate_embeddings(index)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert "file_path" in emb
            assert "embedding" in emb
            assert isinstance(emb["embedding"], list)
            assert len(emb["embedding"]) > 0

    def test_semantic_search_returns_relevant_file(self, tmp_path: Any) -> None:
        """The auth file ranks first for an authentication query."""
        from app.repo_tools.embeddings import generate_embeddings, semantic_search
        from app.repo_tools.scanner import index_repository

        files = {
            "auth.py": "def authenticate(token: str) -> bool:\n    return token == 'secret'\n",
            "routes.py": "def get_users() -> list:\n    return []\n",
            "config.py": "DATABASE_URL = 'sqlite:///test.db'\n",
        }
        for name, content in files.items():
            (tmp_path / name).write_text(content)
        repo = str(tmp_path)
        try:
            _pace()
            _persist(repo, generate_embeddings(index_repository(repo)))
            _pace()
            results = semantic_search(
                "user authentication token verification", repo, top_k=1
            )
            assert len(results) == 1
            assert "auth" in results[0], f"Expected auth.py first, got: {results[0]}"
        finally:
            _cleanup(repo)

    def test_semantic_search_top_k_respected(self, tmp_path: Any) -> None:
        """Exactly top_k results come back when more files are indexed."""
        from app.repo_tools.embeddings import generate_embeddings, semantic_search
        from app.repo_tools.scanner import index_repository

        for i in range(5):
            (tmp_path / f"module_{i}.py").write_text(
                f"def func_{i}() -> None:\n    pass\n"
            )
        repo = str(tmp_path)
        try:
            _pace()
            _persist(repo, generate_embeddings(index_repository(repo)))
            _pace()
            assert len(semantic_search("function", repo, top_k=3)) == 3
            _pace()
            assert len(semantic_search("function", repo, top_k=1)) == 1
        finally:
            _cleanup(repo)

    def test_semantic_search_empty_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """semantic_search returns [] gracefully when VOYAGE_API_KEY is empty."""
        import app.config as cfg_module
        from app.repo_tools.embeddings import semantic_search

        monkeypatch.setenv("VOYAGE_API_KEY", "")
        cfg_module._settings = None
        try:
            assert semantic_search("anything", "/nonexistent/repo") == []
        finally:
            cfg_module._settings = None
