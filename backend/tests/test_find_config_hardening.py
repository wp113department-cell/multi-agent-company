"""find_config tool #99 — tool_enhance.md productionization pass
(2026-08-25).

Two real, empirically-verified findings:

1. The same "an external program's own flag parser accepts an
   LLM-controlled positional field" class already established for
   tools #69/#89/#90/#91, on `find_config_h` and `chat_agent.py`'s
   dispatch — `key="-f"` was silently consumed as grep's own `-f`
   flag; WORSE, `key="--include=*"` left grep with no directory to
   search, causing it to hang reading stdin until timeout — a real,
   reproduced resource-exhaustion vector.
2. `sec_find_config` ignored the `key` field ENTIRELY — it read a
   nonexistent `file_pattern` field and ran a fixed, hardcoded regex,
   so every real call silently searched for the wrong thing.

Fixed via `validate_find_config_key()` (rejects flag-shaped `key`) +
a single shared `find_config_handler()` (also collapses the previous
3-variant retry loop into one `-i` case-insensitive grep call, closing
the hang surface architecturally, not just by rejecting the payload).

All tests here use real files on disk — nothing is mocked.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_security_reviewer_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.find_config import FIND_CONFIG_TOOL, validate_find_config_key


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_find_config_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_find_config_tool_schema_requires_key() -> None:
    assert FIND_CONFIG_TOOL["name"] == "find_config"
    assert FIND_CONFIG_TOOL["input_schema"]["required"] == ["key"]  # type: ignore[index]


def test_find_config_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_config") == 1


# ---------------------------------------------------------------------------
# Pure validator unit tests
# ---------------------------------------------------------------------------


def test_validator_accepts_normal_key() -> None:
    assert validate_find_config_key("DATABASE_URL") is None


def test_validator_rejects_leading_dash() -> None:
    error = validate_find_config_key("-f")
    assert error is not None
    assert "flag" in error


def test_validator_rejects_double_dash_flag() -> None:
    error = validate_find_config_key("--include=*")
    assert error is not None


# ---------------------------------------------------------------------------
# Finding #1 — flag-collision (real, live)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_key(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_config", {"key": "-f"})
    assert "[ERROR]" in result
    assert "flag" in result


@pytest.mark.asyncio
async def test_chat_agent_does_not_hang_on_include_flag_key(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    t0 = time.time()
    result = await agent._execute_tool("find_config", {"key": "--include=*"})
    elapsed = time.time() - t0
    assert "[ERROR]" in result
    assert (
        elapsed < 3
    ), f"took {elapsed}s — should reject instantly, not hang until timeout"


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("security_reviewer", make_security_reviewer_handlers),
    ],
)
def test_both_factories_reject_flag_shaped_key(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["find_config"]({"key": "-f"})
    assert "[ERROR]" in result, f"{factory_name} did not reject the flag-shaped key"


def test_make_chat_handlers_does_not_hang_on_include_flag_key(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    t0 = time.time()
    result = handlers["find_config"]({"key": "--include=*"})
    elapsed = time.time() - t0
    assert "[ERROR]" in result
    assert elapsed < 3


# ---------------------------------------------------------------------------
# Finding #2 — sec_find_config ignored `key` entirely (real, live)
# ---------------------------------------------------------------------------


def test_security_reviewer_actually_searches_for_the_requested_key(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.py").write_text("MY_CUSTOM_SETTING = 'value'\n")
    handlers = make_security_reviewer_handlers(str(tmp_path))
    result = handlers["find_config"]({"key": "MY_CUSTOM_SETTING"})
    assert "MY_CUSTOM_SETTING" in result


def test_security_reviewer_no_longer_returns_unrelated_hardcoded_pattern(
    tmp_path: Path,
) -> None:
    # A file matching the OLD hardcoded pattern but NOT the requested key
    # must not satisfy the search — proves the fixed handler genuinely
    # searches for `key`, not the old fixed host/port/database regex.
    (tmp_path / "config.py").write_text("database_url = 'sqlite:///x.db'\n")
    handlers = make_security_reviewer_handlers(str(tmp_path))
    result = handlers["find_config"]({"key": "TOTALLY_UNRELATED_KEY_XYZ"})
    assert "TOTALLY_UNRELATED_KEY_XYZ" not in result or "not found" in result.lower()
    assert result == "'TOTALLY_UNRELATED_KEY_XYZ' not found in config files"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on all three real
# access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_finds_real_config_key(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("DATABASE_URL=postgresql://localhost/mydb\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_config", {"key": "DATABASE_URL"})
    assert "DATABASE_URL" in result


@pytest.mark.asyncio
async def test_chat_agent_case_insensitive_match(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text("debug = True\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("find_config", {"key": "DEBUG"})
    assert "debug" in result


@pytest.mark.asyncio
async def test_chat_agent_reports_not_found_cleanly(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text("PORT = 8000\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "find_config", {"key": "NONEXISTENT_XYZ_SETTING_12345"}
    )
    assert "not found" in result.lower()


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_security_reviewer_handlers],
)
def test_both_factories_find_real_config_key(tmp_path: Path, factory) -> None:
    (tmp_path / ".env.example").write_text("API_KEY=your_key_here\n")
    handlers = factory(str(tmp_path))
    result = handlers["find_config"]({"key": "API_KEY"})
    assert "API_KEY" in result
