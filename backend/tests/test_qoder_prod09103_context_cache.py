"""Qoder cross-check PROD-09-103 (2026-10-02): the repo-context cache grew
forever, and invalidate_context_cache(repo_path) compared the path against
SHA-256 keys so it never removed anything — after a re-index agents kept
getting stale context.
"""

from __future__ import annotations

import pytest

from app.repo_tools import context_builder as cb


@pytest.fixture(autouse=True)
def _clean() -> None:
    cb.invalidate_context_cache()
    yield
    cb.invalidate_context_cache()


def _put(desc: str, repo: str) -> str:
    key = cb._cache_key(desc, repo)
    cb._context_cache[key] = (repo, object())  # type: ignore[assignment]
    return key


def test_invalidating_a_repo_removes_only_its_entries() -> None:
    a = _put("task one", "/work/repo-a")
    b = _put("task two", "/work/repo-b")
    cb.invalidate_context_cache("/work/repo-a/")
    assert a not in cb._context_cache, "repo-a entry survived its invalidation"
    assert b in cb._context_cache


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.repo_tools.scanner import index_repository

    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    index = index_repository(str(tmp_path))
    monkeypatch.setattr(cb, "_CONTEXT_CACHE_MAX", 3)
    for i in range(8):
        cb.build_context(f"alpha task number {i}", index)
    assert len(cb._context_cache) == 3
