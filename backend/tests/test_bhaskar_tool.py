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
import os
import pathlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.bhaskar_agent import BhaskarRecursionError, bhaskar_agent_active
from app.agents.bhaskar_sandbox import run_sandboxed_python
from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    CODER_TOOLS,
    READ_ONLY_TOOLS,
    RESEARCH_TOOLS,
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
# Module-level (picklable — required by multiprocessing's spawn start
# method) test targets for _run_in_bounded_process. Must stay at module
# level: a closure/lambda/nested function cannot be pickled to hand off to
# a spawned child process.
# ---------------------------------------------------------------------------


def _hang_and_touch_marker(payload, result_queue) -> None:  # noqa: ANN001
    import time as _time

    _time.sleep(2)
    with open(payload, "w") as f:
        f.write("still alive")
    result_queue.put({"ok": True})


def _hang_forever(payload, result_queue) -> None:  # noqa: ANN001
    import time as _time

    _time.sleep(30)
    result_queue.put({"ok": True})


def _fast_success_target(payload, result_queue) -> None:  # noqa: ANN001
    result_queue.put({"ok": True, "marker": "real-result"})


def _raising_target(payload, result_queue) -> None:  # noqa: ANN001
    raise RuntimeError("deliberate test failure")


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


# Real-import-based versions of these two checks (not a source-text scan)
# live further down: test_real_agent_contract_declares_bhaskar_tool and
# test_real_executive_contract_has_zero_tools_by_design.


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


def _mock_db_for_eviction(existing, live_rows, repo_id=None):
    """Builds a mock AsyncSession whose .execute() calls, in the exact
    order write_entry_with_eviction issues them, return:
    1. the advisory-lock select (result unused)
    2. the existing-row-by-key lookup (scalar_one_or_none -> `existing`)
    3. (only when existing is None) the live-rows-for-eviction select
       (.scalars().all() -> `live_rows`)
    4. (only when existing is None) T2-B6 (2026-09-22, GRIDIRON_PARTIAL
       #383)'s opportunistic Epic.repo_id lookup (scalar_one_or_none ->
       `repo_id`)
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
        results.append(
            MagicMock(scalar_one_or_none=MagicMock(return_value=repo_id))
        )
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
        "app.tools.agents.bhaskar_tool._run_with_process_bound", fail_if_called
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
        "app.tools.agents.bhaskar_tool._run_with_process_bound",
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

    monkeypatch.setattr(
        "app.tools.agents.bhaskar_tool._run_with_process_bound", always_fail
    )

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
        "app.tools.agents.bhaskar_tool._run_with_process_bound",
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
# Wall-clock timeout — real process-level cancellation (not just "the
# caller stops waiting" — the underlying process must actually be killed)
# ---------------------------------------------------------------------------


def test_handler_bounds_wall_clock_on_a_hanging_generation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Handler-level: bhaskar_tool_handler treats a timeout-shaped failure
    from _run_with_process_bound like any other bounded-attempt failure
    (retry-eligible, never raises). The real subprocess spawn/kill
    mechanism itself is exercised directly below, against
    _run_in_bounded_process — a parent-process monkeypatch of
    run_bhaskar_agent has no effect on a spawned child (see
    _run_in_bounded_process's own docstring), so it cannot be used to
    simulate a hang at this layer."""
    monkeypatch.setattr(get_settings(), "bhaskar_tool_max_retries", 0)
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync", lambda epic_id, key=None: []
    )
    monkeypatch.setattr(
        "app.tools.agents.bhaskar_tool._run_with_process_bound",
        lambda *a, **kw: {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": "bhaskar_agent exceeded its 0.3s wall-clock bound and was terminated",
            "tokens_in": 0,
            "tokens_out": 0,
        },
    )

    result = json.loads(
        bhaskar_tool_handler(str(tmp_path), {"task_description": "hangs forever"})
    )
    assert result["ok"] is False
    assert "terminated" in result["error"]


def test_run_in_bounded_process_actually_terminates_a_real_hang(
    tmp_path: pathlib.Path,
) -> None:
    """Real subprocess: spawns an actual process that sleeps for 30s,
    bounded to a 0.5s deadline. Proves genuine termination, not just a
    prompt return while the child lingers — the child is supposed to
    write a marker file 2s after waking from sleep; if it were merely
    orphaned (not really killed) rather than terminated, the marker would
    still appear after we wait past that point."""
    from app.tools.agents.bhaskar_tool import _run_in_bounded_process

    marker = str(tmp_path / "still_alive_marker.txt")
    start = time.monotonic()
    result = _run_in_bounded_process(_hang_and_touch_marker, marker, 0.5)
    elapsed = time.monotonic() - start

    assert result["ok"] is False
    assert "terminated" in result["error"]
    assert elapsed < 5.0  # bounded near the 0.5s deadline + kill grace period

    time.sleep(3.0)  # well past when an orphaned (not killed) process would write it
    assert not pathlib.Path(marker).exists()


def test_run_in_bounded_process_bounded_across_repeated_calls() -> None:
    """Repeated timeout behavior — each call is independently bounded, no
    growth/leak across consecutive hangs."""
    from app.tools.agents.bhaskar_tool import _run_in_bounded_process

    for _ in range(3):
        start = time.monotonic()
        result = _run_in_bounded_process(_hang_forever, None, 0.3)
        elapsed = time.monotonic() - start
        assert result["ok"] is False
        assert elapsed < 5.0


def test_run_in_bounded_process_returns_real_result_when_fast() -> None:
    from app.tools.agents.bhaskar_tool import _run_in_bounded_process

    result = _run_in_bounded_process(_fast_success_target, None, 10)
    assert result == {"ok": True, "marker": "real-result"}


def test_run_in_bounded_process_handles_a_raising_target() -> None:
    from app.tools.agents.bhaskar_tool import _run_in_bounded_process

    result = _run_in_bounded_process(_raising_target, None, 10)
    assert result["ok"] is False
    assert "exit code" in result["error"] or "raised" in result["error"]


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


# ---------------------------------------------------------------------------
# Sandbox — filesystem guard: absolute paths, traversal, symlink escape
# ---------------------------------------------------------------------------


def test_sandbox_blocks_absolute_path_read() -> None:
    result = run_sandboxed_python(
        "open('/etc/passwd').read()\nprint('READ_OK')", timeout=10
    )
    assert result["success"] is False
    assert "read access" in result["output"] and "blocked" in result["output"]
    assert "READ_OK" not in result["output"]


def test_sandbox_blocks_absolute_path_write(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "escape.txt"
    code = f"open({str(target)!r}, 'w').write('pwned')\nprint('WRITE_OK')"
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is False
    assert "write access" in result["output"] and "blocked" in result["output"]
    assert not target.exists()


def test_sandbox_blocks_relative_path_traversal() -> None:
    code = (
        "open('../../../../etc/hostname').read()\n"
        "print('READ_OK')"
    )
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is False
    assert "blocked" in result["output"]
    assert "READ_OK" not in result["output"]


def test_sandbox_blocks_symlink_creation() -> None:
    code = (
        "import os\n"
        "os.symlink('/etc/passwd', 'evil_link')\n"
        "print('SYMLINK_CREATED')\n"
        "print(open('evil_link').read())\n"
    )
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is False
    assert "creating symlinks is blocked" in result["output"]
    assert "SYMLINK_CREATED" not in result["output"]


def test_sandbox_blocks_reading_through_a_preexisting_symlink(
    tmp_path: pathlib.Path,
) -> None:
    """Belt-and-suspenders: even if a symlink somehow existed (os.symlink
    itself is blocked above — this proves the SECOND, independent layer:
    open()'s own realpath-based validation resolves symlinks before
    checking containment, so a symlink pointing outside the sandbox is
    caught even if created by some other means)."""
    from app.agents import bhaskar_sandbox as sandbox_module

    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    link_name = "preexisting_link"

    orig_build_script = sandbox_module._build_script

    def build_with_preexisting_symlink(code, sandbox_dir, allow_network):
        os.symlink(str(secret), os.path.join(sandbox_dir, link_name))
        return orig_build_script(code, sandbox_dir, allow_network)

    with patch.object(
        sandbox_module, "_build_script", build_with_preexisting_symlink
    ):
        result = run_sandboxed_python(
            f"print(open({link_name!r}).read())", timeout=10
        )
    assert result["success"] is False
    assert "blocked" in result["output"]
    assert "top secret" not in result["output"]


def test_sandbox_normal_relative_io_still_works_under_fs_guard() -> None:
    code = (
        "with open('local.txt', 'w') as f:\n"
        "    f.write('hello')\n"
        "print(open('local.txt').read())\n"
    )
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is True
    assert "hello" in result["output"]


def test_sandbox_real_imports_still_work_under_fs_guard() -> None:
    """The filesystem guard allowlists read-only access to the Python
    installation itself (sys.prefix/base_prefix/exec_prefix) — without
    this, `import` would break entirely since the import machinery reads
    stdlib/site-packages files via open()."""
    code = (
        "import json, hashlib, urllib.request\n"
        "print('ok:', hashlib.sha256(b'x').hexdigest()[:8])\n"
    )
    result = run_sandboxed_python(code, timeout=10)
    assert result["success"] is True
    assert "ok:" in result["output"]


# ---------------------------------------------------------------------------
# Sandbox — IPv4 + IPv6 SSRF, including the IPv4-mapped-IPv6 bypass class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",  # IPv4 loopback
        "169.254.169.254",  # IPv4 cloud metadata
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 unique-local (RFC 4193)
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 loopback — the classic bypass
    ],
)
def test_sandbox_blocks_ssrf_targets_v4_and_v6(host: str) -> None:
    code = (
        "import socket\n"
        "try:\n"
        f"    socket.create_connection(({host!r}, 80), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
        "except Exception as e:\n"
        "    print('OTHER:' + repr(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=True)
    assert "BLOCKED:" in result["output"]
    assert "CONNECTED" not in result["output"]


def test_sandbox_pinned_connect_does_not_break_real_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for a real bug found while hardening this guard: pinning
    the validated IP for the actual TCP connect (to close the DNS-
    rebinding/TOCTOU gap) must not break the higher-level HTTP/TLS layer,
    which still needs the ORIGINAL hostname for its Host header and SNI.
    Requires real network access to a public host — skipped if unavailable
    rather than failing the suite on a sandboxed/offline CI runner."""
    code = (
        "import urllib.request\n"
        "try:\n"
        "    with urllib.request.urlopen('https://example.com', timeout=8) as r:\n"
        "        print('HTTPS_OK', r.status)\n"
        "except Exception as e:\n"
        "    print('HTTPS_FAILED:' + repr(e))\n"
    )
    result = run_sandboxed_python(code, timeout=15, allow_network=True)
    if "HTTPS_FAILED" in result["output"]:
        pytest.skip(f"no real network access in this environment: {result['output']}")
    assert "HTTPS_OK 200" in result["output"]


def test_sandbox_connect_ex_is_also_guarded() -> None:
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "try:\n"
        "    s.connect_ex(('127.0.0.1', 80))\n"
        "    print('NOT_BLOCKED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=True)
    assert "BLOCKED:" in result["output"]


def test_sandbox_af_unix_connections_are_blocked() -> None:
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "try:\n"
        "    s.connect('/var/run/docker.sock')\n"
        "    print('NOT_BLOCKED')\n"
        "except PermissionError as e:\n"
        "    print('BLOCKED:' + str(e))\n"
        "except Exception as e:\n"
        "    print('OTHER:' + repr(e))\n"
    )
    result = run_sandboxed_python(code, timeout=10, allow_network=True)
    assert "BLOCKED:" in result["output"]


# ---------------------------------------------------------------------------
# Sandbox — total resource protection: disk quota (beyond single-file
# RLIMIT_FSIZE) and process-count (fork-bomb) limits
# ---------------------------------------------------------------------------


def test_sandbox_enforces_total_disk_quota_across_many_small_files() -> None:
    """RLIMIT_FSIZE only bounds any ONE file's size — a script writing many
    small files under that per-file cap could otherwise consume unbounded
    total disk. The watchdog in run_sandboxed_python polls total sandbox
    directory size independently of RLIMIT_FSIZE."""
    code = (
        "import time\n"
        "i = 0\n"
        "while True:\n"
        "    with open(f'file_{i}.bin', 'wb') as f:\n"
        "        f.write(b'0' * (200 * 1024))\n"  # 200KB — well under any per-file cap
        "    i += 1\n"
        "    time.sleep(0.05)\n"
    )
    start = time.monotonic()
    result = run_sandboxed_python(
        code, timeout=30, max_output_file_mb=50, max_total_disk_mb=2
    )
    elapsed = time.monotonic() - start
    assert result["success"] is False
    assert "disk quota" in result["output"]
    assert elapsed < 10.0  # caught by the watchdog, not the 30s timeout


def test_sandbox_enforces_max_process_count() -> None:
    code = (
        "import subprocess, sys\n"
        "procs = []\n"
        "spawned = 0\n"
        "try:\n"
        "    for i in range(60):\n"
        "        procs.append(subprocess.Popen(\n"
        "            [sys.executable, '-c', 'import time; time.sleep(3)']\n"
        "        ))\n"
        "        spawned += 1\n"
        "    print('SPAWNED_ALL', spawned)\n"
        "except OSError as e:\n"
        "    print('BLOCKED_AT', spawned, repr(e))\n"
        "finally:\n"
        "    for p in procs:\n"
        "        try:\n"
        "            p.kill()\n"
        "        except Exception:\n"
        "            pass\n"
    )
    result = run_sandboxed_python(code, timeout=20, max_processes=5)
    assert "BLOCKED_AT" in result["output"]
    assert "SPAWNED_ALL" not in result["output"]


def test_sandbox_repeated_timeouts_stay_bounded() -> None:
    """Repeated timeout behavior — no growth/leak across consecutive
    real sandboxed hangs."""
    for _ in range(3):
        start = time.monotonic()
        result = run_sandboxed_python(
            "import time\ntime.sleep(30)", timeout=1
        )
        elapsed = time.monotonic() - start
        assert result["success"] is False
        assert elapsed < 10.0


# ---------------------------------------------------------------------------
# Final verification — the exact submitted code is re-executed; a script
# that fails at runtime is genuinely rejected, not trusted on the agent's
# say-so. NOT a claim of semantic/task-correctness verification (see
# bhaskar_agent.py's own docstring) — only that it actually runs.
# ---------------------------------------------------------------------------


def test_run_bhaskar_agent_rejects_a_submission_that_fails_final_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import bhaskar_agent as bhaskar_agent_module

    def fake_run_agent_graph(*, tool_handlers, **kw):
        tool_handlers["submit_generated_tool"](
            {"code": "raise RuntimeError('broken')", "result_summary": "claims success"}
        )
        return {"tokens_in": 10, "tokens_out": 10}

    monkeypatch.setattr(bhaskar_agent_module, "run_agent_graph", fake_run_agent_graph)

    result = bhaskar_agent_module.run_bhaskar_agent("task", "", "/tmp")
    assert result["ok"] is False
    assert result["code"] == "raise RuntimeError('broken')"
    assert "final verification" in result["error"]


def test_run_bhaskar_agent_accepts_a_submission_that_passes_final_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import bhaskar_agent as bhaskar_agent_module

    def fake_run_agent_graph(*, tool_handlers, **kw):
        tool_handlers["submit_generated_tool"](
            {"code": "print('42')", "result_summary": "answer"}
        )
        return {"tokens_in": 3, "tokens_out": 3}

    monkeypatch.setattr(bhaskar_agent_module, "run_agent_graph", fake_run_agent_graph)

    result = bhaskar_agent_module.run_bhaskar_agent("task", "", "/tmp")
    assert result["ok"] is True
    assert "42" in result["tested_output"]


def test_run_bhaskar_agent_fails_when_nothing_was_ever_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import bhaskar_agent as bhaskar_agent_module

    monkeypatch.setattr(
        bhaskar_agent_module,
        "run_agent_graph",
        lambda **kw: {"tokens_in": 1, "tokens_out": 1},
    )

    result = bhaskar_agent_module.run_bhaskar_agent("task", "", "/tmp")
    assert result["ok"] is False
    assert "did not submit" in result["error"]


# ---------------------------------------------------------------------------
# Cache safety — a cache-hit replay must go through the SAME hardened
# sandbox as fresh generation, never a shortcut that bypasses the guards
# ---------------------------------------------------------------------------


def test_handler_cache_replay_enforces_the_real_sandbox_guards(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UNMOCKED run_sandboxed_python: a cached script that tries to reach
    a private IP is genuinely blocked on replay (not bypassed), which —
    per the stale-cache-falls-through design — triggers regeneration."""
    monkeypatch.setattr(
        "app.fleet.scratchpad.read_entries_sync",
        lambda epic_id, key=None: [
            {
                "value": {
                    "code": (
                        "import socket\n"
                        "socket.create_connection(('127.0.0.1', 80), timeout=2)\n"
                        "print('should not reach here')"
                    )
                }
            }
        ],
    )
    monkeypatch.setattr(
        "app.fleet.scratchpad.write_entry_with_eviction_sync", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        "app.tools.agents.bhaskar_tool._run_with_process_bound",
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
        bhaskar_tool_handler(str(tmp_path), {"task_description": "cached but blocked"})
    )
    assert result["ok"] is True
    assert result["source"] == "generated"  # cache replay was blocked, not bypassed


# ---------------------------------------------------------------------------
# Agent-contract rollout — validated against the REAL live AGENT_CONTRACT
# (imported), not just source text
# ---------------------------------------------------------------------------


def _candidate_agent_module_names() -> list[str]:
    """Every app/agents/*.py module with a REAL AGENT_CONTRACT dict
    (imported, not text-matched — catches a corrupted rollout edit landing
    in the wrong list, which a text search for the substring "bhaskar_tool"
    anywhere in the file cannot: this caught a real bug, app/agents/
    manager.py's rollout codemod having landed "bhaskar_tool" in
    input_types instead of the real, empty allowed_tools) that isn't
    itself zero-tool-by-design (allowed_tools == []) and isn't
    bhaskar_agent.py (the internal engine bhaskar_tool itself runs on —
    see that module's own docstring for why it's not a real dispatchable
    agent)."""
    import importlib

    names = []
    for f in sorted(AGENTS_DIR.glob("*.py")):
        if f.name in {"__init__.py", "bhaskar_agent.py"}:
            continue
        try:
            mod = importlib.import_module(f"app.agents.{f.stem}")
        except Exception:
            continue
        contract = getattr(mod, "AGENT_CONTRACT", None)
        if not isinstance(contract, dict) or "allowed_tools" not in contract:
            continue
        if contract["allowed_tools"] == []:
            continue
        names.append(f.stem)
    return names


@pytest.mark.parametrize("module_name", _candidate_agent_module_names())
def test_real_agent_contract_declares_bhaskar_tool(module_name: str) -> None:
    import importlib

    mod = importlib.import_module(f"app.agents.{module_name}")
    contract = getattr(mod, "AGENT_CONTRACT", None)
    assert contract is not None, f"{module_name} has no real AGENT_CONTRACT"
    assert "bhaskar_tool" in contract["allowed_tools"], (
        f"{module_name}: real AGENT_CONTRACT['allowed_tools'] is missing "
        f"'bhaskar_tool'"
    )


@pytest.mark.parametrize("module_name", ["executive", "manager"])
def test_real_zero_tool_contracts_are_untouched_by_design(module_name: str) -> None:
    """executive (pure text generation) and manager (pure orchestration —
    dispatches other agents, never calls a tool itself) are the two real,
    deliberately zero-tool agents; bhaskar_tool must never be force-added
    to either, and no other AGENT_CONTRACT list (input_types, etc.) should
    have been corrupted by the rollout codemod either — the exact class of
    bug this test's sibling above caught for manager.py."""
    import importlib

    mod = importlib.import_module(f"app.agents.{module_name}")
    contract = mod.AGENT_CONTRACT
    assert contract["allowed_tools"] == []
    for key, val in contract.items():
        if isinstance(val, list):
            assert "bhaskar_tool" not in val, f"{module_name}.{key}"
