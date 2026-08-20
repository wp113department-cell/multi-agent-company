"""linear_create_issue tool #50 — tool_enhance.md productionization
pass (2026-08-20).

Real finding: same "advertised but never dispatched" bug class as
tools #4/#6/#22/#25/#33/#44/#45/#46/#48 — linear_create_issue was
already in CHAT_TOOLS but chat_agent.py had zero dispatch branch, so
every real interactive call would have hit "[ERROR] Unknown tool".

These tests mock urllib.request.urlopen at the module level (never the
real Linear API) so no real, live Linear issue is ever created during
testing, while still genuinely exercising the real dispatch/confirm/
request-building path (real GraphQL query/variables construction).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.linear_create_issue import (
    LINEAR_CREATE_ISSUE_TOOL,
    create_linear_issue,
)


def _fake_urlopen_factory() -> tuple[MagicMock, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, timeout: int = 10) -> Any:
        captured.append({"url": req.full_url, "data": json.loads(req.data)})
        if len(captured) == 1:
            body = json.dumps(
                {"data": {"teams": {"nodes": [{"id": "team-123", "key": "ENG"}]}}}
            )
        else:
            body = json.dumps(
                {
                    "data": {
                        "issueCreate": {
                            "issue": {
                                "id": "i1",
                                "identifier": "ENG-42",
                                "title": "Real Bug",
                            }
                        }
                    }
                }
            )
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = body.encode()
        cm.__exit__.return_value = False
        return cm

    mock = MagicMock(side_effect=fake_urlopen)
    return mock, captured


def _agent(repo: Path, confirm_result: bool) -> ChatAgent:
    session = ChatSession(
        session_id="td_linear_create_issue_hardening", repo_path=str(repo)
    )
    agent = ChatAgent(session)

    async def _fake_confirm(*_a: object, **_kw: object) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_linear_create_issue_tool_schema_requires_fields() -> None:
    assert LINEAR_CREATE_ISSUE_TOOL["name"] == "linear_create_issue"
    assert LINEAR_CREATE_ISSUE_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "title",
        "description",
        "team_key",
    ]


def test_linear_create_issue_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("linear_create_issue") == 1


# ---------------------------------------------------------------------------
# Pure create_linear_issue() tests
# ---------------------------------------------------------------------------


def test_create_linear_issue_uses_graphql_variables_not_interpolation() -> None:
    mock, captured = _fake_urlopen_factory()
    with patch(
        "app.tools.integrations.linear_create_issue.urllib.request.urlopen", mock
    ):
        result = create_linear_issue("fake_key", "Real Bug", "desc", "ENG")

    assert result == "Linear issue created: ENG-42 — Real Bug"
    assert len(captured) == 2
    mutation_call = captured[1]
    assert mutation_call["data"]["variables"] == {
        "title": "Real Bug",
        "desc": "desc",
        "tid": "team-123",
    }
    # The title/description never appear directly inside the query string
    assert "Real Bug" not in mutation_call["data"]["query"]


def test_create_linear_issue_team_not_found() -> None:
    mock = MagicMock()
    body = json.dumps({"data": {"teams": {"nodes": [{"id": "t1", "key": "OTHER"}]}}})
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body.encode()
    cm.__exit__.return_value = False
    mock.return_value = cm

    with patch(
        "app.tools.integrations.linear_create_issue.urllib.request.urlopen", mock
    ):
        result = create_linear_issue("fake_key", "Bug", "desc", "NONEXISTENT")

    assert result == "[ERROR] Team 'NONEXISTENT' not found in Linear"


# ---------------------------------------------------------------------------
# The previously-unreachable tool — now reachable, with a real
# confirmation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_linear_create_issue_missing_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    agent = _agent(tmp_path, confirm_result=True)

    result = await agent._execute_tool(
        "linear_create_issue",
        {"title": "Bug", "description": "desc", "team_key": "ENG"},
    )
    assert result == "[ERROR] LINEAR_API_KEY not set"


@pytest.mark.asyncio
async def test_chat_agent_linear_create_issue_declined_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "fake_key")
    agent = _agent(tmp_path, confirm_result=False)

    result = await agent._execute_tool(
        "linear_create_issue",
        {"title": "Bug", "description": "desc", "team_key": "ENG"},
    )
    assert result == "[DENIED] User declined linear_create_issue."


@pytest.mark.asyncio
async def test_chat_agent_linear_create_issue_approved_invokes_real_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "fake_key")
    agent = _agent(tmp_path, confirm_result=True)
    mock, captured = _fake_urlopen_factory()

    with patch(
        "app.tools.integrations.linear_create_issue.urllib.request.urlopen", mock
    ):
        result = await agent._execute_tool(
            "linear_create_issue",
            {"title": "Real Bug", "description": "desc", "team_key": "ENG"},
        )

    assert result == "Linear issue created: ENG-42 — Real Bug"
    assert len(captured) == 2


# ---------------------------------------------------------------------------
# Regression — make_chat_handlers' own linear_create_issue must keep
# working
# ---------------------------------------------------------------------------


def test_make_chat_handlers_linear_create_issue_real_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "fake_key")
    mock, captured = _fake_urlopen_factory()

    with patch(
        "app.tools.integrations.linear_create_issue.urllib.request.urlopen", mock
    ):
        handlers = make_chat_handlers(str(tmp_path))
        result = handlers["linear_create_issue"](
            {"title": "Real Bug", "description": "desc", "team_key": "ENG"}
        )

    assert result == "Linear issue created: ENG-42 — Real Bug"
    assert len(captured) == 2
