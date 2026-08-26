"""docker_ps tool — tool_enhance.md productionization pass, tool #109
(2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_ps
Old path: app/agents/tools.py (`_DOCKER_PS_TOOL` schema dict) with
    THREE real implementations: `dk_docker_ps`
    (`make_docker_agent_handlers`), `docker_ps` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/execution/docker_ps.py (this file) —
    `DOCKER_PS_TOOL`, `docker_ps_handler`. ALL THREE real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring `docker_ps`
    in `allowed_tools` — including `app/agents/monitoring_agent.py`,
    which imports `_DOCKER_PS_TOOL` directly from `app.agents.tools`
    (checked proactively before wiring — the plain module-level alias
    assignment preserves that import unchanged).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation — which was already
    structurally injection-safe, since `all` is a boolean gating a
    fixed literal suffix, but is simplified here for consistency with
    the rest of this initiative's list-args-only convention).
Affected registries: none — app/fleet/tool_manifest.py's "docker_ps"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_ps_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_ps.md.
---------------------------------------------------------------------------

No LLM-controlled string ever reaches a subprocess argv here — `all`
is a boolean gating a fixed literal `-a` flag, structurally immune to
injection by construction (same class as tools #73-75/#90). Two real
findings, both functionality/robustness bugs, not security.

1. **A real, significant functionality bug: `dk_docker_ps` completely
   IGNORES the `all` field.** The schema explicitly promises "Show all
   containers including stopped ones" — but this implementation always
   runs plain `docker ps` (never `-a`), regardless of what the caller
   requests. Proved live on this real host: with `all=True`
   effectively requested, this implementation hid 5 real, relevant
   containers a genuine caller would need to see — including a
   container stuck at "Created" and one that had exited with a
   failure code (exactly the kind of deployment problem an agent using
   this tool would be trying to diagnose).

2. **`dk_docker_ps` also has no `try/except` around the subprocess
   call** — unlike its two siblings, a missing `docker` binary would
   raise an uncaught `FileNotFoundError` instead of a clean `[ERROR]`
   string, same robustness class already established for tool #105's
   `mon_cpu_usage`.

Fixed via a shared `docker_ps_handler()`: reads and honors `all`
identically to the two already-correct implementations — closes
finding #1; the whole function is wrapped in `try/except` — closes
finding #2. Uses the wider `Ports`-inclusive format string
(`make_chat_handlers`'s version) for all three real call sites — a
capability increase for `dk_docker_ps`, not a narrowing.
"""

from __future__ import annotations

import subprocess
from typing import Any

MAX_OUTPUT_CHARS = 3000


def docker_ps_handler(inp: dict[str, Any]) -> str:
    """Core docker_ps logic shared by all three real call sites."""
    show_all = bool(inp.get("all", False))
    args = [
        "docker",
        "ps",
        "--format",
        "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}",
    ]
    if show_all:
        args.append("-a")

    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return (r.stdout + r.stderr)[:MAX_OUTPUT_CHARS] or "(no containers)"
    except FileNotFoundError:
        return "[ERROR] docker not found"
    except Exception as e:
        return f"[ERROR] {e}"


DOCKER_PS_TOOL = {
    "name": "docker_ps",
    "description": "List running Docker containers. Shows ID, image, status, and ports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "all": {
                "type": "boolean",
                "description": "Show all containers including stopped ones (default: false)",
            },
        },
        "required": [],
    },
}
