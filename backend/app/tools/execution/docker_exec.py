"""docker_exec tool — tool_enhance.md productionization pass, tool #20
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_exec (the `chat_agent.py` real dispatch only — see
    "Deliberately left untouched" below)
Old path: app/agents/tools.py (`_DOCKER_EXEC_TOOL` schema dict) +
    app/agents/chat_agent.py (inline dispatch body, the only real
    vulnerable/under-guarded implementation)
New path: app/tools/execution/docker_exec.py (this file) —
    `DOCKER_EXEC_TOOL`, `build_docker_exec_command`.
Affected agents: 2 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch (the fixed one) and `docker_agent` (via
    `dk_docker_exec`, never exposed to the injection half of this bug —
    see below).
Affected modules: app/agents/tools.py (schema re-export only — its own
    2 real handler implementations were already safe and already had the
    container risk check; no change needed), app/agents/chat_agent.py
    (its real dispatch now calls `build_docker_exec_command` for safe
    quoting, `check_command` for the same destructive-command denylist
    `make_chat_handlers`'s own implementation already used, and
    `_docker_container_risk_reason` for the same host-escape-surface
    check both tools.py implementations already had).
Affected registries: none — app/fleet/tool_manifest.py's "docker_exec"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["docker_exec"](...)` (already safe,
    untouched) or `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_exec_hardening.py.

Deliberately left untouched: `make_docker_agent_handlers()`'s
`dk_docker_exec` and `make_chat_handlers()`'s own `docker_exec` — both
already use list-args `subprocess.run` (no `shell=True`, so `container`
never needed quoting there), both already call
`_docker_container_risk_reason(container)`, and both already have a
destructive-command check (`dk_docker_exec`'s own keyword denylist,
`docker_exec`'s `check_command`). Neither needed any change.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_exec.md.
---------------------------------------------------------------------------

Real findings (severe — chat_agent.py's real dispatch had THREE gaps at
once, all absent from both of tools.py's own, already-correct
implementations of the same tool):

1. **Shell injection via `container`** (same bug class as tools
   #8/#16/#18/#19): `de_container` was interpolated directly into an
   f-string `shell=True` command with zero quoting — only `command` was
   `shlex.quote()`'d. Proved directly: a `container` value of
   `"x; touch /tmp/PWNED...; echo "` created a real marker file on the
   host.
2. **No `_docker_container_risk_reason` check at all** — both tools.py
   implementations of this exact tool already call this (inspects a
   container for `--privileged`/`--pid=host`/dangerous capabilities/
   sensitive host mounts before allowing exec into it), but
   chat_agent.py's real, interactive dispatch — the one actually reached
   by the main chat agent — never had it wired in. A real host-escape
   surface: the interactive agent could `docker exec` into a privileged
   or host-mounted container with zero warning.
3. **No destructive-command check** — `make_chat_handlers`'s own
   implementation already runs `command` through `check_command()` (the
   centralized policy-engine denylist); chat_agent.py's dispatch had no
   command filtering of any kind.
"""

from __future__ import annotations

import shlex

DOCKER_EXEC_TOOL = {
    "name": "docker_exec",
    "description": "Run a command inside a running Docker container.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
            "command": {
                "type": "string",
                "description": "Command to run inside the container",
            },
        },
        "required": ["container", "command"],
    },
}


def build_docker_exec_command(container: str, command: str) -> str:
    """Safely quotes both `container` and `command` for the
    `_run_subprocess` (`shell=True`) call chat_agent.py uses — same
    per-argument-quoting approach already established for
    `docker_build`/`docker_compose` (tools #18/#19), reused here rather
    than switching this one call site to list-args."""
    return f"docker exec {shlex.quote(container)} sh -c {shlex.quote(command)} 2>&1"
