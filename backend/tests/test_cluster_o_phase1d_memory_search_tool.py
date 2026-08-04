"""Stage 4 Cluster O Phase 1d (2026-08-05) — the memory_search chat/agent
tool (app/agents/tools.py) gained an optional, LLM-provided `repo_id` input
(CLUSTER_O_DESIGN.md change point I / §10 open question 3).

A real finding corrected the design doc's own speculative default before
writing any code: memory_search's only real caller anywhere in the codebase
is knowledge_curator (confirmed via grep — `handlers["memory_search"] =
memory_search` appears nowhere else), and that agent's entire job is
"curating the fleet's persistent engineering memory... so future
memory_hook_node injections stay accurate" — a fleet-wide, cross-repo
curation task, not a per-repo one. CLUSTER_O_DESIGN.md §10 speculated
"current run's repo" would be the safer default; the real caller proves the
opposite would actively break knowledge_curator's actual job (it needs to
see memories from every repo to dedupe/curate the shared store). Omitted
repo_id therefore defaults to fleet-wide (None), matching the same
"intentionally global by default" pattern already established for
record_learning/fleet_dashboard.py's own learning signals — repo_id is
available for a future caller that genuinely wants to narrow, but nothing
narrows unless it explicitly asks to.

memory_search itself does its own asyncio.run() (a sync tool handler, same
shape as embed_learning_signal_sync) — tests here are plain sync functions,
not @pytest.mark.asyncio, matching every other sync-bridge-touching test in
this suite (Phase 1a/1b's own established convention).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from unittest.mock import patch

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.tools import _MEMORY_SEARCH_TOOL, memory_search
from app.db.models import MemoryEmbedding, Repo
from app.db.session import new_isolated_async_engine
from app.memory.store import embed_task_outcome


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clustero-1d-{suffix}",
                    name=f"clustero-1d-{suffix}",
                    local_path=f"/tmp/clustero-1d-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_marker(task_id: str, marker: str, repo_id: int | None) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    await embed_task_outcome(
                        task_id=task_id,
                        description=marker,
                        summary=marker,
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_id,
                    )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _cleanup(task_ids: list[str], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id.in_(task_ids))
                )
                if repo_ids:
                    await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_memory_search_tool_schema_documents_the_optional_repo_id_input() -> None:
    props = _MEMORY_SEARCH_TOOL["input_schema"]["properties"]
    assert "repo_id" in props
    assert props["repo_id"]["type"] == "integer"
    # query is the only required field — repo_id must stay optional
    assert _MEMORY_SEARCH_TOOL["input_schema"]["required"] == ["query"]


def test_memory_search_with_explicit_repo_id_never_leaks_the_other_repos_marker() -> (
    None
):
    """The leak-proof test: 2 real repos, each seeded with a uniquely-markered
    row, and an explicit repo_id call must never surface the other repo's
    marker in its formatted text output (absence-based, deterministic)."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"a-{suffix}")
    repo_b = _make_repo_sync(f"b-{suffix}")
    task_a = f"td-1d-a-{suffix}"
    task_b = f"td-1d-b-{suffix}"
    marker_a = f"CLUSTERO_1D_MARKER_A_{suffix}"
    marker_b = f"CLUSTERO_1D_MARKER_B_{suffix}"

    try:
        _seed_marker(task_a, marker_a, repo_a)
        _seed_marker(task_b, marker_b, repo_b)

        with patch("app.memory.store._embed", side_effect=_vector_for):
            output_a = memory_search(
                {"query": "irrelevant", "top_k": 20, "repo_id": repo_a}
            )
            output_b = memory_search(
                {"query": "irrelevant", "top_k": 20, "repo_id": repo_b}
            )

        assert task_a in output_a
        assert task_b not in output_a, "repo B's row leaked into repo A's scoped search"
        assert task_b in output_b
        assert task_a not in output_b, "repo A's row leaked into repo B's scoped search"
    finally:
        _cleanup([task_a, task_b], [repo_a, repo_b])


def test_memory_search_omitted_repo_id_stays_fleet_wide() -> None:
    """The corrected-default proof: omitting repo_id entirely must still
    surface a repo-scoped row from a search that doesn't filter by repo —
    the real behavior knowledge_curator's real job depends on. Uses a
    freshly created, uniquely-suffixed repo (never seen by any other test)
    so this row is guaranteed to be new/highly-recent and rank into a small
    top_k regardless of what else exists in this shared test DB."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"fleet-{suffix}")
    task_a = f"td-1d-fleet-{suffix}"
    marker_a = f"CLUSTERO_1D_FLEETWIDE_MARKER_{suffix}"

    try:
        _seed_marker(task_a, marker_a, repo_a)

        with patch("app.memory.store._embed", side_effect=_vector_for):
            output = memory_search({"query": "irrelevant", "top_k": 20})

        assert task_a in output, (
            "omitting repo_id must still search fleet-wide and surface a "
            "real repo-scoped row — knowledge_curator's real job depends on "
            "seeing memory from every repo, not just one"
        )
    finally:
        _cleanup([task_a], [repo_a])


def test_memory_search_still_requires_query() -> None:
    """Regression guard: adding repo_id must not have disturbed the
    existing required-query validation."""
    assert memory_search({"repo_id": 1}) == "[ERROR] query is required"
