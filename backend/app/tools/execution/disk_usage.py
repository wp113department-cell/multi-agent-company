"""disk_usage tool — tool_enhance.md productionization pass, tool #107
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: disk_usage
Old path: app/agents/tools.py (`_DISK_USAGE_TOOL` schema dict) with
    THREE real implementations: `mon_disk_usage`
    (`make_monitoring_agent_handlers`), `disk_usage_h` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/execution/disk_usage.py (this file) —
    `DISK_USAGE_TOOL`, `disk_usage_handler`. ALL THREE real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `disk_usage` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "disk_usage"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`, and none locked in `mon_disk_usage`'s
    old `df`-based output format. New tests added: see
    tests/test_disk_usage_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/disk_usage.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **`mon_disk_usage` genuinely diverges from the tool's own documented
   contract, in two separate ways.** The schema explicitly promises
   "Get disk usage (total, used, free) for a path using
   shutil.disk_usage (stdlib)... default: repo root" — but
   `mon_disk_usage` (a) uses `subprocess.run(["df", "-h", path])`
   instead, a completely different mechanism producing a differently
   FORMATTED result (a raw `df` table, not the other two
   implementations' "Total/Used/Free GB" text) than every other real
   call site; and (b) defaults `path` to `"/"` (the whole HOST root
   filesystem) rather than the repo root the schema documents. Proved
   live: with no `path` given, this implementation reports the ENTIRE
   HOST's disk usage by default — a real information-disclosure-by-
   default bug, not just a documentation mismatch, since every other
   real call site scopes to the project by default.

2. **Worktree-boundary escape, on all three implementations.** None
   validated `path` before handing it to `shutil.disk_usage()` (or,
   for `mon_disk_usage`, `df`). Proved live: `shutil.disk_usage("/etc")`
   genuinely returned real host filesystem statistics for a directory
   completely outside any repo.

Fixed via a shared `disk_usage_handler()`: uses `shutil.disk_usage()`
consistently (matching the tool's own documented mechanism, and
removing `mon_disk_usage`'s external `df` binary dependency entirely)
— closes finding #1a; defaults to the handler's own configured
worktree root when `path` is empty, matching the documented "default:
repo root" contract — closes finding #1b; `check_path_in_worktree()`
rejects any `path` value that resolves outside the worktree — closes
finding #2.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

_GB = 1024**3


def disk_usage_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core disk_usage logic shared by all three real call sites."""
    path = str(inp.get("path", ""))

    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = str(root / path) if path else str(root)
    try:
        usage = shutil.disk_usage(target)
        pct = round(usage.used / usage.total * 100, 1) if usage.total else 0
        return (
            f"Disk usage for {target}:\n"
            f"  Total: {usage.total / _GB:.1f} GB\n"
            f"  Used:  {usage.used / _GB:.1f} GB  ({pct}%)\n"
            f"  Free:  {usage.free / _GB:.1f} GB"
        )
    except Exception as e:
        return f"[ERROR] {e}"


DISK_USAGE_TOOL = {
    "name": "disk_usage",
    "description": "Get disk usage (total, used, free) for a path using shutil.disk_usage (stdlib).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to check (default: repo root)",
            },
        },
        "required": [],
    },
}
