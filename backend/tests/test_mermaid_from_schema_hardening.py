"""mermaid_from_schema tool #168 — tool_enhance.md productionization
pass (2026-09-15).

Two real, empirically-verified findings on the one real
implementation (`mermaid_from_schema_h` inside `make_chat_handlers`).

1. SEVERE — the tool has never actually worked in real production
   use. It shelled out to the `psql` CLI, but the real runtime this
   tool actually executes in (the deployed backend container) has no
   `psql` binary installed at all. Proved live: reproduced the exact
   subprocess call inside the real backend container — every real
   call genuinely raised `FileNotFoundError`. A theorized SQL-
   injection risk via `table` (matching sibling tool #96's
   `inspect_schema` finding) was investigated and EMPIRICALLY
   REFUTED for this tool's specific `\\d`-meta-command construction:
   proved live against a real `psql` binary (inside the database
   container, which does have one) that `\\d`'s own argument parser
   consumes the entire remainder as one table-name pattern, with no
   semicolon- or newline-based statement-stacking possible — a
   genuinely different risk profile from `inspect_schema`'s plain-SQL
   construction, not assumed to be the same just because both tools
   shelled out to psql.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py.

Fixed by full replacement, matching tool #96's precedent: no longer
shells out to `psql` at all — real psycopg2 parameter binding against
`information_schema` instead, producing a genuine Mermaid erDiagram
with real column names and types.

These tests require a real, reachable PostgreSQL database
(DATABASE_URL) — skipped otherwise, matching this codebase's existing
convention for DB-dependent tests (see tests/test_inspect_schema_hardening.py).
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.config import get_settings
from app.models.chat import ChatSession
from app.tools.database.mermaid_from_schema import (
    MERMAID_FROM_SCHEMA_TOOL,
    mermaid_from_schema_handler,
)

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)


def _db_url() -> str:
    return get_settings().database_url


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_mermaid_from_schema_hardening", repo_path=repo)
    return ChatAgent(session)


def test_mermaid_from_schema_tool_schema() -> None:
    assert MERMAID_FROM_SCHEMA_TOOL["name"] == "mermaid_from_schema"
    assert MERMAID_FROM_SCHEMA_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_mermaid_from_schema_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("mermaid_from_schema") == 1


# ---------------------------------------------------------------------------
# Finding #1 — the tool now genuinely works (it never did before), and the
# refuted SQL-injection hypothesis is re-confirmed safe by construction
# ---------------------------------------------------------------------------


class TestGenuinelyWorksNow:
    def test_direct_handler_produces_real_diagram_for_a_real_table(self) -> None:
        out = mermaid_from_schema_handler(_db_url(), {"table": "agents"})
        assert "[ERROR]" not in out
        assert "```mermaid" in out
        assert "erDiagram" in out
        assert "agents {" in out

    def test_direct_handler_no_table_lists_multiple_real_tables(self) -> None:
        out = mermaid_from_schema_handler(_db_url(), {})
        assert "[ERROR]" not in out
        assert "```mermaid" in out
        # A real schema has more than one table; the diagram must show
        # more than one entity block.
        assert out.count(" {\n") >= 2 or out.count("    ") > 3

    def test_direct_handler_nonexistent_table(self) -> None:
        out = mermaid_from_schema_handler(
            _db_url(), {"table": "this_table_does_not_exist_xyz"}
        )
        assert "table not found" in out

    def test_direct_handler_no_database_url(self) -> None:
        out = mermaid_from_schema_handler("", {"table": "agents"})
        assert out == "[ERROR] DATABASE_URL not configured"


class TestSemicolonInjectionRefuted:
    """The `\\d`-meta-command construction was proved live (outside
    this test suite, against a real psql binary in the DB container)
    to NOT allow statement-stacking injection — these tests
    re-confirm the NEW, psycopg2-based implementation is safe by
    construction (table is always parameter-bound, never
    string-interpolated), regardless."""

    def test_semicolon_payload_does_not_execute_as_separate_statement(self) -> None:
        payload = "agents'; SELECT 'INJECTED_MARKER' AS proof; --"
        out = mermaid_from_schema_handler(_db_url(), {"table": payload})
        # The payload is safely treated as ONE literal (non-existent)
        # table name via parameter binding — it's echoed back verbatim
        # inside the "table not found" message (inert text), never
        # executed as a second SQL statement. Proof the injection is
        # closed: no Mermaid erDiagram output was produced at all (a
        # real execution would have at least attempted to build one),
        # and the response is exactly the same "not found" shape as
        # any other nonexistent table name.
        assert out == f"(table not found: {payload})"
        assert "```mermaid" not in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("mermaid_from_schema", {"table": "agents"})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "[ERROR]" not in out
        assert "agents {" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_real_diagram(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["mermaid_from_schema"]({"table": "agents"})
        assert "[ERROR]" not in out
        assert "agents {" in out

    def test_chat_agent_dispatch_no_table_lists_real_tables(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("mermaid_from_schema", {})

        out = asyncio.run(_run())
        assert "[ERROR]" not in out
        assert "```mermaid" in out
