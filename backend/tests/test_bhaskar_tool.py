"""bhaskar_tool — universal "no existing tool fits" fallback.

Covers: schema/rollout registration (every agent's AGENT_CONTRACT +
*_TOOLS schema bundle actually includes it, chat_agent.py's own separate
dispatch loop reaches it — the exact gap class tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131 all had to fix),
the cache (hit/replay/stale-refresh/bounded eviction/TTL), bounded
retry/timeout in bhaskar_tool_handler, the recursion guard, and the
hardened sandbox's real, kernel-enforced isolation (cwd, environment,
network guard, resource limits, timeout).
"""

from __future__ import annotations

import json
import pathlib
import socket
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.bhaskar_agent import BhaskarRecursionError, bhaskar_agent_active
from app.agents.bhaskar_sandbox import run_sandboxed_python
from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    CODER_TOOLS,
    READ_ONLY_TOOLS,
    RESEARCH_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.config import get_settings
from app.fleet import scratchpad
from app.fleet.tool_manifest import TOOL_MANIFEST, is_high_risk
from app.models.chat import ChatSession
from app.tools.agents.bhaskar_tool import (
    BHASKAR_TOOL,
    _normalize_task_signature,
    bhaskar_tool_handler,
)

AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "agents"


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_bhaskar_tool", repo_path=repo)
    return ChatAgent(session)


# ---------------------------------------------------------------------------
# Schema + rollout registration
# ---------------------------------------------------------------------------


def test_bhaskar_tool_schema() -> None:
    assert BHASKAR_TOOL["name"] == "bhaskar_tool"
    assert BHASKAR_TOOL["input_schema"]["required"] == ["task_description"]  # type: ignore[index]


@pytest.mark.parametrize(
    "bundle_name,bundle",
    [
        ("READ_ONLY_TOOLS", READ_ONLY_TOOLS),
        ("CODER_TOOLS", CODER_TOOLS),
        ("CHAT_TOOLS", CHAT_TOOLS),
        ("RESEARCH_TOOLS", RESEARCH_TOOLS),
    ],
)
def test_bhaskar_tool_appears_exactly_once_in_bundle(
    bundle_name: str, bundle: list
) -> None:
    names = [t["name"] for t in bundle]
    assert names.count("bhaskar_tool") == 1, bundle_name


def test_read_only_tools_append_did_not_reorder_existing_entries() -> None:
    # RESEARCH_TOOLS/FLEET_APPLY_TOOLS index into READ_ONLY_TOOLS
    # positionally — appending bhaskar_tool must never shift index 0.
    assert READ_ONLY_TOOLS[0]["name"] == "read_file"
    assert READ_ONLY_TOOLS[-1]["name"] == "bhaskar_tool"


def test_make_read_only_handlers_wires_bhaskar_tool(tmp_path: pathlib.Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    assert "bhaskar_tool" in handlers
    assert callable(handlers["bhaskar_tool"])


def test_tool_manifest_entry_exists_and_is_high_risk() -> None:
    assert "bhaskar_tool" in TOOL_MANIFEST
    assert is_high_risk("bhaskar_tool")


def test_every_agent_contract_declares_bhaskar_tool() -> None:
    """Static source scan mirroring the rollout codemod's own verification
    — every AGENT_CONTRACT["allowed_tools"] list must declare
    "bhaskar_tool", except executive.py's deliberately tool-less
    "pure text generation" agent."""
    missing = []
    for f in sorted(AGENTS_DIR.glob("*.py")):
        if f.name == "executive.py":
            continue
        text = f.read_text()
        if "AGENT_CONTRACT" not in text or '"allowed_tools"' not in text:
            continue
        if '"bhaskar_tool"' not in text:
            missing.append(f.name)
    assert missing == []


def test_executive_agent_deliberately_excluded() -> None:
    text = (AGENTS_DIR / "executive.py").read_text()
    assert '"allowed_tools": [],' in text
    assert '"bhaskar_tool"' not in text


# ---------------------------------------------------------------------------
# chat_agent.py real dispatch reachability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatch_reaches_bhaskar_tool(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.agents.chat_agent.bhaskar_tool_handler",
        lambda repo, inp, **kw: json.dumps({"ok": True, "source": "generated"}),
    )
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool(
        "bhaskar_tool", {"task_description": "do something novel"}
    )
    assert "Unknown tool" not in result
    assert json.loads(result)["ok"] is True


@pytest.mark.asyncio
async def test_chat_agent_dispatch_passes_trace_id_and_agent_name(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_handler(repo, inp, **kw):
        captured.update(kw)
        return json.dumps({"ok": True})

    monkeypatch.setattr("app.agents.chat_agent.bhaskar_tool_handler", fake_handler)
    agent = _agent(str(tmp_path))
    await agent._execute_tool("bhaskar_tool", {"task_description": "x"})
    assert captured["agent_name"] == "chat_agent"
    assert "trace_id" in captured


# ---------------------------------------------------------------------------
# Cache key normalization
# ---------------------------------------------------------------------------


def test_signature_stable_across_whitespace_and_case() -> None:
    a = _normalize_task_signature("Fetch the  weather", "city=NYC")
    b = _normalize_task_signature("fetch the weather", "city=nyc")
    assert a == b


def test_signature_differs_for_different_tasks() -> None:
    a = _normalize_task_signature("fetch weather", "")
    b = _normalize_task_signature("fetch news", "")
    assert a != b


# ---------------------------------------------------------------------------
# scratchpad.write_entry_with_eviction — concurrency-safe bounded cache
# ---------------------------------------------------------------------------


def _mock_db_for_eviction(existing, live_rows):
    """Builds a mock AsyncSession whose .execute() calls, in the exact
    order write_entry_with_eviction issues them, return:
    1. the advisory-lock select (result unused)
    2. the existing-row-by-key lookup (scalar_one_or_none -> `existing`)
    3. (only when existing is None) the live-rows-for-eviction select
       (.scalars().all() -> `live_rows`)
    """
    db = AsyncMock()
    results = [MagicMock()]  # advisory lock select — value unused
    results.append(
        MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
    )
    if existing is None:
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=live_rows)
        results.append(MagicMock(scalars=MagicMock(return_value=scalars_result)))
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_write_entry_with_eviction_inserts_under_the_limit() -> None:
    db = _mock_db_for_eviction(existing=None, live_rows=[])
    ok = await scratchpad.write_entry_with_eviction(
        "__bhaskar_tool__",
        "sig-1",
        {"code": "print(1)"},
        "coder",
        db,
        max_entries=4,
        ttl_seconds=1200,
    )
    assert ok is True
    assert db.add.called
    assert not db.delete.called


@pytest.mark.asyncio
async def test_write_entry_with_eviction_updates_existing_key_in_place() -> None:
    existing_row = MagicMock()
    db = _mock_db_for_eviction(existing=existing_row, live_rows=[])
    ok = await scratchpad.write_entry_with_eviction(
        "__bhaskar_tool__",
        "sig-1",
        {"code": "print(2)"},
        "coder",
        db,
        max_entries=4,
        ttl_seconds=1200,
    )
    assert ok is True
    assert existing_row.value == {"code": "print(2)"}
    assert not db.add.called
    assert not db.delete.called


@pytest.mark.asyncio
async def test_write_entry_with_eviction_evicts_oldest_when_at_capacity() -> None:
    oldest = MagicMock(name="oldest")
    newer = MagicMock(name="newer")
    # read_entries-equivalent ordering is created_at ASC, so oldest is first.
    db = _mock_db_for_eviction(existing=None, live_rows=[oldest, newer, MagicMock(), MagicMock()])
    ok = await scratchpad.write_entry_with_eviction(
        "__bhaskar_tool__",
        "sig-new",
        {"code": "print(3)"},
        "coder",
        db,
        max_entries=4,
        ttl_seconds=1200,
    )
    assert ok is True
    db.delete.assert_awaited_once_with(oldest)
    assert db.add.called


@pytest.mark.asyncio
async def test_write_entry_with_eviction_never_raises_on_db_failure() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    db.rollback = AsyncMock()
    ok = await scratchpad.write_entry_with_eviction(
        "__bhaskar_tool__", "sig", {}, "coder", db, max_entries=4, ttl_seconds=1200
    )
    assert ok is False
    assert db.rollback.called


@pytest.mark.asyncio
async def test_delete_entry_returns_false_when_nothing_matched() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    db.commit = AsyncMock()
    ok = await scratchpad.delete_entry("epic", "key", db)
    assert ok is False


@pytest.mark.asyncio
async def test_delete_entry_returns_true_when_a_row_was_deleted() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    db.commit = AsyncMock()
    ok = await scratchpad.delete_entry("epic", "key", db)
    assert ok is True


# ---------------------------------------------------------------------------
# bhaskar_tool_handler orchestration — disabled/validation/cache/retry
# ---------------------------------------------------------------------------


def test_handler_refuses_when_disabled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "bhaskar_tool_enabled", False)
    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "x"})
    )
    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_handler_requires_task_description(tmp_path: pathlib.Path) -> None:
    result = json.loads(bhaskar_tool_handler(str(tmp_path), {}))
    assert result["ok"] is False
    assert "task_description" in result["error"]


def test_handler_cache_hit_replays_without_regenerating(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync",
        lambda epic_id, key=None: [
            {"value": {"code": "print('cached')", "result_summary": "s"}}
        ],
    )
    monkeypatch.setattr(
        "app.agents.bhaskar_sandbox.run_sandboxed_python",
        lambda code, **kw: {"success": True, "output": "cached", "returncode": 0},
    )

    called = {"n": 0}

    def fail_if_called(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not regenerate on a cache hit")

    monkeypatch.setattr(
        "app.agents.bhaskar_agent.run_bhaskar_agent", fail_if_called
    )

    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "cached task"})
    )
    assert result["ok"] is True
    assert result["source"] == "cache"
    assert called["n"] == 0


def test_handler_stale_cache_falls_through_to_regeneration(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync",
        lambda epic_id, key=None: [{"value": {"code": "raise SystemExit(1)"}}],
    )
    monkeypatch.setattr(
        "app.agents.bhaskar_sandbox.run_sandboxed_python",
        lambda code, **kw: {"success": False, "output": "boom", "returncode": 1},
    )
    monkeypatch.setattr(
        "app.fleet.scratchpad.write_entry_with_eviction_sync",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        "app.agents.bhaskar_agent.run_bhaskar_agent",
        lambda *a, **kw: {
            "ok": True,
            "code": "print('fresh')",
            "result_summary": "fresh",
            "tested_output": "fresh",
            "error": "",
            "tokens_in": 1,
            "tokens_out": 1,
        },
    )

    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "stale task"})
    )
    assert result["ok"] is True
    assert result["source"] == "generated"


def test_handler_retries_bounded_then_reports_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "bhaskar_tool_max_retries", 2)
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync", lambda epic_id, key=None: []
    )
    calls = {"n": 0}

    def always_fail(*a, **kw):
        calls["n"] += 1
        return {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": "generation failed",
            "tokens_in": 0,
            "tokens_out": 0,
        }

    monkeypatch.setattr("app.agents.bhaskar_agent.run_bhaskar_agent", always_fail)

    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "always fails"})
    )
    assert result["ok"] is False
    assert calls["n"] == 3  # 1 initial attempt + 2 retries, never unbounded


def test_handler_caches_on_successful_generation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync", lambda epic_id, key=None: []
    )
    monkeypatch.setattr(
        "app.agents.bhaskar_agent.run_bhaskar_agent",
        lambda *a, **kw: {
            "ok": True,
            "code": "print('x')",
            "result_summary": "s",
            "tested_output": "x",
            "error": "",
            "tokens_in": 5,
            "tokens_out": 5,
        },
    )
    cache_calls = []
    monkeypatch.setattr(
        "app.fleet.scratchpad.write_entry_with_eviction_sync",
        lambda *a, **kw: cache_calls.append((a, kw)) or True,
    )

    result = json.loads(
        bhaskar_tool_handler(
            str(tmp_path), {"task_description": "new task"}, agent_name="coder"
        )
    )
    assert result["ok"] is True
    assert len(cache_calls) == 1
    args, kwargs = cache_calls[0]
    assert args[0] == "__bhaskar_tool__"
    assert kwargs["max_entries"] == get_settings().bhaskar_tool_cache_max_entries


# ---------------------------------------------------------------------------
# Wall-clock timeout — must return promptly, not block for the full hang
# ---------------------------------------------------------------------------


def test_handler_bounds_wall_clock_on_a_hanging_generation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "bhaskar_tool_timeout_seconds", 0.3)
    monkeypatch.setattr(get_settings(), "bhaskar_tool_max_retries", 0)
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync", lambda epic_id, key=None: []
    )

    def hang(*a, **kw):
        time.sleep(5)
        return {"ok": True, "code": "x", "result_summary": "", "tested_output": ""}

    monkeypatch.setattr("app.agents.bhaskar_agent.run_bhaskar_agent", hang)

    start = time.monotonic()
    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "hangs forever"})
    )
    elapsed = time.monotonic() - start

    assert result["ok"] is False
    assert elapsed < 2.0  # bounded near the 0.3s deadline, not the 5s hang


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------


def test_run_bhaskar_agent_refuses_reentry() -> None:
    from app.agents.bhaskar_agent import run_bhaskar_agent

    token = bhaskar_agent_active.set(True)
    try:
        with pytest.raises(BhaskarRecursionError):
            run_bhaskar_agent("task", "", "/tmp")
    finally:
        bhaskar_agent_active.reset(token)


def test_bhaskar_agent_tool_list_excludes_bhaskar_tool() -> None:
    from app.agents.bhaskar_agent import (
        SANDBOXED_RUN_SCRIPT_TOOL,
        SUBMIT_GENERATED_TOOL,
    )
    from app.tools.integrations.web_search import WEB_SEARCH_TOOL

    names = {
        WEB_SEARCH_TOOL["name"],
        SANDBOXED_RUN_SCRIPT_TOOL["name"],
        SUBMIT_GENERATED_TOOL["name"],
    }
    assert "bhaskar_tool" not in names


# ---------------------------------------------------------------------------
# Sandbox — real, kernel-enforced isolation (no mocks: run_sandboxed_python
# executes a real subprocess)
# ---------------------------------------------------------------------------


def test_sandbox_runs_a_real_script_and_captures_output() -> None:
    result = run_sandboxed_python("print('hello from sandbox')", timeout=10)
    assert result["success"] is True
    assert "hello from sandbox" in result["output"]


def test_sandbox_cwd_is_isolated_not_the_real_repo(tmp_path: pathlib.Path) -> None:
    marker = tmp_path / "should_not_exist.txt"
    code = "open('relative_write.txt', 'w').write('x')\nprint('done')"
    result = run_sandboxed_python(code, repo_path=str(tmp_path), timeout=10)
    assert result["success"] is True
    assert not (tmp_path / "relative_write.txt").exists()
    assert not marker.exists()


def test_sandbox_environment_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHASKAR_TEST_SECRET", "super-secret-value")
    code = (
        "import os\n"
        "print('SECRET_PRESENT=' + str('BHASKAR_TEST_SECRET' in os.environ))\n"
        "print('PATH_PRESENT=' + str('PATH' in os.environ))\n"
    )
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is True
    assert "SECRET_PRESENT=False" in result["output"]
    assert "PATH_PRESENT=True" in result["output"]


def test_sandbox_blocks_network_entirely_when_disabled() -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('example.com', 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=False)
    assert "BLOCKED:" in result["output"]
    assert "CONNECTED" not in result["output"]


def test_sandbox_blocks_private_ip_even_when_network_allowed() -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
        "except Exception as e:\n"
        "    print('OTHER:' + str(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=True)
    assert "BLOCKED:" in result["output"]
    assert "CONNECTED" not in result["output"]


def test_sandbox_blocks_cloud_metadata_endpoint() -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('169.254.169.254', 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
        "except Exception as e:\n"
        "    print('OTHER:' + str(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=True)
    assert "BLOCKED:" in result["output"]


def test_sandbox_enforces_wall_clock_timeout() -> None:
    start = time.monotonic()
    result = run_sandboxed_python("import time\ntime.sleep(30)", timeout=1)
    elapsed = time.monotonic() - start
    assert result["success"] is False
    assert "timed out" in result["output"]
    assert elapsed < 10.0


@pytest.mark.skipif(
    not hasattr(__import__("sys"), "platform") or __import__("sys").platform == "win32",
    reason="resource.RLIMIT_FSIZE is POSIX-only",
)
def test_sandbox_enforces_max_output_file_size() -> None:
    code = (
        "with open('big.bin', 'wb') as f:\n"
        "    f.write(b'0' * (20 * 1024 * 1024))\n"  # 20MB, over the 1MB test cap
        "print('wrote it')\n"
    )
    result = run_sandboxed_python(code, timeout=10, max_output_file_mb=1)
    assert result["success"] is False


def test_sandbox_output_is_truncated_to_configured_cap() -> None:
    code = "print('x' * 20000)"
    result = run_sandboxed_python(code, timeout=10, max_output_chars=500)
    assert len(result["output"]) <= 500


def test_sandbox_never_raises_on_bad_code() -> None:
    result = run_sandboxed_python("this is not ) valid python (((", timeout=10)
    assert result["success"] is False
    assert result["returncode"] not in (0, None) or "SyntaxError" in result["output"]


def test_sandbox_prefers_repo_venv_python_when_present(tmp_path: pathlib.Path) -> None:
    from app.agents.bhaskar_sandbox import _resolve_python_executable

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_python = venv_bin / "python3"
    fake_python.write_text("#!/bin/sh\n")
    fake_python.chmod(0o755)

    resolved = _resolve_python_executable(str(tmp_path))
    assert resolved == str(fake_python)


def test_sandbox_falls_back_to_current_interpreter_without_venv(
    tmp_path: pathlib.Path,
) -> None:
    import sys

    from app.agents.bhaskar_sandbox import _resolve_python_executable

    resolved = _resolve_python_executable(str(tmp_path))
    assert resolved == sys.executable
