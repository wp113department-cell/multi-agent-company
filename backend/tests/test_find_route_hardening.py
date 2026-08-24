"""find_route tool #90 — tool_enhance.md productionization pass
(2026-08-24).

Unlike tool #89's sibling `find_api` (where all four implementations
shared the identical bug), this tool had a genuine split fixed at the
shared `find_route_handler()` in `app.tools.filesystem.find_route`:

`sec_find_route`/`ad_find_route` had a severe field-name mismatch — the
schema declares `method`/`path_pattern`, but both handlers read a
nonexistent `path` field and ignored `method` entirely, so every real,
schema-conformant call silently fell back to a fixed `"/api/"`
substring search. `find_route_h`/`chat_agent.py`'s dispatch were
already correct — proper field names, `method` embedded inside a
fixed non-empty literal regex prefix (structurally immune to
flag-injection, same class as tools #73-75), `path_pattern` used only
as a plain post-grep substring filter (never reaches grep's argv at
all). All four are now unified onto the already-correct design.

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_api_docs_agent_handlers,
    make_chat_handlers,
    make_security_reviewer_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_route import FIND_ROUTE_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_route_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_route_tool_schema_has_no_required_fields() -> None:
    assert FIND_ROUTE_TOOL["name"] == "find_route"
    assert FIND_ROUTE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_find_route_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_route") == 1


def _repo_with_two_routes(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        '@router.post("/orders")\ndef create_order():\n    pass\n\n'
        '@router.get("/users")\ndef get_users():\n    pass\n'
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Finding — field-name mismatch (sec_/ad_), proved closed on all four
# real call sites via a schema-conformant call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_schema_conformant_call_finds_real_route(
    tmp_path: Path,
) -> None:
    _repo_with_two_routes(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_route", {"path_pattern": "/orders", "method": "POST"}
    )
    assert "/orders" in result
    assert "/users" not in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("security_reviewer", make_security_reviewer_handlers),
        ("api_docs_agent", make_api_docs_agent_handlers),
    ],
)
def test_all_three_factories_schema_conformant_call_finds_real_route(
    tmp_path: Path, factory_name: str, factory
) -> None:
    """security_reviewer/api_docs_agent previously read a nonexistent
    `path` field and always fell back to a fixed "/api/" search — a
    real, schema-conformant call must now find the real route."""
    _repo_with_two_routes(tmp_path)
    handlers = factory(str(tmp_path))
    result = handlers["find_route"]({"path_pattern": "/orders", "method": "POST"})
    assert "/orders" in result, f"{factory_name}: field-name mismatch still broken"
    assert "/users" not in result, f"{factory_name}: method filter not respected"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all four real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_no_filters_finds_all_routes(tmp_path: Path) -> None:
    _repo_with_two_routes(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_route", {})
    assert "/orders" in result
    assert "/users" in result


@pytest.mark.asyncio
async def test_chat_agent_method_filter_without_path_pattern(tmp_path: Path) -> None:
    _repo_with_two_routes(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_route", {"method": "GET"})
    assert "/users" in result
    assert "/orders" not in result


@pytest.mark.asyncio
async def test_chat_agent_no_match_reports_cleanly(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_route", {"method": "DELETE"})
    assert "No routes found" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_security_reviewer_handlers, make_api_docs_agent_handlers],
)
def test_all_three_factories_no_filters_finds_all_routes(
    tmp_path: Path, factory
) -> None:
    _repo_with_two_routes(tmp_path)
    handlers = factory(str(tmp_path))
    result = handlers["find_route"]({})
    assert "/orders" in result
    assert "/users" in result
