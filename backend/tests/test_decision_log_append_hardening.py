"""decision_log_append tool #133 — tool_enhance.md productionization
pass (2026-09-11).

Audited for every finding class established so far in this initiative
(shell injection, flag/program injection, worktree-boundary escape,
unbounded timeout) — none apply. There is no LLM-controlled filesystem
path anywhere in this tool's input schema — the target file is a
fixed, deterministic path derived from an MD5 hash of `repo_path`
(never LLM-controlled — every real call site passes the session/
agent's own fixed repo path). `decision`/`reason`/`alternatives` reach
the file only as plain JSON-serialized string values, never as raw
text concatenated into anything executable.

One real finding — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132.

Pure "close the missing dispatch" turn; these tests exist to prove the
behavior (including real writes verified via a direct file read, not
just a returned string) rather than assert it from reading alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.agents.decision_log_append import (
    DECISION_LOG_APPEND_TOOL,
    decision_log_append_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_decision_log_append_hardening", repo_path=repo)
    return ChatAgent(session)


def _decisions_file(repo_path: str) -> Path:
    slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    mem_dir = Path(__file__).resolve().parent.parent / "app" / "memory"
    return mem_dir / f"{slug}_decisions.jsonl"


def test_decision_log_append_tool_schema() -> None:
    assert DECISION_LOG_APPEND_TOOL["name"] == "decision_log_append"
    assert DECISION_LOG_APPEND_TOOL["input_schema"]["required"] == ["decision", "reason"]  # type: ignore[index]


def test_decision_log_append_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("decision_log_append") == 1


# ---------------------------------------------------------------------------
# Finding — advertised but never dispatched (chat_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_no_longer_unknown_tool() -> None:
    repo = f"/tmp/td_decision_log_dispatch_{id(object())}"
    agent = _agent(repo)
    # The chat agent passes str(Path(repo_path)) — "\\tmp\\..." on Windows —
    # so derive the file from that exact string, not the raw POSIX literal.
    target = _decisions_file(str(agent.root))
    if target.exists():
        target.unlink()
    try:
        result = await agent._execute_tool(
            "decision_log_append", {"decision": "use Redis", "reason": "speed"}
        )
        assert "Unknown tool" not in result
        assert result.startswith("Decision logged:")
        assert target.exists()
        line = json.loads(target.read_text().splitlines()[-1])
        assert line["decision"] == "use Redis"
        assert line["reason"] == "speed"
    finally:
        if target.exists():
            target.unlink()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, writing to the real, deterministic target file
# ---------------------------------------------------------------------------


def test_handler_writes_a_real_entry_with_alternatives() -> None:
    repo = f"/tmp/td_decision_log_direct_{id(object())}"
    target = _decisions_file(repo)
    if target.exists():
        target.unlink()
    try:
        result = decision_log_append_handler(
            repo,
            {
                "decision": "use SQLite",
                "reason": "simplicity",
                "alternatives": "Postgres",
            },
        )
        assert result == "Decision logged: use SQLite"
        line = json.loads(target.read_text().splitlines()[-1])
        assert line["decision"] == "use SQLite"
        assert line["reason"] == "simplicity"
        assert line["alternatives"] == "Postgres"
        assert "timestamp" in line
    finally:
        if target.exists():
            target.unlink()


def test_handler_defaults_alternatives_when_omitted() -> None:
    repo = f"/tmp/td_decision_log_noalt_{id(object())}"
    target = _decisions_file(repo)
    if target.exists():
        target.unlink()
    try:
        decision_log_append_handler(repo, {"decision": "d", "reason": "r"})
        line = json.loads(target.read_text().splitlines()[-1])
        assert line["alternatives"] == ""
    finally:
        if target.exists():
            target.unlink()


def test_make_chat_handlers_writes_a_real_entry() -> None:
    repo = f"/tmp/td_decision_log_factory_{id(object())}"
    target = _decisions_file(repo)
    if target.exists():
        target.unlink()
    try:
        handlers = make_chat_handlers(repo)
        result = handlers["decision_log_append"](
            {"decision": "use gRPC", "reason": "perf"}
        )
        assert result == "Decision logged: use gRPC"
        assert target.exists()
    finally:
        if target.exists():
            target.unlink()


def test_different_repo_paths_write_to_different_files() -> None:
    repo_a = f"/tmp/td_decision_log_a_{id(object())}"
    repo_b = f"/tmp/td_decision_log_b_{id(object())}"
    target_a = _decisions_file(repo_a)
    target_b = _decisions_file(repo_b)
    assert target_a != target_b
    for t in (target_a, target_b):
        if t.exists():
            t.unlink()
    try:
        decision_log_append_handler(repo_a, {"decision": "A", "reason": "a"})
        assert target_a.exists()
        assert not target_b.exists()
    finally:
        for t in (target_a, target_b):
            if t.exists():
                t.unlink()
