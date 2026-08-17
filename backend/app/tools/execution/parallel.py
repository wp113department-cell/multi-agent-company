"""run_parallel_commands tool — tool_enhance.md productionization pass,
tool #9 (2026-08-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_parallel_commands
Old path: app/agents/tools.py (`_MAX_PARALLEL_COMMANDS`,
    `_RUN_PARALLEL_COMMANDS_TOOL` schema dict, and the
    `run_parallel_commands_h` handler inside `make_chat_handlers()`)
New path: app/tools/execution/parallel.py (this file) —
    `MAX_PARALLEL_COMMANDS`, `RUN_PARALLEL_COMMANDS_TOOL`,
    `run_parallel_commands_handler`.

Affected agents: only chat_agent's own AGENT_CONTRACT lists
    run_parallel_commands as an allowed_tool. No one-shot agent has it in
    allowed_tools, so `run_parallel_commands_handler` here is unreachable
    in production today — kept correct for defense-in-depth/consistency,
    matching the rest of this tool series' precedent. The interactive
    chat agent has its own separate, real, working dispatch in
    app/agents/chat_agent.py (which now imports `MAX_PARALLEL_COMMANDS`
    from here instead of `app.agents.tools`).
Affected modules: app/agents/tools.py (compatibility re-export),
    app/agents/chat_agent.py (updated its `_MAX_PARALLEL_COMMANDS` import
    to the new location).
Affected registries: none — app/fleet/tool_manifest.py's
    "run_parallel_commands" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every real test accesses this
    tool via `handlers["run_parallel_commands"](...)` or
    `ChatAgent._execute_tool`.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_parallel_commands.md.
---------------------------------------------------------------------------

Real, empirically-verified finding (full detail in
run_parallel_commands.md), fixed together with the identical bug in the
generic `bash` tool (tool #1, already GREEN-FLAGGED before this was
found — fixed here too per explicit user direction): each command's
`cwd` field is fully LLM-controlled and was passed straight through to
`app.policy.sandbox.run_sandboxed` (via `_run_bash_command`) with no
validation that it stays inside the caller's own repo.
`run_sandboxed()` mounts whatever `cwd` it receives read-write as the
container's `/workspace` — proved directly (not assumed): a real
directory outside any intended worktree was mounted into the sandbox and
a file inside it was read back through the container. Fixed by
validating every `cwd` through `check_path_in_worktree` (the same,
already-established mechanism this codebase already uses for
write_file/edit_file's own path arguments) before any command reaches
the sandboxed execution primitive.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.tool_security import _is_dangerous_command
from app.policy.engine import check_command, check_path_in_worktree
from app.tools.execution.bash import _run_bash_command

MAX_PARALLEL_COMMANDS = 10

RUN_PARALLEL_COMMANDS_TOOL: dict[str, Any] = {
    "name": "run_parallel_commands",
    "description": f"Run up to {MAX_PARALLEL_COMMANDS} independent shell commands concurrently (fan-out) and return each result. Use only for commands that do NOT depend on each other's output (e.g. two unrelated test suites); for anything destructive or that needs human confirmation, use the bash tool individually instead.",
    "input_schema": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (default: repo root)",
                        },
                    },
                    "required": ["command"],
                },
                "description": f"Commands to run concurrently (max {MAX_PARALLEL_COMMANDS})",
            },
            "timeout": {
                "type": "integer",
                "description": "Per-command timeout in seconds (default 60)",
            },
        },
        "required": ["commands"],
    },
}


def run_parallel_commands_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Sync handler used by make_chat_handlers() — unreachable by any
    real one-shot agent today (run_parallel_commands isn't in any of
    their allowed_tools), kept correct for defense-in-depth/consistency
    with the real, reachable chat_agent.py dispatch."""
    raw_commands = inp.get("commands")
    if not isinstance(raw_commands, list) or not raw_commands:
        return "[ERROR] commands must be a non-empty list of {command, cwd?} objects"
    if len(raw_commands) > MAX_PARALLEL_COMMANDS:
        return f"[ERROR] run_parallel_commands supports at most {MAX_PARALLEL_COMMANDS} commands per call"
    rpc_timeout = int(inp.get("timeout", 60))

    parsed: list[tuple[str, str]] = []
    for entry in raw_commands:
        if isinstance(entry, dict):
            cmd = str(entry.get("command", ""))
            cwd = str(entry.get("cwd") or repo_path)
        else:
            cmd = str(entry)
            cwd = repo_path
        parsed.append((cmd, cwd))

    for cmd, cwd in parsed:
        cwd_check = check_path_in_worktree(cwd, repo_path)
        if not cwd_check.allowed:
            return f"[POLICY DENIED] {cwd_check.reason}"
        if cmd and _is_dangerous_command(cmd):
            return (
                f"[POLICY DENIED] {cmd!r} looks destructive/dangerous — "
                "run_parallel_commands does not support the bash tool's "
                "human-confirmation flow. Run it individually via bash instead."
            )

    async def _run_one(cmd: str, cwd: str) -> str:
        if not cmd:
            return "[ERROR] empty command"
        rpc_policy = check_command(cmd)
        if not rpc_policy.allowed:
            return f"[POLICY DENIED] {rpc_policy.reason}"
        stdout, stderr, returncode, timed_out = await asyncio.to_thread(
            _run_bash_command, cmd, cwd, timeout=rpc_timeout
        )
        if timed_out:
            return f"[ERROR] Command timed out after {rpc_timeout}s"
        out = stdout
        if stderr:
            out += f"\n[stderr]\n{stderr}"
        if returncode != 0:
            out += f"\n[exit {returncode}]"
        return out.strip() or "(no output)"

    async def _run_all() -> list[str]:
        return await asyncio.gather(*(_run_one(c, w) for c, w in parsed))

    results = asyncio.run(_run_all())
    return "\n\n".join(
        f"=== [{i}] {cmd[:80]!r} ===\n{res}"
        for i, ((cmd, _cwd), res) in enumerate(zip(parsed, results))
    )
