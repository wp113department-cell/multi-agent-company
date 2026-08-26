"""request_clarification tool #117 — tool_enhance.md productionization
pass (2026-08-26).

Audited for every finding class established so far in this initiative
(shell injection, flag/program injection, worktree-boundary escape,
unbounded timeout, advertised-but-not-dispatched, silent
documented-contract divergence) — none apply. `question`/`context`/
`options`/`recommended_option` only ever reach an ORM insert
(`PendingApproval.details`, a JSONB column) via `record_pending()`,
never raw SQL or a shell command. `agent_name`/`task_id` are never
LLM-controlled — both real call sites (`coder.py`, `planner.py`) pass
the calling agent's own fixed name and the graph's own numeric task id.
Deliberately absent from `CHAT_TOOLS` (a one-shot-worker-agent-only
pause mechanism, no interactive-session use case) — confirmed this is
intentional, not a missed dispatch.

Pure modularization turn; these tests exist to prove the behavior
(including a REAL write against the real approval-gate store, verified
via a direct DB query and cleaned up afterward) rather than assert it
from reading alone. The real-DB test is skipped when no DATABASE_URL
is configured, matching this codebase's existing convention for
DB-dependent tests.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.tools.agents.request_clarification import (
    REQUEST_CLARIFICATION_TOOL,
    make_request_clarification_handler,
)


def test_request_clarification_tool_schema_requires_question() -> None:
    assert REQUEST_CLARIFICATION_TOOL["name"] == "request_clarification"
    assert REQUEST_CLARIFICATION_TOOL["input_schema"]["required"] == ["question"]  # type: ignore[index]


def test_request_clarification_not_in_chat_tools() -> None:
    """Deliberate, verified absence — not a missed dispatch."""
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert "request_clarification" not in names


def test_handler_rejects_missing_question() -> None:
    handler = make_request_clarification_handler("td_request_clarification_hardening")
    result = handler({})
    assert result == "[ERROR] question is required."


def test_handler_rejects_blank_question() -> None:
    handler = make_request_clarification_handler("td_request_clarification_hardening")
    result = handler({"question": "   "})
    assert result == "[ERROR] question is required."


def test_handler_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("app.fleet.approval_gate.request_human_input", _boom)
    handler = make_request_clarification_handler("td_request_clarification_hardening")
    result = handler({"question": "q?"})
    assert result.startswith("[ERROR]")


@pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)
def test_handler_records_a_real_pending_approval_row() -> None:
    """Real, end-to-end: writes to the real approval-gate store and
    verifies via a direct DB query, cleaning up afterward."""
    import asyncio

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PendingApproval
    from app.db.session import new_isolated_async_engine

    agent_name = f"td_request_clarification_hardening_{uuid.uuid4().hex[:8]}"
    marker = f"real question {uuid.uuid4().hex[:8]}"
    handler = make_request_clarification_handler(agent_name, "999999")
    result = handler({"question": marker, "context": "some context"})
    assert "recorded" in result.lower()

    async def _verify_and_cleanup() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                rows = (
                    await session.execute(
                        select(PendingApproval).where(
                            PendingApproval.agent_name == agent_name
                        )
                    )
                ).scalars().all()
                assert len(rows) == 1
                assert rows[0].details["question"] == marker
                assert rows[0].details["context"] == "some context"
                assert rows[0].details["blocking"] is False
                assert rows[0].action == "clarification"
                count = len(rows)
                await session.execute(
                    delete(PendingApproval).where(
                        PendingApproval.agent_name == agent_name
                    )
                )
                await session.commit()
                return count
        finally:
            await engine.dispose()

    found = asyncio.run(_verify_and_cleanup())
    assert found == 1
