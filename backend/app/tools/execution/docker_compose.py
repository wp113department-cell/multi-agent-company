"""docker_compose tool — tool_enhance.md productionization pass, tool #19
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_compose (the `chat_agent.py` real dispatch only — see
    "Deliberately left untouched" below)
Old path: app/agents/tools.py (`_DOCKER_COMPOSE_TOOL` schema dict) +
    app/agents/chat_agent.py (inline dispatch body, the only real
    vulnerable implementation)
New path: app/tools/execution/docker_compose.py (this file) —
    `DOCKER_COMPOSE_TOOL`, `build_docker_compose_command`.
Affected agents: 2 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch (the fixed one) and `docker_agent` (via
    `dk_docker_compose`, never exposed to this bug — see below).
Affected modules: app/agents/tools.py (schema re-export only — its own
    2 real handler implementations were already safe and needed no
    change), app/agents/chat_agent.py (its real dispatch now calls
    `build_docker_compose_command` to get a safely-quoted command string
    instead of interpolating `services` raw).
Affected registries: none — app/fleet/tool_manifest.py's
    "docker_compose" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["docker_compose"](...)` (already safe,
    untouched) or `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_compose_hardening.py.

Deliberately left untouched: `make_chat_handlers()`'s own `docker_compose`
— already safe, builds a list-args `subprocess.run(dc_cmd, ...)` command
(no `shell=True`) with `services` appended as individual list elements,
so no string-interpolation injection surface exists there at all.
`make_docker_agent_handlers()`'s `dk_docker_compose` — narrower by
design (only `ps`/`logs`/`config`/`images` allowed, no `services` field,
no `shell=True`), never exposed to this bug either.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_compose.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live shell injection, same bug class as
tools #8/#16/#19's siblings): `chat_agent.py`'s real dispatch joined
`services` (a list of LLM-controlled strings) with `" ".join(...)` and
interpolated the result directly into an f-string `shell=True` command
with zero quoting. Proved directly: a `services` value of
`["; touch /tmp/PWNED...; echo "]` created a real marker file on the
host, completely outside the intended `docker compose` invocation.
`make_chat_handlers`'s own implementation already avoided this by using
list-args `subprocess.run` instead of a shell string — the fix here
follows the SAME per-argument-quoting pattern already established for
`docker_build`'s `chat_agent.py` dispatch (tool #18), which already
`shlex.quote()`'d each part before joining, rather than switching
`chat_agent.py`'s whole command-building approach to list-args (which
would require replacing its shared `_run_subprocess` helper, used by
dozens of other tools, for this one case).
"""

from __future__ import annotations

import shlex

DOCKER_COMPOSE_TOOL = {
    "name": "docker_compose",
    "description": "Run docker compose commands (up, down, restart, build, ps, logs, pull).",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["up", "down", "restart", "build", "ps", "logs", "pull"],
                "description": "Action to perform",
            },
            "services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific services to target (default: all)",
            },
            "detach": {
                "type": "boolean",
                "description": "Run in background for 'up' (default: true)",
            },
        },
        "required": ["action"],
    },
}


def build_docker_compose_command(
    action: str, services: list[str], detach: bool
) -> tuple[str | None, str | None]:
    """Returns (command, error). error is a plain denial reason (not
    prefixed — the caller decides `[ERROR]`/`[POLICY DENIED]`) on an
    unknown action. Every part of the command — including each service
    name — is `shlex.quote()`'d individually before being joined into the
    single string `_run_subprocess` (a `shell=True` helper) expects, so a
    service name shaped like a shell command can never break out."""
    if action == "up":
        parts = ["docker", "compose", "up"] + (["-d"] if detach else []) + services
    elif action in ("down", "restart", "build", "ps", "pull"):
        parts = ["docker", "compose", action] + services
    elif action == "logs":
        parts = ["docker", "compose", "logs", "--tail=50"] + services
    else:
        return None, f"Unknown action: {action}"
    return " ".join(shlex.quote(p) for p in parts), None
