"""list_background_processes tool — tool_enhance.md productionization
pass, tool #162 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_background_processes
Old path: app/agents/tools.py (`_LIST_BACKGROUND_PROCESSES_TOOL`
    schema dict, `list_background_processes_h` inside
    `make_chat_handlers()`) + app/agents/chat_agent.py (its own
    separate dispatch) — TWO real implementations, both already
    calling the same shared `app.fleet.process_manager.format_tracked()`
    function on their own session's process registry
    (`_session_bg_procs` in `make_chat_handlers()`'s closure,
    `self._background_processes` in `ChatAgent`).
New path: app/tools/execution/list_background_processes.py (this
    file) — `LIST_BACKGROUND_PROCESSES_TOOL`,
    `list_background_processes_handler`. Both real call sites now
    delegate to this one shared handler, which simply forwards to the
    caller's own process registry.
Affected agents: per tool_inventory.json, agents declaring
    `list_background_processes` in `allowed_tools` (plus interactive
    chat, which already had a real, correctly-matching dispatch —
    unlike most tools this initiative, this one was never missing its
    dispatch branch).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "list_background_processes" ToolManifestEntry is pure metadata,
    keyed by tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_list_background_processes_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_background_processes.md.
---------------------------------------------------------------------------

No real bug found. The input schema is empty (no properties at all),
so there is no LLM-controlled input reaching this tool — the
worktree-boundary-escape and injection classes established repeatedly
this initiative do not apply. Both real implementations were already
correctly dispatched (`chat_agent.py` was never missing this branch,
unusually for this initiative) and already delegate to the same,
already-correct, already-shared `app.fleet.process_manager.
format_tracked()` function — confirmed via that function's own module
docstring, which states it is "used directly by the
list_background_processes tool handler in both tools.py and
chat_agent.py". Proved live: a real background process started via
`run_background` was genuinely reported by `list_background_processes`
with the correct PID, status, age, cwd, and command.

The only action taken this turn is modularization, mandatory for
every tool under this initiative regardless of finding count (see
tool #147's `generate_patch` / tool #156's `inspect_github_repo` for
the identical "no bug found, still extracted" precedent) — each real
call site now delegates to one shared handler that forwards to the
caller's own per-session process registry, instead of each
independently re-implementing the identical one-line forward to
`format_tracked()`.
"""

from __future__ import annotations

import subprocess
from typing import Any

LIST_BACKGROUND_PROCESSES_TOOL: dict[str, Any] = {
    "name": "list_background_processes",
    "description": "List background processes started in this session via run_background, with age and whether each is possibly hung (alive well past the expected runtime). Distinct from list_processes, which lists all OS processes.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def list_background_processes_handler(
    procs: dict[int, "subprocess.Popen[str]"],
) -> str:
    """Core list_background_processes logic — the one real behavior,
    unchanged: format the caller's own per-session background-process
    registry via the already-shared `format_tracked()`."""
    from app.fleet import process_manager

    return process_manager.format_tracked(procs)
