"""slack_send_message tool #63 — tool_enhance.md productionization pass
(2026-08-22).

Real finding: `chat_agent.py` had zero dispatch branch for
`slack_send_message` despite it being advertised via `CHAT_TOOLS` —
every real interactive call would have hit "[ERROR] Unknown tool" (the
same "advertised but never dispatched" bug class as tools
#4/#6/#22/#25/#33/#44/#45/#46/#48/#50). The handler's own logic was
already safe (`text` is JSON-encoded, never string-interpolated into a
command or URL). Fixed by adding a real dispatch, gated behind a
confirmation dialog (posting a Slack message is a real, publicly-
visible external write — same risk category as
create_pr/github_comment/github_create_issue/linear_create_issue).

Tests use a REAL local HTTP server standing in for the Slack webhook
(never mocking `urllib.request` itself) so the real request/response
path is exercised end-to-end.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.slack_send_message import (
    SLACK_SEND_MESSAGE_TOOL,
    send_slack_message,
)


class _CapturingHandler(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def fake_webhook() -> Any:
    _CapturingHandler.received = []
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}/webhook", _CapturingHandler.received
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_slack_send_message_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_slack_send_message_tool_schema_requires_text() -> None:
    assert SLACK_SEND_MESSAGE_TOOL["name"] == "slack_send_message"
    assert SLACK_SEND_MESSAGE_TOOL["input_schema"]["required"] == ["text"]  # type: ignore[index]


def test_send_slack_message_posts_real_json_payload(fake_webhook: Any) -> None:
    url, received = fake_webhook
    result = send_slack_message(url, "hello world")
    assert "Slack message sent" in result
    assert received == [{"text": "hello world"}]


# ---------------------------------------------------------------------------
# The proven "advertised but never dispatched" finding, verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatches_slack_send_message_when_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webhook: Any
) -> None:
    url, received = fake_webhook
    monkeypatch.setenv("SLACK_WEBHOOK_URL", url)
    agent = _agent(tmp_path)
    agent._confirm = lambda **kw: _true()  # type: ignore[method-assign]
    result = await agent._execute_tool(
        "slack_send_message", {"text": "real dispatch works"}
    )
    assert "Slack message sent" in result
    assert received == [{"text": "real dispatch works"}]


@pytest.mark.asyncio
async def test_chat_agent_blocks_slack_send_message_when_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webhook: Any
) -> None:
    url, received = fake_webhook
    monkeypatch.setenv("SLACK_WEBHOOK_URL", url)
    agent = _agent(tmp_path)
    agent._confirm = lambda **kw: _false()  # type: ignore[method-assign]
    result = await agent._execute_tool(
        "slack_send_message", {"text": "should never be sent"}
    )
    assert result.startswith("[DENIED]")
    assert received == []


@pytest.mark.asyncio
async def test_chat_agent_errors_cleanly_when_webhook_url_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("slack_send_message", {"text": "x"})
    assert result == "[ERROR] SLACK_WEBHOOK_URL not set"


def test_make_chat_handlers_slack_send_message_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webhook: Any
) -> None:
    url, received = fake_webhook
    monkeypatch.setenv("SLACK_WEBHOOK_URL", url)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["slack_send_message"]({"text": "from make_chat_handlers"})
    assert "Slack message sent" in result
    assert received == [{"text": "from make_chat_handlers"}]


def test_make_chat_handlers_errors_cleanly_when_webhook_url_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["slack_send_message"]({"text": "x"})
    assert result == "[ERROR] SLACK_WEBHOOK_URL not set"


def test_slack_send_message_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("slack_send_message") == 1


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False
