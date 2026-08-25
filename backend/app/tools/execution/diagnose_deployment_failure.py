"""diagnose_deployment_failure tool — tool_enhance.md productionization
pass, tool #106 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: diagnose_deployment_failure
Old path: app/agents/tools.py (`_DIAGNOSE_DEPLOYMENT_FAILURE_TOOL`
    schema dict) with THREE real implementations, all byte-identical
    logic: `dk_diagnose_deployment_failure` (`make_docker_agent_
    handlers`), `diagnose_deployment_failure` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (functionally identical, but `shell=True`
    instead of list-args — see finding #1 below).
New path: app/tools/execution/diagnose_deployment_failure.py (this
    file) — `DIAGNOSE_DEPLOYMENT_FAILURE_TOOL`,
    `gather_deployment_diagnostics`. ALL THREE real call sites now
    delegate to this one shared gathering function; each caller still
    calls the existing, unmodified `_llm_diagnose_deployment_failure()`
    itself afterward (see "Why the LLM step stays where it is" below).
Affected agents: per tool_inventory.json, agents declaring
    `diagnose_deployment_failure` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared gathering function, then call the
    untouched `_llm_diagnose_deployment_failure()` exactly as before),
    app/agents/chat_agent.py (its dispatch now calls the same shared
    gathering function, dropping its `_run_subprocess`/`shell=True`
    invocation entirely, then calls the same untouched
    `_llm_diagnose_deployment_failure()` it already imports).
Affected registries: none — app/fleet/tool_manifest.py's
    "diagnose_deployment_failure" ToolManifestEntry is pure metadata,
    keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_diagnose_deployment_failure_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/diagnose_deployment_failure.md.
---------------------------------------------------------------------------

**Why the LLM diagnosis step stays where it is**: `_llm_diagnose_
deployment_failure()` (in `app/agents/tools.py`) has no bug of its
own — the audit found nothing wrong with the diagnosis PROMPT or
generation step, only with how the evidence was GATHERED (the
`container` field). It depends on `_llm_generate_text()`, a genuinely
shared utility with 6 unrelated callers across `tools.py` — moving it
here would require either dragging that whole shared utility along
(touching unrelated tools) or a module-load-time circular import
(`tools.py` already imports this new module near the top of the file,
before `_llm_generate_text`/`_llm_diagnose_deployment_failure` are
even defined). Splitting responsibility this way — this module gathers
evidence safely, the existing caller-side helper diagnoses it — avoids
both problems with zero behavior change to the diagnosis step itself.
`_summarize_docker_log_patterns()` is imported normally, at module
load time, from `app.agents.tool_security` — it used to live in
`tools.py` itself (which would have forced a lazy, in-function import
here to avoid a circular dependency), but tool #108's own turn
(`docker_logs`, elsewhere in this same batch, also needs this exact
function) relocated it to this neutral, lower-level module instead, so
both tools can import it cleanly.

Two real, empirically-verified findings.

1. **The most severe: a genuine, direct shell-injection (arbitrary
   command execution) on `chat_agent.py`'s dispatch.** `dd_container`
   was interpolated COMPLETELY UNQUOTED into TWO separate f-string
   `shell=True` commands (`docker logs --tail {lines} {container}`,
   `docker inspect {container}`). Proved live: `container="; touch
   /tmp/PWNED_DIAGNOSE_DEPLOYMENT; echo x"` genuinely executed the
   injected command — same severity class as tools #101/#102/#104's
   chat_agent.py findings.

2. **A flag-collision on `container` (bare positional, no `--`
   separator), across all three implementations — including the two
   list-args ones,** and an uncaught `ValueError` on `lines` if a
   non-numeric value is ever passed (the schema types it `integer` but
   this was never actually enforced). Proved live:
   `int("not-a-number")` raises uncaught, matching the class already
   established for tools #78/#96 ("schema types a field but the real
   code never validates it").

Fixed via a shared `gather_deployment_diagnostics()`: rejects a
flag-shaped `container` (matching the `find_sql`/`find_api`/
`find_config` precedent) and a non-numeric `lines`, closing finding
#2. `chat_agent.py`'s dispatch now uses list-args subprocess calls
exclusively (no `shell=True` at all) — closing finding #1
structurally, not just validating around it.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from app.agents.tool_security import _summarize_docker_log_patterns


def gather_deployment_diagnostics(inp: dict[str, Any]) -> str:
    """Gathers real `docker ps -a` / `docker logs` / `docker inspect`
    evidence for the shared LLM diagnosis step to reason over.
    Returns either the gathered context text, or an `[ERROR]`/
    `[POLICY DENIED]` string if `inp` is invalid — callers must check
    for that prefix before passing the result on to
    `_llm_diagnose_deployment_failure()`."""
    container = str(inp.get("container", "")).strip()
    lines_raw = inp.get("lines", 100)

    try:
        lines = int(lines_raw)
    except (TypeError, ValueError):
        return f"[ERROR] lines must be a number, got: {lines_raw!r}"

    if container and container.startswith("-"):
        return (
            f"[ERROR] container must not look like a command-line flag: "
            f"{container!r} — docker would interpret a leading '-' as its "
            "own option rather than a container name/ID."
        )

    parts: list[str] = []
    ps_r = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--format",
            "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    parts.append(
        "=== docker ps -a ===\n" + (ps_r.stdout or ps_r.stderr or "(no containers)")
    )

    if container:
        logs_r = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        raw_logs = (logs_r.stdout + logs_r.stderr)[:6000]
        parts.append(
            f"=== docker logs --tail {lines} {container} ===\n"
            + (
                _summarize_docker_log_patterns(raw_logs) + raw_logs
                if raw_logs
                else "(no logs)"
            )
        )

        inspect_r = subprocess.run(
            ["docker", "inspect", container],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if inspect_r.returncode == 0:
            try:
                data = json.loads(inspect_r.stdout)
                state = (data[0] if data else {}).get("State", {})
                inspect_summary = {
                    "Status": state.get("Status"),
                    "ExitCode": state.get("ExitCode"),
                    "Error": state.get("Error"),
                    "OOMKilled": state.get("OOMKilled"),
                    "RestartCount": (data[0] if data else {}).get("RestartCount"),
                    "StartedAt": state.get("StartedAt"),
                    "FinishedAt": state.get("FinishedAt"),
                }
                parts.append(
                    "=== docker inspect (State) ===\n"
                    + json.dumps(inspect_summary, indent=2)
                )
            except Exception:
                parts.append("=== docker inspect ===\n" + inspect_r.stdout[:2000])
        else:
            parts.append(
                f"[ERROR] docker inspect {container} failed: "
                f"{(inspect_r.stderr or '')[:500]}"
            )

    return "\n\n".join(parts)


DIAGNOSE_DEPLOYMENT_FAILURE_TOOL = {
    "name": "diagnose_deployment_failure",
    "description": "Diagnose a real deployment/container failure: gathers real docker ps -a state, docker logs, and docker inspect (exit code, OOMKilled, restart count, error) for the given container — or just the overall container state if none is given — then adds an LLM root-cause diagnosis grounded strictly in that gathered evidence. Distinct from docker_logs, which only returns raw/pattern-flagged log text with no diagnosis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "container": {
                "type": "string",
                "description": "Container name or ID to diagnose (omit to just diagnose overall docker ps -a state)",
            },
            "lines": {
                "type": "integer",
                "description": "Number of log lines to gather when container is given (default: 100)",
            },
        },
        "required": [],
    },
}
