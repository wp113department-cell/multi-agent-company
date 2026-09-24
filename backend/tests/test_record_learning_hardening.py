"""record_learning tool #66 — tool_enhance.md productionization pass
(2026-08-22).

Audited for every finding class established so far in this initiative
(shell injection, flag/program injection, worktree-boundary escape,
unbounded timeout, advertised-but-not-dispatched) — none apply. This
tool has no filesystem path or network destination in its input schema
at all; `finding`/`outcome` only ever reach a vector-embedding call and
an ORM insert, never raw SQL or a shell command. `agent_name` is never
LLM-controlled — every real call site passes a static string literal.
Deliberately absent from `CHAT_TOOLS` (a fleet-governance memory tool,
no interactive-session use case) — confirmed this is intentional, not
a missed dispatch.

Pure modularization turn; these tests exist to prove the behavior
(including a REAL write against the real memory store, verified via a
direct DB query and cleaned up afterward) rather than assert it from
reading alone.
"""

from __future__ import annotations

import uuid


from app.tools.agents.record_learning import (
    RECORD_LEARNING_TOOL,
    make_record_learning_handler,
)


def test_record_learning_tool_schema_requires_finding() -> None:
    assert RECORD_LEARNING_TOOL["name"] == "record_learning"
    assert RECORD_LEARNING_TOOL["input_schema"]["required"] == ["finding"]  # type: ignore[index]


def test_record_learning_not_in_chat_tools() -> None:
    """Deliberate, verified absence — not a missed dispatch."""
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert "record_learning" not in names


def test_handler_rejects_missing_finding() -> None:
    handler = make_record_learning_handler("td_record_learning_hardening")
    result = handler({})
    assert result == "[ERROR] finding is required."


def test_handler_rejects_blank_finding() -> None:
    handler = make_record_learning_handler("td_record_learning_hardening")
    result = handler({"finding": "   "})
    assert result == "[ERROR] finding is required."


def test_handler_defaults_outcome_when_omitted() -> None:
    """Real, end-to-end: writes to the real memory store and verifies
    via a direct DB query, cleaning up afterward."""
    import asyncio

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import MemoryEmbedding
    from app.db.session import new_isolated_async_engine

    agent_name = f"td_record_learning_hardening_{uuid.uuid4().hex[:8]}"
    marker = f"real finding {uuid.uuid4().hex[:8]}"
    handler = make_record_learning_handler(agent_name)
    result = handler({"finding": marker})
    assert result == "Recorded."

    async def _verify_and_cleanup() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rows = (
                    (
                        await session.execute(
                            select(MemoryEmbedding).where(
                                MemoryEmbedding.agent_name == agent_name
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 1
                assert marker in rows[0].description
                assert rows[0].summary == "recorded during task execution"
                deleted = await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.agent_name == agent_name
                    )
                )
                await session.commit()
                return deleted.rowcount
        finally:
            await engine.dispose()

    deleted_count = asyncio.run(_verify_and_cleanup())
    assert deleted_count == 1


def test_handler_attributes_to_the_correct_agent_name() -> None:
    """`agent_name` is baked into the handler at construction time —
    proves two different handlers can never cross-attribute."""
    import asyncio

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import MemoryEmbedding
    from app.db.session import new_isolated_async_engine

    agent_a = f"td_rl_hardening_a_{uuid.uuid4().hex[:8]}"
    agent_b = f"td_rl_hardening_b_{uuid.uuid4().hex[:8]}"
    handler_a = make_record_learning_handler(agent_a)
    handler_b = make_record_learning_handler(agent_b)

    result_a = handler_a({"finding": "finding from agent A"})
    result_b = handler_b({"finding": "finding from agent B"})
    assert result_a == "Recorded."
    assert result_b == "Recorded."

    async def _verify_and_cleanup() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rows_a = (
                    (
                        await session.execute(
                            select(MemoryEmbedding).where(
                                MemoryEmbedding.agent_name == agent_a
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                rows_b = (
                    (
                        await session.execute(
                            select(MemoryEmbedding).where(
                                MemoryEmbedding.agent_name == agent_b
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows_a) == 1
                assert len(rows_b) == 1
                assert "agent A" in rows_a[0].description
                assert "agent B" in rows_b[0].description
                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.agent_name.in_([agent_a, agent_b])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_verify_and_cleanup())


def test_qa_and_reviewer_tool_bundles_still_include_record_learning() -> None:
    from app.agents.tools import QA_TOOLS, REVIEWER_TOOLS

    assert any(t["name"] == "record_learning" for t in QA_TOOLS)
    assert any(t["name"] == "record_learning" for t in REVIEWER_TOOLS)
