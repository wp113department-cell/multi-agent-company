"""memory_write tool #51 — tool_enhance.md productionization pass
(2026-08-20).

Two real findings:

1. Reachability (same "advertised but never dispatched" class as tools
   #4/#6/#22/#25/#33/#44/#45/#46/#48/#50): already in CHAT_TOOLS, zero
   chat_agent.py dispatch.
2. Severe, empirically-proven data-loss race condition, new class for
   this initiative: the original memory_write_h did a plain, unlocked
   read-modify-write. Proved live with 20 threads calling memory_write
   concurrently against the same store — 17 of 20 writes were silently
   lost. A second, more subtle bug surfaced even after adding a
   properly-scoped lock: releasing the lock before flush() still lost
   updates, since Python's buffered file object doesn't guarantee a
   write reached the OS file before another reader sees it.

Every test here uses real threads/real file I/O against a real JSON
store on disk — never mocked — and proves the fix against the REAL
dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.agents.memory_write import (
    MEMORY_WRITE_TOOL,
    memory_store_path,
    write_memory_key,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_memory_write_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_memory_write_tool_schema_requires_key_and_value() -> None:
    assert MEMORY_WRITE_TOOL["name"] == "memory_write"
    assert MEMORY_WRITE_TOOL["input_schema"]["required"] == ["key", "value"]  # type: ignore[index]


def test_memory_write_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("memory_write") == 1


# ---------------------------------------------------------------------------
# The proven lost-update race condition — verified closed
# ---------------------------------------------------------------------------


def test_write_memory_key_survives_20_concurrent_threads(tmp_path: Path) -> None:
    repo = str(tmp_path)

    def writer(i: int) -> None:
        write_memory_key(repo, f"key{i}", f"value{i}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    store = json.loads(memory_store_path(repo).read_text())
    missing = [i for i in range(20) if f"key{i}" not in store]
    assert missing == [], f"lost updates for keys: {missing}"
    assert len(store) == 20


@pytest.mark.asyncio
async def test_chat_agent_memory_write_survives_20_concurrent_calls(
    tmp_path: Path,
) -> None:
    repo = tmp_path
    agent = _agent(repo)

    tasks = [
        agent._execute_tool("memory_write", {"key": f"key{i}", "value": f"value{i}"})
        for i in range(20)
    ]
    await asyncio.gather(*tasks)

    store = json.loads(memory_store_path(str(repo)).read_text())
    missing = [i for i in range(20) if f"key{i}" not in store]
    assert missing == [], f"lost updates for keys: {missing}"


# ---------------------------------------------------------------------------
# The reachability fix — verified live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_memory_write_real_write(tmp_path: Path) -> None:
    repo = tmp_path
    agent = _agent(repo)

    result = await agent._execute_tool(
        "memory_write", {"key": "greeting", "value": "hello world"}
    )
    assert result == "Memory written: greeting"

    store = json.loads(memory_store_path(str(repo)).read_text())
    assert store["greeting"] == "hello world"


# ---------------------------------------------------------------------------
# Regression — cross-implementation and cross-tool consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_write_and_read_agree_across_both_implementations(
    tmp_path: Path,
) -> None:
    repo = tmp_path
    agent = _agent(repo)

    await agent._execute_tool("memory_write", {"key": "k1", "value": "from_chat_agent"})

    handlers = make_chat_handlers(str(repo))
    read_result = handlers["memory_read"]({"key": "k1"})
    assert read_result == "from_chat_agent"

    write_result = handlers["memory_write"]({"key": "k1", "value": "from_batch_handler"})
    assert write_result == "Memory written: k1"

    # memory_read has no chat_agent.py dispatch of its own yet (separate,
    # not-yet-reached tracking row #167) — read back via make_chat_handlers
    final_read = handlers["memory_read"]({"key": "k1"})
    assert final_read == "from_batch_handler"


def test_make_chat_handlers_memory_write_real_write(tmp_path: Path) -> None:
    repo = tmp_path
    handlers = make_chat_handlers(str(repo))

    result = handlers["memory_write"]({"key": "batch_key", "value": "batch value"})
    assert result == "Memory written: batch_key"

    store = json.loads(memory_store_path(str(repo)).read_text())
    assert store["batch_key"] == "batch value"
