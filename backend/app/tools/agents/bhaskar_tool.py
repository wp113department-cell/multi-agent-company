"""bhaskar_tool — universal "no existing tool fits" fallback, exposed to
every agent (app/agents/tools.py's READ_ONLY_TOOLS + make_read_only_handlers,
inherited by every *_TOOLS bundle built on top of it — see that module).

When an agent hits a task no available tool covers, it calls this instead
of getting stuck. This handler:

  1. Normalizes (task_description, context) into a stable cache key and
     checks app/fleet/scratchpad.py's bounded, TTL'd cache (sentinel
     epic_id) for a previously-generated script — a cache HIT re-executes
     that cached script in the same hardened sandbox rather than replaying
     it blindly, so a script that has since started failing (e.g. an
     external API changed shape) is caught and triggers regeneration
     instead of silently returning a stale/broken result.
  2. On a cache MISS (or a hit whose replay failed), runs bhaskar_agent
     (app/agents/bhaskar_agent.py) — a small LangGraph sub-agent that
     researches, writes, and tests a one-off script — in a fresh, separate
     OS process (multiprocessing, spawn context), bounded by a real
     wall-clock timeout (settings.bhaskar_tool_timeout_seconds) and a
     bounded retry count (settings.bhaskar_tool_max_retries) — never an
     unbounded loop. Unlike a thread (which Python can never forcibly
     stop), a process that exceeds its deadline is actually terminated —
     see _run_with_process_bound's own docstring for exactly what that
     does and does not guarantee.
  3. On success, caches the generated script (write_entry_with_eviction_sync
     — concurrency-safe bounded-size eviction, see scratchpad.py) and
     returns a structured JSON result.

Never raises to its caller — every failure mode returns
`{"ok": false, "error": "..."}`, matching this codebase's existing
structured-error convention (see tool_enhance.md universal tool contract).
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import os
import queue as _queue_module
import re
from typing import Any

logger = logging.getLogger(__name__)

# Reserved sentinel — never a real epic id (those come from app.db.models
# Epic's own id sequence/uuid scheme). app.fleet.scratchpad.EpicScratchpad's
# epic_id column has no foreign key (plain indexed String(100)), so reusing
# it as a fixed namespace for a cache with no real epic is safe.
_CACHE_EPIC_ID = "__bhaskar_tool__"

BHASKAR_TOOL: dict[str, Any] = {
    "name": "bhaskar_tool",
    "description": (
        "UNIVERSAL FALLBACK — call this ONLY when no other tool available to "
        "you can accomplish the task (e.g. scraping a specific site, a "
        "one-off data transform, or an API integration nothing else covers). "
        "It runs its own small agent that researches, writes, and tests a "
        "one-off Python script to accomplish exactly what you describe, "
        "then returns the result. It is slower and more expensive than a "
        "normal tool call — never use it to avoid using a tool you already "
        "have, and never use it for tasks a normal tool already covers "
        "(reading/writing files, git operations, running tests, etc.). "
        "A true `ok` only means the generated script ran without error, "
        "not that it necessarily accomplished the task correctly — check "
        "the returned output yourself before trusting the result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": (
                    "Exactly what capability/task is needed, described "
                    "precisely enough that someone with no other context "
                    "could implement it."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional: inputs, URLs, sample data, or other details "
                    "the task needs."
                ),
            },
        },
        "required": ["task_description"],
    },
}


def _normalize_task_signature(task_description: str, context: str) -> str:
    """Stable cache key: whitespace/case-normalized so trivially different
    phrasing of the same request still hits the cache, then hashed (the
    scratchpad `key` column is String(200) — a fixed-length hash avoids any
    truncation surprise from a very long task_description)."""
    normalized = re.sub(
        r"\s+",
        " ",
        f"{task_description.strip().lower()}|{context.strip().lower()}",
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "code": "",
        "result_summary": "",
        "tested_output": "",
        "error": error,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _run_in_bounded_process(
    target: Any, payload: Any, timeout: float
) -> dict[str, Any]:
    """Run `target(payload, result_queue)` — a module-level (picklable —
    required by multiprocessing's spawn start method), NOT a lambda/
    closure — in a fresh, separately-killable OS process (spawn context;
    never fork, since this handler runs inside an already multi-threaded,
    async app, and spawn avoids inheriting any of its open connections/
    locks/event-loop state into the child), bounded by a real wall-clock
    timeout.

    Unlike a thread (which Python can never forcibly stop — the previous
    implementation here), a process that exceeds its deadline is actually
    terminated: SIGTERM, then SIGKILL after a grace period if still alive.
    This reliably reclaims the child's own memory/fds immediately.

    A generic primitive (used for the real bhaskar_agent entry point below
    and, in tests, for lightweight test-only targets) so the actual
    subprocess/timeout/kill mechanism can be exercised directly without
    needing to mock across a process boundary — spawn re-imports the
    target module fresh in the child, so a parent-process monkeypatch of
    e.g. run_bhaskar_agent would silently have no effect there; tests
    instead pass in their own real, fast, module-level targets."""
    ctx = multiprocessing.get_context("spawn")
    result_queue: "multiprocessing.Queue[dict[str, Any]]" = ctx.Queue()
    proc = ctx.Process(target=target, args=(payload, result_queue), daemon=True)
    proc.start()
    proc.join(timeout=timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=5)
        result_queue.close()
        return _failure(
            f"bhaskar_agent exceeded its {timeout}s wall-clock bound and was terminated"
        )

    try:
        result: dict[str, Any] = result_queue.get_nowait()
    except _queue_module.Empty:
        result = _failure(
            "bhaskar_agent process exited without returning a result "
            f"(exit code {proc.exitcode})"
        )
    finally:
        result_queue.close()
    return result


def _bhaskar_agent_subprocess_entry(
    payload: tuple[str, str, str, str],
    result_queue: "multiprocessing.Queue[dict[str, Any]]",
) -> None:
    """Module-level (picklable) entry point run in a fresh, separate
    process by _run_with_process_bound, via _run_in_bounded_process.
    os.setsid() makes this its own session/process-group leader (POSIX) —
    harmless if run_bhaskar_agent never spawns a direct child of its own,
    and a real backstop if it ever does beyond app/agents/bhaskar_sandbox.
    py's own sandboxed subprocess calls (which already detach into THEIR
    OWN session — see _run_with_process_bound's docstring for that
    residual edge case)."""
    task_description, context, repo_path, trace_id = payload
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except Exception:
            pass

    from app.agents.bhaskar_agent import run_bhaskar_agent

    try:
        result = run_bhaskar_agent(
            task_description, context, repo_path, trace_id=trace_id
        )
    except Exception as exc:
        result = _failure(f"bhaskar_agent run raised: {exc}")
    try:
        result_queue.put(result)
    except Exception:
        pass


def _run_with_process_bound(
    task_description: str,
    context: str,
    repo_path: str,
    trace_id: str,
    timeout: float,
) -> dict[str, Any]:
    """Residual edge case, disclosed rather than hidden: if the deadline
    lands while this process is itself mid-execution of a sandboxed script
    (app/agents/bhaskar_sandbox.py's run_sandboxed_python, which — on
    POSIX — deliberately puts EACH sandboxed script in its OWN new session
    via start_new_session=True), that grandchild is not reachable through
    this process's own process group and is not directly killed here. It
    is not left unbounded, though: that sandboxed subprocess already
    carries its own kernel-enforced RLIMIT_CPU (set to its own, smaller
    settings.bhaskar_tool_sandbox_script_timeout_seconds), so it
    self-terminates on its own regardless of whether this supervising
    process is still alive."""
    return _run_in_bounded_process(
        _bhaskar_agent_subprocess_entry,
        (task_description, context, repo_path, trace_id),
        timeout,
    )


def bhaskar_tool_handler(
    repo_path: str,
    inp: dict[str, Any],
    *,
    agent_name: str = "unknown",
    trace_id: str = "",
) -> str:
    from app.agents.bhaskar_sandbox import run_sandboxed_python
    from app.config import get_settings
    from app.fleet import scratchpad

    settings = get_settings()
    if not settings.bhaskar_tool_enabled:
        return json.dumps(
            {"ok": False, "error": "bhaskar_tool is disabled (bhaskar_tool_enabled=false)"}
        )

    task_description = str(inp.get("task_description", "")).strip()
    if not task_description:
        return json.dumps({"ok": False, "error": "task_description is required"})
    context = str(inp.get("context", "")).strip()

    signature = _normalize_task_signature(task_description, context)
    sandbox_kwargs: dict[str, Any] = {
        "repo_path": repo_path,
        "timeout": settings.bhaskar_tool_sandbox_script_timeout_seconds,
        "allow_network": settings.bhaskar_tool_sandbox_allow_network,
        "max_memory_mb": settings.bhaskar_tool_sandbox_max_memory_mb,
        "max_output_file_mb": settings.bhaskar_tool_sandbox_max_output_file_mb,
        "max_output_chars": settings.bhaskar_tool_sandbox_max_output_chars,
        "max_total_disk_mb": settings.bhaskar_tool_sandbox_max_total_disk_mb,
        "max_processes": settings.bhaskar_tool_sandbox_max_processes,
    }

    # --- 1. Cache lookup (real expiry: read_entries only returns rows
    # where expires_at > now, so an expired entry is simply invisible here,
    # independent of any sweep). ---
    cached = scratchpad.read_entries_sync(_CACHE_EPIC_ID, key=signature)
    if cached:
        cached_value = cached[0].get("value") or {}
        cached_code = str(cached_value.get("code", ""))
        if cached_code:
            replay = run_sandboxed_python(cached_code, **sandbox_kwargs)
            if replay["success"]:
                return json.dumps(
                    {
                        "ok": True,
                        "source": "cache",
                        "result_summary": cached_value.get("result_summary", ""),
                        "output": replay["output"],
                    }
                )
            logger.info(
                "bhaskar_tool: cached script for signature=%s failed replay "
                "(%s) — regenerating instead of returning a stale result",
                signature[:12],
                replay["output"][:200],
            )

    # --- 2. Generate, bounded by wall-clock timeout + retry cap. ---
    attempts = max(1, settings.bhaskar_tool_max_retries + 1)
    last_error = "no attempt made"
    for attempt in range(1, attempts + 1):
        gen = _run_with_process_bound(
            task_description,
            context,
            repo_path,
            trace_id,
            settings.bhaskar_tool_timeout_seconds,
        )

        if gen.get("ok"):
            scratchpad.write_entry_with_eviction_sync(
                _CACHE_EPIC_ID,
                signature,
                {
                    "code": gen["code"],
                    "result_summary": gen.get("result_summary", ""),
                },
                agent_name,
                max_entries=settings.bhaskar_tool_cache_max_entries,
                ttl_seconds=settings.bhaskar_tool_cache_ttl_seconds,
            )
            return json.dumps(
                {
                    "ok": True,
                    "source": "generated",
                    "result_summary": gen.get("result_summary", ""),
                    "output": gen.get("tested_output", ""),
                }
            )

        last_error = str(gen.get("error", "unknown failure"))
        logger.info(
            "bhaskar_tool: attempt %d/%d failed: %s", attempt, attempts, last_error
        )

    return json.dumps(
        {
            "ok": False,
            "error": f"bhaskar_tool failed after {attempts} attempt(s): {last_error}",
        }
    )
