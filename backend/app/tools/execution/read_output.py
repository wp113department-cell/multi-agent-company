"""read_output tool — tool_enhance.md productionization pass, tool
#176 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_output
Old path: app/agents/tools.py (`_READ_OUTPUT_TOOL` schema dict,
    `read_output_h` inside `make_chat_handlers()`) AND
    app/agents/chat_agent.py (its own separate, previously-duplicated
    `if tool_name == "read_output":` dispatch body) — TWO real call
    sites, both already delegating to the same shared
    `app.fleet.process_manager.read_output()`, but each doing its own
    unguarded `int(inp["pid"])` / `int(inp.get("lines", 50))`
    conversion first (see finding below).
New path: app/tools/execution/read_output.py (this file) —
    `READ_OUTPUT_TOOL`, `read_output_handler` (now does the pid/lines
    parsing safely, once, shared by both call sites).
Affected agents: per tool_inventory.json, agents declaring
    `read_output` in `allowed_tools` (both `make_chat_handlers()`-
    based one-shot agents and interactive chat).
Affected modules: app/agents/tools.py (`read_output_h` delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    delegates to the same shared handler instead of its own
    unguarded conversion).
Affected registries: none — app/fleet/tool_manifest.py's
    "read_output" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_read_output_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_output.md.
---------------------------------------------------------------------------

Audit: this tool was ALREADY dispatched correctly on both real access
paths (`make_chat_handlers()`'s `read_output_h` AND `chat_agent.py`'s
own separate dispatch), and both already delegated to the same
shared, safe `app.fleet.process_manager.read_output()` for the actual
stdout/stderr reading logic (no injection surface there — `pid` is
used only as a dict key into the caller's own tracked-process map,
never reaches a subprocess/shell). This is the same
"duplicate-implementation, core logic already shared and safe" shape
as tool #162's `list_background_processes`.

One real finding: **uncaught crash on malformed `pid`/`lines`
input**, same class as tools #70/#72/#76/#127/#130/#135. Both call
sites did their own `int(inp["pid"])` / `int(inp.get("lines", 50))`
conversion BEFORE calling the shared `process_manager.read_output()`
— with no `try`/`except` around either. Proved live on all 3 real
access paths:
- `read_output({})` (missing `pid`) → uncaught `KeyError('pid')`.
- `read_output({"pid": "not-a-number"})` → uncaught `ValueError`.
- `read_output({"pid": 12345, "lines": "bad"})` → uncaught
  `ValueError`.
Through `chat_agent.py`'s real graph-node call path these are caught
by its own outer generic `except Exception` (turning them into a
`"[ERROR] Tool read_output failed: ..."` result rather than a hard
crash — same mitigating factor already documented for the `list_files`
#68 finding), but `make_chat_handlers()`'s handlers dict is consumed
directly, with NO such outer wrapper, by many one-shot agents
(`mcp_developer_agent`, `evaluation_agent`, `devex_agent`, etc. — 18+
callers per grep) — for those, an uncaught exception genuinely
propagates.

Fixed by consolidating pid/lines parsing into this shared
`read_output_handler()`, used identically by both call sites: bad
input now returns a clean `[ERROR]` message instead of raising.
"""

from __future__ import annotations

from typing import Any, Callable

from app.fleet import process_manager

READ_OUTPUT_TOOL: dict[str, Any] = {
    "name": "read_output",
    "description": "Read the latest stdout/stderr from a background process started with run_background.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "description": "Process ID returned by run_background",
            },
            "lines": {
                "type": "integer",
                "description": "Max lines to return (default: 50)",
            },
        },
        "required": ["pid"],
    },
}


def read_output_handler(
    inp: dict[str, Any],
    procs: dict[int, Any],
    read_stream_fn: Callable[[Any], str | None],
) -> str:
    """Safely parse `pid`/`lines` (closing the crash finding — see
    module docstring) then delegate to the already-safe, already-
    shared `process_manager.read_output()`."""
    try:
        pid = int(inp["pid"])
    except KeyError:
        return "[ERROR] read_output: 'pid' is required"
    except (TypeError, ValueError):
        return f"[ERROR] read_output: 'pid' must be an integer, got {inp.get('pid')!r}"
    try:
        max_lines = int(inp.get("lines", 50))
    except (TypeError, ValueError):
        return (
            f"[ERROR] read_output: 'lines' must be an integer, got {inp.get('lines')!r}"
        )
    return process_manager.read_output(pid, max_lines, procs, read_stream_fn)
