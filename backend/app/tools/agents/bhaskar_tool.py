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
     researches, writes, and tests a one-off script — bounded by both a
     real wall-clock timeout (settings.bhaskar_tool_timeout_seconds, via a
     ThreadPoolExecutor + Future.result(timeout=...), which — unlike
     asyncio.wait_for over asyncio.to_thread — actually returns to the
     caller at the deadline regardless of caller context) and a bounded
     retry count (settings.bhaskar_tool_max_retries) — never an unbounded
     loop.
  3. On success, caches the generated script (write_entry_with_eviction_sync
     — concurrency-safe bounded-size eviction, see scratchpad.py) and
     returns a structured JSON result.

Never raises to its caller — every failure mode returns
`{"ok": false, "error": "..."}`, matching this codebase's existing
structured-error convention (see tool_enhance.md universal tool contract).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
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
        "(reading/writing files, git operations, running tests, etc.)."
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


def _run_with_wallclock_bound(
    fn: Any, timeout: float
) -> dict[str, Any]:
    """Run `fn()` (a zero-arg callable) bounded by a real wall-clock
    timeout. Uses a ThreadPoolExecutor + Future.result(timeout=...) rather
    than asyncio.wait_for: this handler is itself synchronous (matching
    every other *_handler in this codebase) and may be invoked from either
    a sync dispatch path or via asyncio.to_thread by an async caller — a
    plain Future.result(timeout=...) enforces the deadline correctly
    either way, without depending on the caller wrapping us in
    asyncio.wait_for. Python cannot forcibly kill a running thread, so a
    timed-out attempt's background thread keeps running briefly after we
    return — acceptable here because run_bhaskar_agent's own internal work
    (LLM calls, sandboxed subprocess runs) is itself bounded by its own
    real timeouts, so the orphaned thread terminates on its own shortly
    after; this wrapper's job is only to make sure the CALLER is never
    blocked past the deadline."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        result: dict[str, Any] = future.result(timeout=timeout)
        return result
    except concurrent.futures.TimeoutError:
        return {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": f"bhaskar_agent exceeded its {timeout}s wall-clock bound",
            "tokens_in": 0,
            "tokens_out": 0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": "",
            "result_summary": "",
            "tested_output": "",
            "error": f"bhaskar_agent run raised: {exc}",
            "tokens_in": 0,
            "tokens_out": 0,
        }
    finally:
        pool.shutdown(wait=False)


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
    from app.agents.bhaskar_agent import BhaskarRecursionError, run_bhaskar_agent

    attempts = max(1, settings.bhaskar_tool_max_retries + 1)
    last_error = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            gen = _run_with_wallclock_bound(
                lambda: run_bhaskar_agent(
                    task_description, context, repo_path, trace_id=trace_id
                ),
                settings.bhaskar_tool_timeout_seconds,
            )
        except BhaskarRecursionError as exc:
            # Structurally should never happen (see bhaskar_agent.py's
            # module docstring) — refuse rather than let it propagate as an
            # unhandled exception out of a tool handler.
            return json.dumps({"ok": False, "error": f"refused: {exc}"})

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
