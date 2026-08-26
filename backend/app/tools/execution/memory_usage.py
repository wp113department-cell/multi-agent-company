"""memory_usage tool — tool_enhance.md productionization pass, tool
#114 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_usage
Old path: app/agents/tools.py (`_MEMORY_USAGE_TOOL` schema dict) with
    THREE real implementations: `mon_memory_usage`
    (`make_monitoring_agent_handlers` — see finding below),
    `memory_usage_h` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/execution/memory_usage.py (this file) —
    `MEMORY_USAGE_TOOL`, `memory_usage_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `memory_usage` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler — `mon_memory_usage` is fully
    replaced, see finding below), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation — which was already
    structurally injection-safe, since the schema has no input fields
    at all, but is simplified here for consistency with this
    initiative's list-args-only convention).
Affected registries: none — app/fleet/tool_manifest.py's
    "memory_usage" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`, and none locked in `mon_memory_usage`'s
    old, always-`free`-only output shape. New tests added: see
    tests/test_memory_usage_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_usage.md.
---------------------------------------------------------------------------

No LLM-controlled input reaches this tool at all — the schema's own
`input_schema.properties` is empty (`{}`), so the usual worktree-
escape/flag-collision/shell-injection classes established throughout
this initiative are structurally impossible here. Unlike tool #105's
`cpu_usage`, memory usage is a point-in-time quantity, not a
cumulative counter — a single `/proc/meminfo` read is not subject to
the "single-read gives the wrong answer" class that affected
`/proc/stat`, so no accuracy bug exists here.

One real finding: **`mon_memory_usage` has no `try/except` around its
`free` subprocess call, and always shells out to `free` instead of
preferring `/proc/meminfo` like its two siblings.** Unlike
`memory_usage_h`/`chat_agent.py`'s dispatch (both already correctly
try `/proc/meminfo` first, falling back to `free -h`, all wrapped in
error handling), a missing `free` binary — a real, plausible case in a
minimal container image — would raise an uncaught `FileNotFoundError`
straight out of the handler instead of a clean `[ERROR]` string. Same
robustness class already established for tools #105 (`mon_cpu_usage`)
and #109 (`dk_docker_ps`). Proved live with a simulated missing
binary.

Fixed via a shared `memory_usage_handler()`: prefers `/proc/meminfo`
(fast, no subprocess dependency) and falls back to `free -h` only when
unavailable, matching the already-correct design — the whole function
is wrapped in `try/except`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def memory_usage_handler() -> str:
    """Core memory_usage logic shared by all three real call sites."""
    try:
        mem_info = Path("/proc/meminfo")
        if mem_info.exists():
            rows = mem_info.read_text().splitlines()[:8]
            return "\n".join(rows)
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "[ERROR] Could not read memory"
    except Exception as e:
        return f"[ERROR] {e}"


MEMORY_USAGE_TOOL: dict[str, Any] = {
    "name": "memory_usage",
    "description": "Get current RAM usage from /proc/meminfo or the `free` command.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
