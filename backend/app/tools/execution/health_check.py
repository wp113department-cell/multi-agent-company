"""health_check tool — tool_enhance.md productionization pass, tool
#113 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: health_check
Old path: app/agents/tools.py (`_HEALTH_CHECK_TOOL` schema dict) with
    THREE real implementations: `mon_health_check`
    (`make_monitoring_agent_handlers` — see finding below),
    `health_check_h` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/execution/health_check.py (this file) —
    `HEALTH_CHECK_TOOL`, `health_check_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `health_check` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler — `mon_health_check` is fully
    replaced, see finding below), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation — which was already
    injection-safe since every value inside it comes from settings,
    not the LLM, but is simplified here for consistency with this
    initiative's list-args-only convention).
Affected registries: none — app/fleet/tool_manifest.py's
    "health_check" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`, and none locked in `mon_health_check`'s
    old, always-curl-only output shape. New tests added: see
    tests/test_health_check_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/health_check.md.
---------------------------------------------------------------------------

`service` is the only LLM-controlled field, and it only ever SELECTS
which fixed branch(es) run (`in ("all", "backend")` / `in ("all",
"db")`) — never embedded into any command string. `port` and
`database_url` come from server-side settings, never the LLM. So the
usual worktree-escape/flag-collision/shell-injection classes
established throughout this initiative are structurally impossible
for the two already-correct implementations.

Two real, empirically-verified findings — both on `mon_health_check`,
which is a genuinely different, broken implementation.

1. **A real, severe functionality bug: `mon_health_check` completely
   ignores the `service` field — the tool's only documented input —
   and reads an entirely UNDOCUMENTED `url` field instead** (never
   declared anywhere in the schema). Proved live: a real,
   schema-conformant call with `service="db"` is silently ignored —
   this implementation ALWAYS curls a single hardcoded URL regardless
   of what `service` requests, and **never checks database
   connectivity at all, in any case** — directly contradicting the
   tool's own description ("backend HTTP health endpoint AND database
   connectivity").

2. **A real, second-order SSRF surface.** Because tool schemas are
   advisory to the model, not strictly enforced server-side (the same
   principle already established for tool #42's `git_stash` — "the
   schema's own enum is purely advisory... never enforced at
   runtime"), nothing prevents a real tool-call payload from including
   an extra, undocumented `url` key. `mon_health_check` would use that
   value directly as its `curl` target with zero validation — a real
   Server-Side Request Forgery primitive (e.g. a cloud metadata
   endpoint or an internal-only service) reachable through a tool the
   caller would reasonably assume takes no attacker-influenced network
   target at all.

Fixed by fully replacing `mon_health_check` with the shared
`health_check_handler()` — adopting the already-correct design
(`health_check_h`/`chat_agent.py`'s dispatch, both independently
verified safe) rather than kept as a second, broken, and
SSRF-exposed implementation. The shared handler never reads a `url`
field at all, closing finding #2 by construction, not just validation.
"""

from __future__ import annotations

import subprocess
from typing import Any


def health_check_handler(inp: dict[str, Any], port: int, database_url: str) -> str:
    """Core health_check logic shared by all three real call sites.
    `port`/`database_url` must come from server-side settings, never
    from `inp` — this tool takes no LLM-controlled network target."""
    service = str(inp.get("service", "all"))
    results: list[str] = []

    if service in ("all", "backend"):
        try:
            r = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://localhost:{port}/health",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            code = r.stdout.strip()
            results.append(
                f"Backend (:{port}/health): {'✅ UP' if code == '200' else f'⚠️ HTTP {code}'}"
            )
        except Exception:
            results.append(f"Backend (:{port}/health): ❌ unreachable")

    if service in ("all", "db"):
        if database_url:
            try:
                r = subprocess.run(
                    ["pg_isready", "-d", database_url],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                results.append(
                    f"Database: {'✅ UP' if r.returncode == 0 else '❌ DOWN'}"
                )
            except Exception:
                results.append("Database: ❓ pg_isready not available")
        else:
            results.append("Database: (DATABASE_URL not configured)")

    return "\n".join(results) if results else "No services checked"


HEALTH_CHECK_TOOL = {
    "name": "health_check",
    "description": "Check if backend services are up: backend HTTP health endpoint and database connectivity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service to check: 'all', 'backend', 'db' (default: all)",
            },
        },
        "required": [],
    },
}
