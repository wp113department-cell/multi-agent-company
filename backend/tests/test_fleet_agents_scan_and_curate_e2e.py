"""Every fleet scan agent can really file a request; knowledge_curator's APPLY
really promotes a lesson (audit 15, 2026-10-06).

Real Postgres; the model is an in-process mock (no network, no API key).
"""

from __future__ import annotations

import asyncio
import importlib
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import EnhancementRequest, VersionedLesson
from app.db.session import get_async_session

# The 8 scans the daily background loop runs (app/main.py _fleet_agents_scan_loop).
SCANS = [
    ("agent_performance_reviewer", "run_agent_performance_reviewer_scan"),
    ("agent_debugger", "run_agent_debugger_scan"),
    ("agent_advisor", "run_agent_advisor_scan"),
    ("knowledge_curator", "run_knowledge_curator_scan"),
    ("quality_auditor", "run_quality_auditor_scan"),
    ("architecture_reviewer", "run_architecture_reviewer_scan"),
    ("dependency_security_agent", "run_dependency_security_scan"),
    ("monitoring_agent", "run_monitoring_agent_scan"),
]


def _reply(turn: int, name: str | None, inp: dict[str, Any] | None = None) -> Any:
    content = (
        [
            SimpleNamespace(
                type="tool_use", id=f"tu{turn}_{name}", name=name, input=inp or {}
            )
        ]
        if name
        else [SimpleNamespace(type="text", text="{}")]
    )
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        stop_reason="tool_use" if name else "end_turn",
    )


@pytest.fixture(autouse=True)
def _economy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "cost_mode", "economy")


@pytest.mark.asyncio
@pytest.mark.parametrize(("agent", "fn"), SCANS, ids=[a for a, _ in SCANS])
async def test_each_scan_agent_files_a_pending_request(agent: str, fn: str) -> None:
    title = f"audit15 scan probe {agent} {uuid.uuid4().hex[:8]}"

    def model(**kw: Any) -> Any:
        tools = {t["name"] for t in kw.get("tools") or []}
        turn = sum(1 for m in kw.get("messages", []) if m.get("role") == "assistant")
        if "submit_enhancement_request" in tools:
            return _reply(
                turn,
                "submit_enhancement_request",
                {
                    "title": title,
                    "description": "probe",
                    "category": "bug",
                    "priority": "low",
                },
            )
        return _reply(turn, None)

    scan = getattr(importlib.import_module(f"app.agents.{agent}"), fn)
    try:
        with patch("anthropic.Anthropic") as cls:
            cls.return_value.messages.create.side_effect = model
            await asyncio.to_thread(scan)
        async with get_async_session() as db:
            row = (
                await db.execute(
                    select(EnhancementRequest).where(EnhancementRequest.title == title)
                )
            ).scalar_one_or_none()
        assert row is not None, f"{agent}'s scan filed nothing"
        assert row.agent_name == agent and row.status == "pending"
    finally:
        async with get_async_session() as db:
            await db.execute(
                delete(EnhancementRequest).where(EnhancementRequest.title == title)
            )
            await db.commit()


@pytest.mark.asyncio
async def test_knowledge_curator_apply_promotes_a_draft_lesson() -> None:
    from app.agents.knowledge_curator import run_knowledge_curator_apply
    from app.fleet.versioned_memory import get_versioned_memory_store

    topic = f"audit15-curator-{uuid.uuid4().hex[:8]}"

    async def fake_embed(text: str) -> list[float]:
        return [float((hash(text) >> i) & 1) for i in range(1536)]

    with patch("app.memory.store._embed", side_effect=fake_embed):
        draft = await asyncio.to_thread(
            get_versioned_memory_store().publish,
            topic,
            f"{topic}: always register new routers in app/main.py",
            "test",
        )
    assert draft.state == "draft"

    def model(**kw: Any) -> Any:
        turn = sum(1 for m in kw.get("messages", []) if m.get("role") == "assistant")
        steps = [
            ("memory_promote_lesson", {"lesson_id": draft.lesson_id}),
            ("submit_fix", {"summary": f"promoted {draft.lesson_id}"}),
        ]
        name, inp = steps[min(turn, len(steps) - 1)]
        return _reply(turn, name, inp)

    try:
        with patch("anthropic.Anthropic") as cls, patch(
            "app.memory.store._embed", side_effect=fake_embed
        ):
            cls.return_value.messages.create.side_effect = model
            result = await asyncio.to_thread(
                run_knowledge_curator_apply, 1, f"Promote lesson {draft.lesson_id}", ""
            )
        assert result.status == "completed", result
        async with get_async_session() as db:
            state = (
                await db.execute(
                    select(VersionedLesson.state).where(
                        VersionedLesson.lesson_id == draft.lesson_id
                    )
                )
            ).scalar_one()
        assert state == "published"
    finally:
        async with get_async_session() as db:
            await db.execute(
                delete(VersionedLesson).where(
                    VersionedLesson.lesson_id == draft.lesson_id
                )
            )
            await db.commit()
