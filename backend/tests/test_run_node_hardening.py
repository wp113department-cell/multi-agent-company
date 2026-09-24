"""run_node tool #60 — tool_enhance.md productionization pass
(2026-08-22).

`code` was already correctly protected on both real implementations via
`shlex.quote()` — proved live: a real shell-metacharacter-and-quote-
breakout payload was NOT shell-interpreted (node's own JS parser
rejected it as invalid syntax). The real, empirically-verified finding:
`timeout` had no upper bound on either real call site —
`int(inp.get("timeout", 30))` was passed straight into
`subprocess.run(..., timeout=...)` unclamped. Proved live on both real
call sites with a monkeypatched `subprocess.run` spy confirming the raw
value reaching the call. Fixed via `MAX_RUN_NODE_TIMEOUT_SECONDS = 300`
(same class and fix pattern as `run_python_snippet`, tool #14).

Tests that need a real `node`/`nodejs` binary are marked and skipped if
unavailable, matching this codebase's own convention for infra-
dependent tests.
"""

from __future__ import annotations

import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.run_node import (
    MAX_RUN_NODE_TIMEOUT_SECONDS,
    RUN_NODE_TOOL,
    run_node_handler,
)

_HAS_NODE = shutil.which("node") is not None or shutil.which("nodejs") is not None

pytestmark = pytest.mark.skipif(
    not _HAS_NODE, reason="requires a real node/nodejs binary"
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_run_node_hardening", repo_path=repo)
    return ChatAgent(session)


def test_run_node_tool_schema_requires_code() -> None:
    assert RUN_NODE_TOOL["name"] == "run_node"
    assert RUN_NODE_TOOL["input_schema"]["required"] == ["code"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Pre-existing protection re-verified live, not re-fixed
# ---------------------------------------------------------------------------


def test_shell_metacharacter_payload_is_not_shell_interpreted(tmp_path: str) -> None:
    marker = "/tmp/run_node_hardening_shell_pwn.txt"
    import os

    if os.path.exists(marker):
        os.remove(marker)
    payload = f"1' ; touch {marker} ; echo '"
    result = run_node_handler(str(tmp_path), {"code": payload})
    assert not os.path.exists(marker)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# The proven unbounded-timeout finding, verified closed on both real call
# sites
# ---------------------------------------------------------------------------


def _spy_timeout_for_node(captured: dict) -> None:
    real_run = subprocess.run

    def spy(*args, **kwargs):
        if args and isinstance(args[0], str) and args[0].startswith("node -e"):
            captured["timeout"] = kwargs.get("timeout")
        return real_run(*args, **kwargs)

    return spy


def test_run_node_handler_clamps_unbounded_timeout(tmp_path: str) -> None:
    captured: dict = {}
    with patch("subprocess.run", side_effect=_spy_timeout_for_node(captured)):
        run_node_handler(
            str(tmp_path), {"code": "console.log(1)", "timeout": 999999999}
        )
    assert captured.get("timeout") == MAX_RUN_NODE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_chat_agent_run_node_clamps_unbounded_timeout(tmp_path) -> None:
    captured: dict = {}
    agent = _agent(str(tmp_path))
    with patch("subprocess.run", side_effect=_spy_timeout_for_node(captured)):
        await agent._execute_tool(
            "run_node", {"code": "console.log(1)", "timeout": 999999999}
        )
    assert captured.get("timeout") == MAX_RUN_NODE_TIMEOUT_SECONDS


def test_make_chat_handlers_run_node_clamps_unbounded_timeout(tmp_path) -> None:
    captured: dict = {}
    handlers = make_chat_handlers(str(tmp_path))
    with patch("subprocess.run", side_effect=_spy_timeout_for_node(captured)):
        handlers["run_node"]({"code": "console.log(1)", "timeout": 999999999})
    assert captured.get("timeout") == MAX_RUN_NODE_TIMEOUT_SECONDS


def test_run_node_handler_clamps_below_minimum_to_one(tmp_path: str) -> None:
    captured: dict = {}
    with patch("subprocess.run", side_effect=_spy_timeout_for_node(captured)):
        run_node_handler(str(tmp_path), {"code": "console.log(1)", "timeout": -5})
    assert captured.get("timeout") == 1


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


def test_run_node_handler_runs_legitimate_code(tmp_path: str) -> None:
    result = run_node_handler(str(tmp_path), {"code": "console.log(2+2)"})
    assert "4" in result


@pytest.mark.asyncio
async def test_chat_agent_run_node_runs_legitimate_code(tmp_path) -> None:
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("run_node", {"code": "console.log(3+3)"})
    assert "6" in result


def test_make_chat_handlers_run_node_runs_legitimate_code(tmp_path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["run_node"]({"code": "console.log(5+5)"})
    assert "10" in result


def test_run_node_default_timeout_unaffected(tmp_path: str) -> None:
    captured: dict = {}
    with patch("subprocess.run", side_effect=_spy_timeout_for_node(captured)):
        run_node_handler(str(tmp_path), {"code": "console.log(1)"})
    assert captured.get("timeout") == 30


def test_run_node_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("run_node") == 1
