"""wait_for_port tool #207 — tool_enhance.md productionization pass
(2026-09-16).

Two findings on the one real implementation (`wait_for_port_h` inside
`make_chat_handlers`, plus `app/agents/chat_agent.py`'s dispatch, which
never existed until this turn).

1. `host` was a completely unrestricted, LLM-controlled TCP
   connect-probe target — a real network-reconnaissance/blind-SSRF-
   adjacent primitive. Deliberately scoped NARROWER than the full
   `_ssrf_denial_reason()` guard `fetch_url`/`check_url_status` use
   (tool #126): this tool's own purpose is checking a just-started
   LOCAL dev server's port (`host` defaults to `"localhost"`), so
   loopback/private-network addresses remain allowed — only the cloud
   instance-metadata link-local range (169.254.0.0/16 / fe80::/10) is
   rejected, proved live to correctly distinguish
   169.254.169.254 (blocked) from 127.0.0.1/localhost (allowed).
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py
   (same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206)
   — every real interactive-chat call fell through to "[ERROR] Unknown
   tool".
"""

from __future__ import annotations

import socket
import threading

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.wait_for_port import (
    WAIT_FOR_PORT_TOOL,
    wait_for_port_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_wait_for_port_hardening", repo_path=repo)
    return ChatAgent(session)


def _real_open_port() -> tuple[socket.socket, int]:
    """A real, live listening TCP socket on localhost for legitimate-
    usage tests — not mocked."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def test_wait_for_port_tool_schema() -> None:
    assert WAIT_FOR_PORT_TOOL["name"] == "wait_for_port"
    assert WAIT_FOR_PORT_TOOL["input_schema"]["required"] == ["port"]  # type: ignore[index]


def test_wait_for_port_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("wait_for_port") == 1


# ---------------------------------------------------------------------------
# Finding #1 — link-local (cloud metadata) probing blocked, localhost allowed
# ---------------------------------------------------------------------------


def test_handler_blocks_cloud_metadata_link_local_address() -> None:
    result = wait_for_port_handler(
        {"host": "169.254.169.254", "port": 80, "timeout": 1}
    )
    assert "[POLICY DENIED]" in result
    assert "link-local" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_blocks_cloud_metadata_link_local_address(
    tmp_path,
) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "wait_for_port", {"host": "169.254.169.254", "port": 80, "timeout": 1}
    )
    assert "[POLICY DENIED]" in result


def test_make_chat_handlers_blocks_cloud_metadata_link_local_address(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["wait_for_port"](
        {"host": "169.254.169.254", "port": 80, "timeout": 1}
    )
    assert "[POLICY DENIED]" in result


def test_handler_allows_localhost_real_open_port() -> None:
    """Real localhost port checks are the tool's stated core purpose —
    proves the narrower guard doesn't break it, unlike the full SSRF
    denylist would have."""
    srv, port = _real_open_port()
    try:
        result = wait_for_port_handler({"host": "127.0.0.1", "port": port, "timeout": 5})
        assert "is open" in result
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Finding #2 — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool(tmp_path) -> None:
    srv, port = _real_open_port()
    try:
        agent = _agent(str(tmp_path))
        result = await agent._execute_tool(
            "wait_for_port", {"host": "127.0.0.1", "port": port, "timeout": 5}
        )
        assert "Unknown tool" not in result
        assert "is open" in result
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths
# ---------------------------------------------------------------------------


def test_handler_times_out_on_a_real_closed_port() -> None:
    # Bind and immediately close to get a real, currently-unused port.
    tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()

    result = wait_for_port_handler({"host": "127.0.0.1", "port": port, "timeout": 1})
    assert "[TIMEOUT]" in result


def test_handler_detects_a_port_that_opens_mid_wait() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]

    def _listen_after_delay() -> None:
        import time

        time.sleep(0.3)
        srv.listen(1)

    t = threading.Thread(target=_listen_after_delay)
    t.start()
    try:
        result = wait_for_port_handler({"host": "127.0.0.1", "port": port, "timeout": 5})
        assert "is open" in result
    finally:
        t.join()
        srv.close()


def test_make_chat_handlers_wait_for_port_still_works() -> None:
    srv, port = _real_open_port()
    try:
        handlers = make_chat_handlers("/tmp")
        result = handlers["wait_for_port"]({"host": "127.0.0.1", "port": port, "timeout": 5})
        assert "is open" in result
    finally:
        srv.close()
