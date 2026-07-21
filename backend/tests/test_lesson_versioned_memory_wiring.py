"""Gap-closure (2026-07-21) — Day 11's versioned_memory.py was built and fully
tested but never received a real lesson from any actual agent run:
_extract_and_store_lesson() (base_graph.py) only ever wrote to the in-process
LessonStore. This wires the exact call site Day 11's own plan doc identified
as the target.

Gated on a real VOYAGE_API_KEY being configured: a zero-vector embedding can
never be found again by similarity search anyway, and unconditionally writing
one row per test (enable_lesson defaults True across ~2500 existing tests)
was found to pollute OTHER tests' similarity searches with unrelated
zero-vector rows — confirmed by running the full suite, not assumed safe.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _cleanup(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import VersionedLesson

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                # VersionedLesson has no agent_name column — filter by content instead
                await session.execute(delete(VersionedLesson).where(VersionedLesson.topic.like("td_lvm_%")))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _make_tool_use_response(tool_name: str = "submit_result") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id="tu_001", name=tool_name, input={"summary": "done"})],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
@patch("app.agents.base_graph.anthropic.Anthropic")
def test_lesson_flows_into_versioned_memory_when_voyage_key_configured(
    mock_anthropic: Any, _key: Any, _role: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "voyage_api_key", "test-voyage-key")

    lesson_json = (
        '{"lesson": "always validate td_lvm_gap_closure_test inputs", '
        '"pattern": "td_lvm_gap_closure_topic", "category": "general", "reusable": true}'
    )

    def _create(*args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""
        if "Extract a reusable lesson" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=lesson_json)],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )
        return _make_tool_use_response("submit_result")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _create
    mock_anthropic.return_value = mock_client

    async def _fake_embed(text: str) -> list[float]:
        return [0.1] * 1536  # non-zero — real Voyage responses are never all-zero either

    try:
        with patch("app.memory.store._embed", _fake_embed):
            from app.agents.base_graph import VerificationConfig, run_agent_graph

            final_state = run_agent_graph(
                role_name="lesson_versioned_memory_wiring_test_agent",
                model="claude-haiku-4-5-20251001",
                tools=[{
                    "name": "submit_result", "description": "Submit",
                    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
                }],
                tool_handlers={"submit_result": lambda inp: "ok"},
                verification_cfg=VerificationConfig(initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}),
                initial_message="do a task",
                enable_planning=False,
                enable_memory=False,
                enable_reflection=False,
                enable_lesson=True,
            )
            assert final_state["submitted"] is True

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        async def _query() -> list[Any]:
            engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    from app.db.models import VersionedLesson
                    return list((
                        await session.execute(
                            select(VersionedLesson).where(VersionedLesson.topic == "td_lvm_gap_closure_topic")
                        )
                    ).scalars().all())
            finally:
                await engine.dispose()

        rows = asyncio.run(_query())
        assert len(rows) == 1, "lesson never reached versioned_memory"
        assert "td_lvm_gap_closure_test" in rows[0].content
        assert rows[0].state == "published"
    finally:
        _cleanup("lesson_versioned_memory_wiring_test_agent")


@patch("app.agents.base_graph.load_role", return_value="You are a test agent.")
@patch("app.agents.base_graph.get_effective_api_key", return_value="test-key")
@patch("app.agents.base_graph.anthropic.Anthropic")
def test_lesson_skips_versioned_memory_without_voyage_key(
    mock_anthropic: Any, _key: Any, _role: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "voyage_api_key", "")

    lesson_json = (
        '{"lesson": "td_lvm_no_key_test lesson text", "pattern": "td_lvm_no_key_topic", '
        '"category": "general", "reusable": true}'
    )

    def _create(*args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        last_text = str(messages[-1].get("content", "")) if messages else ""
        if "Extract a reusable lesson" in last_text:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=lesson_json)],
                usage=SimpleNamespace(input_tokens=20, output_tokens=15),
            )
        return _make_tool_use_response("submit_result")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _create
    mock_anthropic.return_value = mock_client

    try:
        from app.agents.base_graph import VerificationConfig, run_agent_graph

        final_state = run_agent_graph(
            role_name="lesson_no_voyage_key_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[{
                "name": "submit_result", "description": "Submit",
                "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
            }],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(initial={}, set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=True,
        )
        assert final_state["submitted"] is True

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        async def _query() -> list[Any]:
            engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    from app.db.models import VersionedLesson
                    return list((
                        await session.execute(
                            select(VersionedLesson).where(VersionedLesson.topic == "td_lvm_no_key_topic")
                        )
                    ).scalars().all())
            finally:
                await engine.dispose()

        rows = asyncio.run(_query())
        assert len(rows) == 0, "should skip versioned_memory entirely without a real embedding key"
    finally:
        _cleanup("lesson_no_voyage_key_test_agent")
