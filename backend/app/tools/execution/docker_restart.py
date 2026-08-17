"""docker_restart tool — tool_enhance.md productionization pass, tool #21
(2026-08-17).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: docker_restart (the `chat_agent.py` real dispatch only — see
    "Deliberately left untouched" below)
Old path: app/agents/tools.py (`_DOCKER_RESTART_TOOL` schema dict) +
    app/agents/chat_agent.py (inline dispatch body, the only real
    vulnerable implementation)
New path: app/tools/execution/docker_restart.py (this file) —
    `DOCKER_RESTART_TOOL`, `build_docker_restart_command`.
Affected agents: 2 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch (the fixed one) and `docker_agent` (via
    `dk_docker_restart`, never exposed to this bug).
Affected modules: app/agents/tools.py (schema re-export only — its own 2
    real handler implementations were already safe and needed no change),
    app/agents/chat_agent.py (its real dispatch now calls
    `build_docker_restart_command` for safe quoting).
Affected registries: none — app/fleet/tool_manifest.py's
    "docker_restart" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["docker_restart"](...)` (already safe,
    untouched) or `ChatAgent._execute_tool`. New tests added: see
    tests/test_docker_restart_hardening.py.

Deliberately left untouched: `make_docker_agent_handlers()`'s
`dk_docker_restart` and `make_chat_handlers()`'s own `docker_restart_h`
— both already use list-args `subprocess.run` (no `shell=True`), so
`container` never needed quoting there. Unlike `docker_exec`
(tool #20), this tool has no `command` field and doesn't run arbitrary
code inside the container, so `_docker_container_risk_reason`'s
exec-into-a-privileged-container concern doesn't apply the same way —
restarting a container isn't a code-execution primitive.

Runtime verification: PASS — see
    backend/docs/tool_productionization/docker_restart.md.
---------------------------------------------------------------------------

Real finding (severe — same bug class as tools #8/#16/#18/#19/#20):
`chat_agent.py`'s real dispatch interpolated `container` (LLM-controlled)
directly into an f-string `shell=True` command with zero quoting:

```python
drst_cmd = f"docker restart {drst_name} 2>&1"
```

Proved directly: a `container` value of `"x; touch /tmp/PWNED...; echo "`
created a real marker file on the host, completely outside the intended
`docker restart` invocation. Both tools.py implementations of this exact
tool were already safe (list-args, no `shell=True`) — this fix brings
`chat_agent.py`'s dispatch in line with them.
"""

from __future__ import annotations

import shlex

DOCKER_RESTART_TOOL = {
    "name": "docker_restart",
    "description": "Restart a running Docker container by name or ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {"type": "string", "description": "Container name or ID"},
        },
        "required": ["container"],
    },
}


def build_docker_restart_command(container: str) -> str:
    """Safely quotes `container` for the `_run_subprocess` (`shell=True`)
    call chat_agent.py uses — same per-argument-quoting approach already
    established for `docker_build`/`docker_compose`/`docker_exec` (tools
    #18/#19/#20)."""
    return f"docker restart {shlex.quote(container)} 2>&1"
