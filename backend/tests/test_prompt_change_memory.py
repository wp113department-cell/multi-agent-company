"""#405 (2026-09-28, GRIDIRON_PARTIAL "Covers approved prompts/MCPs/tools
as a distinct knowledge type") — folds PromptVersion diffs into the same
embedding-based retrieval every other organizational-knowledge category
(embed_bug/embed_preference/embed_procedure) already uses. Real Postgres,
mocked only at the Voyage embedding boundary (same convention as
test_memory_aware_agent_selection.py).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.memory.store import (
    embed_prompt_change,
    embed_prompt_change_sync,
    format_full_memory_context,
    query_memory_context,
    query_prompt_changes,
)


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_prompt_change_persists_a_real_row(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    role_name = f"role-pc-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            diff = f"-old line\n+new line for {suffix}\n"
            row = await embed_prompt_change(
                role_name=role_name,
                diff_text=diff,
                db=session,
                version_id=7,
                proposed_by="alice",
            )
            assert row is not None
            assert row.category == "prompt_change"
            assert row.outcome == "prompt_change"
            assert row.task_id == f"prompt:{role_name}"
            assert diff.strip() in row.description
            assert row.files_changed == [f"roles/{role_name}.md"]
            # A short, generic diff can legitimately be classified as
            # "draft" by the pre-existing memory quality gate (dampened
            # importance), same as any other category — the real assertion
            # here is that prompt_change gets the SAME 0.7 base weight as
            # architecture, not the generic 0.5 fallback.
            settings = get_settings()
            draft_value = 0.7 * settings.memory_quality_draft_importance_factor
            assert row.importance == pytest.approx(
                0.7
            ) or row.importance == pytest.approx(draft_value)
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id == f"prompt:{role_name}"
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_prompt_changes_finds_the_real_row_back(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    role_name = f"role-pc-query-{suffix}"
    diff = (
        f"-you must never use eval()\n+you must never use eval() or exec() ({suffix})\n"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_prompt_change(
                role_name=role_name,
                diff_text=diff,
                db=session,
                version_id=3,
                proposed_by="bob",
            )
            assert row is not None

            results = await query_prompt_changes(diff, session, top_k=5)
            assert any(r["role_name"] == role_name for r in results)
            matched = next(r for r in results if r["role_name"] == role_name)
            assert matched["diff"] == diff.strip() or diff.strip() in matched["diff"]
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as cleanup:
            await cleanup.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id == f"prompt:{role_name}"
                )
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_memory_context_includes_prompt_changes_key(
    _mock_embed: object,
) -> None:
    engine = _engine()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await query_memory_context("anything", session, top_k=1)
    await engine.dispose()
    assert "prompt_changes" in result
    assert isinstance(result["prompt_changes"], list)


def test_format_full_memory_context_includes_prompt_changes_section() -> None:
    block = format_full_memory_context(
        tasks=[],
        failures=[],
        learnings=[],
        prompt_changes=[
            {
                "role_name": "backend_dev",
                "diff": "-old rule\n+new rule",
                "similarity": 0.91,
            }
        ],
    )
    assert "Approved prompt/role changes" in block
    assert "backend_dev" in block
    assert "new rule" in block


def test_format_full_memory_context_omits_empty_prompt_changes_section() -> None:
    block = format_full_memory_context(
        tasks=[], failures=[], learnings=[], prompt_changes=[]
    )
    assert "Approved prompt/role changes" not in block


def test_embed_prompt_change_sync_bridges_correctly() -> None:
    suffix = uuid.uuid4().hex[:8]
    role_name = f"role-pc-sync-{suffix}"
    with patch("app.memory.store._embed", side_effect=_vector_for):
        ok = embed_prompt_change_sync(
            role_name=role_name,
            diff_text=f"-old\n+new sync test {suffix}\n",
            version_id=1,
            proposed_by="carol",
        )
    assert ok is True

    async def _cleanup() -> None:
        engine = _engine()
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id == f"prompt:{role_name}"
                )
            )
            await session.commit()
        await engine.dispose()

    import asyncio

    asyncio.run(_cleanup())


def test_embed_prompt_change_sync_returns_false_on_failure() -> None:
    with patch("app.memory.store._embed", side_effect=RuntimeError("boom")):
        ok = embed_prompt_change_sync(
            role_name="whatever", diff_text="-a\n+b\n", version_id=1
        )
    assert ok is False
