"""Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23) — found while
wiring the new repo-intelligence persistence layer: index_repository() with
known_hashes set returns ONLY changed files (unchanged ones are skipped and
never added to the result); scanner.merge_indexes() exists specifically to
reunite that partial result with the previous full index, but had zero real
callers anywhere. _do_reindex() fed the partial result straight back into
_known_hashes/_file_count, and get_context() re-derived its own partial
index the same way on every call — both silently degraded to only ever
seeing recently-changed files after the very first reindex ever ran.

Driven through a real TestClient (POST /api/repo/reindex uses a single-level
BackgroundTasks.add_task(), same safe pattern established in
test_launch_coder_bootstrap.py) against a real temp-dir repo, so this
exercises the actual module-level _known_hashes/_cached_index state, not a
mock of it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _reset_reindex_state() -> None:
    import app.api.repo as repo_module

    repo_module._known_hashes = {}
    repo_module._cached_index = None
    repo_module._indexed_at = None
    repo_module._file_count = 0


def test_second_reindex_keeps_the_full_file_set(tmp_path: Path) -> None:
    """The actual bug: before the fix, a second reindex call (after the
    first populated _known_hashes) would shrink _file_count/_known_hashes
    down to just the changed file, losing every unchanged file's record."""
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("def bar():\n    return 2\n")

    import app.api.repo as repo_module

    _reset_reindex_state()
    try:
        # One TestClient context (one lifespan cycle) for both calls —
        # lifespan's own init_active_repo() runs on __enter__ and would
        # otherwise overwrite _active_repo_path with whatever real repo is
        # active in the DB, on every new TestClient(app) context.
        with TestClient(app) as client:
            repo_module._active_repo_path = str(tmp_path)

            first = client.post("/api/repo/reindex")
            assert first.status_code == 200, first.text
            assert repo_module._file_count == 2
            assert set(repo_module._known_hashes.keys()) == {"a.py", "b.py"}
            assert repo_module._cached_index is not None
            assert set(repo_module._cached_index.files.keys()) == {"a.py", "b.py"}

            # Change only one file, then reindex again.
            (tmp_path / "a.py").write_text("def foo():\n    return 999\n")
            second = client.post("/api/repo/reindex")
            assert second.status_code == 200, second.text

            # Before the fix: _file_count would drop to 1 and _known_hashes/
            # _cached_index would only contain "a.py" — b.py's record
            # silently lost even though b.py still exists on disk, unchanged.
            assert repo_module._file_count == 2
            assert set(repo_module._known_hashes.keys()) == {"a.py", "b.py"}
            assert set(repo_module._cached_index.files.keys()) == {"a.py", "b.py"}
            # The changed file's cached hash reflects the new content, not
            # the first reindex's stale value.
            assert (
                repo_module._known_hashes["a.py"]
                == repo_module._cached_index.files["a.py"].content_hash
            )
    finally:
        repo_module._active_repo_path = None
        _reset_reindex_state()


def test_get_context_uses_the_full_cached_index_not_a_partial_one(
    tmp_path: Path,
) -> None:
    """The parallel bug in get_context(): it used to call
    index_repository(repo_path, known_hashes=_known_hashes) directly on every
    request, which — after any reindex had populated _known_hashes — returns
    only changed files, starving build_context() of the rest of the repo."""
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "calculator.py").write_text(
        "from math_utils import add\n\ndef total(a, b):\n    return add(a, b)\n"
    )

    import app.api.repo as repo_module

    _reset_reindex_state()
    try:
        with TestClient(app) as client:
            repo_module._active_repo_path = str(tmp_path)

            reindex_resp = client.post("/api/repo/reindex")
            assert reindex_resp.status_code == 200, reindex_resp.text

            # _known_hashes is now populated (2 files) — this is exactly the
            # state that used to make get_context()'s own internal
            # index_repository() call return a partial index.
            assert len(repo_module._known_hashes) == 2

            # Capture the actual `idx` argument get_context() passes to
            # build_context() directly — the real fix under test, independent
            # of build_context()'s own relevance-scoring behavior (which may
            # legitimately score one file 0 for a given query and exclude it
            # from relevantFiles — a separate, correct, unrelated concern).
            captured_idx = {}
            real_build_context = __import__(
                "app.repo_tools.context_builder", fromlist=["build_context"]
            ).build_context

            def _spy_build_context(task_description: str, idx: object) -> object:
                captured_idx["files"] = set(idx.files.keys())  # type: ignore[attr-defined]
                return real_build_context(task_description, idx)

            with patch(
                "app.repo_tools.context_builder.build_context",
                side_effect=_spy_build_context,
            ):
                context_resp = client.get(
                    "/api/repo/context",
                    params={"task_description": "add two numbers"},
                )
            assert context_resp.status_code == 200, context_resp.text

        assert captured_idx["files"] == {"math_utils.py", "calculator.py"}
    finally:
        repo_module._active_repo_path = None
        _reset_reindex_state()


async def test_weekly_reindex_loop_delegates_to_do_reindex() -> None:
    """Gap-closure (2026-07-23): the weekly loop used to run its own separate
    index_repository() scan whose result was discarded entirely (no
    persistence, no _cached_index update) and which always reindexed
    whichever repo_path was active at process startup, never a repo switched
    to later. Delegating to _do_reindex() fixes both — verified here as a
    real call, not just "the function exists"."""
    import asyncio as asyncio_module

    from app.main import _weekly_reindex_loop

    call_count = 0

    async def _fake_do_reindex() -> None:
        nonlocal call_count
        call_count += 1

    async def _sleep_once_then_stop(_seconds: float) -> None:
        if call_count >= 1:
            raise asyncio_module.CancelledError()

    with patch("app.api.repo._do_reindex", new=_fake_do_reindex), patch(
        "asyncio.sleep", new=_sleep_once_then_stop
    ):
        with pytest.raises(asyncio_module.CancelledError):
            await _weekly_reindex_loop()

    assert call_count == 1
