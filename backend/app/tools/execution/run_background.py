"""run_background tool — tool_enhance.md productionization pass, tool
#58 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_background
Old path: app/agents/tools.py (`_RUN_BACKGROUND_TOOL_DEF` schema dict).
New path: app/tools/execution/run_background.py (this file) —
    `RUN_BACKGROUND_TOOL`, `validate_run_background_cwd`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch and `make_chat_handlers`'s own `run_background`,
    both real, reachable callers, both delegating to the single shared
    `app.fleet.process_manager.spawn()` — that function (not this
    schema) is where the real fixes for this tool's turn landed; see
    its own docstring and `app.fleet.process_manager.kill()`'s.
Affected modules: app/agents/tools.py, app/agents/chat_agent.py (schema
    re-export; both real dispatch bodies now validate `cwd` before
    calling the shared, now-sandboxed `spawn()`).
Affected registries: none — app/fleet/tool_manifest.py's
    "run_background" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests beyond the
    retroactive kill_process fix (see below). New tests added: see
    tests/test_run_background_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_background.md.
---------------------------------------------------------------------------

Two real, severe findings, both fixed at the shared implementation in
`app/fleet/process_manager.py` (not duplicated here):

1. **`command` had zero sandboxing** — full, unrestricted host shell
   execution via `subprocess.Popen(command, shell=True)`, the same
   unsandboxed state `bash` (tool #1) was in before its own real Docker-
   sandboxing remediation. Proved live: a real payload wrote a marker
   file to an arbitrary host path with no restriction. Raised to the
   user directly (AskUserQuestion) given the scope — user chose to
   apply the same real Docker sandboxing tool #1 built for bash.
   `process_manager.spawn()` now routes through a real, `--init`-based,
   read-only-rootfs, non-root, resource-capped `docker run` (foreground,
   not detached, so the existing PID-based `kill_process`/`read_output`/
   `list_background_processes` machinery needed zero changes) when
   `Settings.bash_sandbox_enabled` (fails closed if Docker itself is
   unreachable).

2. **Retroactive fix to `kill_process` (tool #49, already shipped)** —
   uncovered while verifying THIS turn's own sandboxing work, not
   introduced by it: `spawn()`'s `shell=True` Popen made the tracked PID
   the WRAPPING `/bin/sh -c <command>` process, not the real command —
   `kill()` sent `sig_name` to that shell wrapper via plain `os.kill()`,
   never to its child. Proved live with a plain `sleep 300` background
   command: the shell wrapper was correctly reaped, but the real `sleep`
   process was left running, orphaned, completely untracked —
   `kill_process` returned a false "Sent TERM to PID X" success message
   while the actual command kept running indefinitely. Fixed via
   `os.killpg()` (signaling the whole process group) plus a companion
   `start_new_session=True` on the `spawn()` Popen (so each background
   command's shell — and everything it spawns, sandboxed or not — gets
   its own process group, letting `killpg` reach the real command
   without also reaching the caller's own). See
   `docs/tool_productionization/kill_process.md`'s own correction note.

Since `cwd` now gets bind-mounted into the sandbox as `/workspace:rw`
when sandboxing is enabled, an unvalidated `cwd` would let an
LLM-controlled value mount an ARBITRARY host directory read-write into
the "sandboxed" container — defeating the whole point of sandboxing it.
Fixed via `validate_run_background_cwd()` (the same `check_path_in_
worktree()` chokepoint used throughout this initiative since tool #9)
on both real call sites, before `spawn()` is ever called.
"""

from __future__ import annotations

from app.policy.engine import check_path_in_worktree

RUN_BACKGROUND_TOOL = {
    "name": "run_background",
    "description": "Start a shell command in the background. Returns immediately with a PID. Use kill_process to stop it. Pass wait_for_pids to only start this command after other background PID(s) have exited (task dependency chaining).",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run in background",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (default: repo root)",
            },
            "wait_for_pids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "PIDs (from earlier run_background calls) that must exit before this command starts running — expresses a dependency between background jobs.",
            },
        },
        "required": ["command"],
    },
}


def validate_run_background_cwd(cwd: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `cwd` escapes the repo, else None.
    Real and necessary once sandboxing is enabled: `cwd` is the one host
    path bind-mounted read-write into the sandboxed container."""
    result = check_path_in_worktree(cwd, worktree_path)
    if not result.allowed:
        return f"[ERROR] {result.reason}"
    return None
