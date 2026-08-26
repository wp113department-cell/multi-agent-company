"""cpu_profile tool — tool_enhance.md productionization pass, tool
#130 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: cpu_profile
Old path: app/agents/tools.py (`_CPU_PROFILE_TOOL` schema dict,
    `cpu_profile_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/cpu_profile.py (this file) —
    `CPU_PROFILE_TOOL`, `cpu_profile_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `cpu_profile` in `allowed_tools` (plus interactive chat, newly —
    see finding #3).
Affected modules: app/agents/tools.py (`cpu_profile_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's
    "cpu_profile" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_cpu_profile_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/cpu_profile.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **Severe: the tool silently broke for any `command` not literally
   prefixed with the word `"python"`.** The real, executed argv was
   built as `[..., "-s", "cumulative"] + command.split()[1:]` —
   unconditionally dropping the FIRST TOKEN of `command`, on the
   undocumented assumption it is always the literal string
   `"python"`. The schema's own example (`"python -m myapp"`) happens
   to make this "work" only by coincidence (dropping "python" leaves
   the correct `-m myapp` module invocation) — but the schema's field
   description ("Python command to profile") never requires a
   `python`-prefixed string, and a perfectly reasonable,
   schema-conformant call like `{"command": "myscript.py"}` instead
   dropped `myscript.py` itself, leaving cProfile with no target at
   all. Proved live: `cpu_profile({"command": "myscript.py"})`
   genuinely produced a `cProfile` usage-error traceback instead of
   ever profiling the script, while `{"command": "python
   myscript.py"}` happened to work. There was also a genuinely dead,
   never-executed `profiled = f"..."` variable (marked `# noqa: F841`
   — a linter suppression for code someone already knew was unused)
   left over from an earlier, different (and also broken) attempt at
   building this same command.
2. **A real robustness gap — an uncaught crash on a non-numeric
   `top`.** `int(inp.get("top", 20))` was never wrapped in a
   `try/except`, matching the class already fixed for tools
   #78/#127. Proved live: `top="not_a_number"` raised an unhandled
   `ValueError`.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/#110/#112/#118/#120/#122/#126/#129.**
   `cpu_profile` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: cpu_profile"`.

Fixed via a shared `cpu_profile_handler()`: `command` is tokenized
with `shlex.split()` and only a LITERAL leading `python`/`python3`
token is stripped (matching what the schema's own example implies,
without destroying a script name that never had that prefix), closing
finding #1 — the dead `profiled` variable is removed entirely. `top`
conversion is now wrapped in `try/except`, closing finding #2. A new
`chat_agent.py` dispatch branch delegates to this same shared handler,
closing finding #3.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any


def cpu_profile_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core cpu_profile logic — the one real implementation, fixed to
    no longer silently drop the profiled script's own name."""
    command = str(inp["command"])
    try:
        top = int(inp.get("top", 20))
    except (TypeError, ValueError):
        return f"[ERROR] top must be an integer, got {inp.get('top')!r}"

    tokens = shlex.split(command)
    if tokens and tokens[0] in ("python", "python3"):
        tokens = tokens[1:]

    try:
        r = subprocess.run(
            ["python", "-m", "cProfile", "-s", "cumulative"] + tokens,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=60,
        )
        lines = (r.stdout + r.stderr).strip().splitlines()
        return "\n".join(lines[: top + 10])
    except Exception as e:
        return f"[ERROR] cpu_profile: {e}"


CPU_PROFILE_TOOL: dict[str, Any] = {
    "name": "cpu_profile",
    "description": "Profile a Python script or module with cProfile and return the top N slowest functions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Python command to profile, e.g. 'python -m myapp'",
            },
            "top": {
                "type": "integer",
                "description": "Number of top functions to return (default: 20)",
            },
        },
        "required": ["command"],
    },
}
