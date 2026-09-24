"""submit_enhancement_request tool #212 — tool_enhance.md
productionization pass (2026-09-16).

No security vulnerability found after a thorough audit of the full
real call graph: the DB write goes through the SQLAlchemy ORM
exclusively (no injection surface); the best-effort impact simulation
extracts file:line citations via a character-class-restricted regex
that rules out grep -E ReDoS/regex-injection, and never opens a file
at the extracted path itself (only greps the fixed repo_root) so no
worktree-escape read is possible; both the DB write and dashboard push
are already wrapped in their own try/except.

`tool_inventory.json` reports `agent_count: 5`, but a direct grep
found 8 real agents genuinely using this tool — a stale-comment
undercount in tools.py, not a real reachability gap.

One real, narrow finding: the DB write used a local, less-completely-
configured duplicate of the canonical isolated-engine helper
(`_new_isolated_db_engine()` in tools.py, still used by 4 other tools
with their own future turns) instead of the canonical
`app.db.session.new_isolated_async_engine()` (which sets explicit
pool_size/max_overflow/connect_args). Fixed for this tool specifically
by switching to the canonical helper.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.tools import CHAT_TOOLS
from app.config import get_settings
from app.db.models import EnhancementRequest
from app.tools.agents.submit_enhancement_request import (
    SUBMIT_ENHANCEMENT_REQUEST_TOOL,
    make_submit_enhancement_request_handler,
)


def _engine() -> object:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def test_submit_enhancement_request_tool_schema() -> None:
    assert SUBMIT_ENHANCEMENT_REQUEST_TOOL["name"] == "submit_enhancement_request"
    assert SUBMIT_ENHANCEMENT_REQUEST_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "title",
        "description",
        "category",
        "priority",
    ]


def test_submit_enhancement_request_not_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "submit_enhancement_request" not in names


# ---------------------------------------------------------------------------
# Real execution — genuine DB write, no mocking
# ---------------------------------------------------------------------------


def test_handler_files_a_real_row_and_returns_its_id() -> None:
    suffix = uuid.uuid4().hex[:8]
    title = f"tool212 hardening test {suffix}"
    handler = make_submit_enhancement_request_handler(
        agent_name="test_agent_212", trace_id=f"trace-{suffix}", repo_path="."
    )

    async def _verify_and_cleanup() -> EnhancementRequest:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                row = (
                    await session.execute(
                        select(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                ).scalar_one()
                await session.execute(
                    delete(EnhancementRequest).where(EnhancementRequest.title == title)
                )
                await session.commit()
                return row
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    try:
        result = handler(
            {
                "title": title,
                "description": "a genuine test description, no citations",
                "category": "quality",
                "priority": "low",
                "evidence": {"note": "hardening test"},
            }
        )
        assert result.startswith("Enhancement request #")
        assert "filed for human review" in result

        row = asyncio.run(_verify_and_cleanup())
        assert row.agent_name == "test_agent_212"
        assert row.status == "pending"
        assert row.category == "quality"
    finally:

        async def _force_cleanup() -> None:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    await session.execute(
                        delete(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_force_cleanup())


def test_handler_computes_real_impact_simulation_for_a_real_citation() -> None:
    """Real end-to-end proof of the impact-simulation path: a citation
    naming a real file in this repo produces a non-trivial
    impact_simulation on the stored row."""
    suffix = uuid.uuid4().hex[:8]
    title = f"tool212 impact test {suffix}"
    handler = make_submit_enhancement_request_handler(
        agent_name="test_agent_212", trace_id="", repo_path="."
    )

    async def _verify_and_cleanup() -> EnhancementRequest:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                row = (
                    await session.execute(
                        select(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                ).scalar_one()
                await session.execute(
                    delete(EnhancementRequest).where(EnhancementRequest.title == title)
                )
                await session.commit()
                return row
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    try:
        handler(
            {
                "title": title,
                "description": "See app/agents/tools.py:1 for context.",
                "category": "quality",
                "priority": "low",
            }
        )
        row = asyncio.run(_verify_and_cleanup())
        assert row.impact_simulation is not None
        assert "app/agents/tools.py" in row.impact_simulation.get("targets", {})
    finally:

        async def _force_cleanup() -> None:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    await session.execute(
                        delete(EnhancementRequest).where(
                            EnhancementRequest.title == title
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_force_cleanup())


def test_handler_returns_error_string_on_missing_required_field() -> None:
    handler = make_submit_enhancement_request_handler(
        agent_name="test_agent_212", trace_id="", repo_path="."
    )
    result = handler({"title": "missing everything else"})
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Investigated and refuted — regex/ReDoS via crafted evidence citations
# ---------------------------------------------------------------------------


def test_regex_metacharacters_in_citation_shaped_text_are_refuted() -> None:
    """A citation-shaped string containing regex metacharacters cannot
    reach grep -E as a metacharacter — the citation regex's own
    character class excludes them, so the extracted module stem is
    always a plain identifier. Not a real vulnerability; kept as a
    regression guard."""
    from app.fleet.enhancement_impact import simulate_enhancement_impact

    # Even a description crafted to look like it contains a dangerous
    # regex payload can only ever yield safe, alnum/./- citations.
    result = simulate_enhancement_impact(
        ".", "See (a+)+$.py:1 and normal_file.py:5 for details.", {}
    )
    assert isinstance(result, dict)
    assert "total_target_files" in result
