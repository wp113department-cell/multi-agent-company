"""run_script tool — tool_enhance.md productionization pass, tool #61
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_script
Old path: app/agents/tools.py (`_RUN_SCRIPT_TOOL` schema dict and the
    `run_script_h` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body).
New path: app/tools/execution/run_script.py (this file) —
    `RUN_SCRIPT_TOOL`, `validate_run_script_inputs`, `run_script_handler`.
Affected agents: 1 per tool_inventory.json (chat_agent's own interactive
    dispatch) + `make_chat_handlers()`'s own `run_script` (whichever
    one-shot agents declare it in `allowed_tools`).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch no longer builds a shell string at all, now calls the same
    shared function via `asyncio.to_thread`).
Affected registries: none — app/fleet/tool_manifest.py's "run_script"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_script"](...)` or `ChatAgent._execute_tool`.
    New tests added: see tests/test_run_script_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_script.md.
---------------------------------------------------------------------------

This tool was already flagged as a likely finding during tool #14's
proactive scan (2026-08-17): "`run_script` (~L3038) — `rscr_interp` (the
`interpreter` field) is used AS-IS unquoted whenever it isn't exactly
'auto' ... a custom interpreter value never gets validated or quoted at
all." That scan understated the real severity — see finding #2 below.

Three real, empirically-verified findings:

1. **Classic shell injection, `chat_agent.py`'s dispatch only** (the
   `tools.py` implementation already used list-args, not exposed to
   this one): `interpreter` was interpolated raw into an f-string
   (`f"{rscr_interp} {rscr_fp} 2>&1"`) run via the shell=True
   `_run_subprocess` helper. Proved live:
   `interpreter="cat; touch /tmp/PWNED; echo"` genuinely created the
   marker file alongside the intended script read.

2. **Severe — arbitrary-program execution via `interpreter`, on BOTH
   implementations, including the one already using list-args.**
   Neither implementation restricted `interpreter` to the documented
   set (`'auto', 'python3', 'bash', 'node'`) at all — any other string
   was passed straight through as `argv[0]`, i.e. the actual program to
   execute, with the target script's path as its sole argument. Proved
   live against the ALREADY-LIST-ARGS `tools.py` implementation (no
   shell involved anywhere in this path): `interpreter="rm"` against a
   real file genuinely DELETED it —
   `subprocess.run(["rm", "<path>"])` is exactly the shape of `rm
   <path>`, requiring no flags at all for a single file. This has
   nothing to do with shell metacharacters; it's an LLM (or a
   successful prompt injection) choosing which HOST PROGRAM to run, a
   far broader primitive than the classic injection in finding #1.

3. **Worktree-boundary escape via `path`, on BOTH implementations** —
   same pathlib bug class as tools #10/#11/#18/#23/#43/#59: `root /
   path` silently discards `root` when `path` is absolute. Proved live
   end-to-end: a real script OUTSIDE the repo
   (`/tmp/rs_outside_dir/evil.sh`) was genuinely executed through the
   tool, with real observable side effects (a marker file created at
   the attacker's chosen host path).

Fix: a shared `validate_run_script_inputs()` chokepoint —

- Rejects any `interpreter` other than `"auto"` or one of the exact 3
  documented values (`python3`, `bash`, `node`). This single check
  closes finding #2 completely (no other program name can ever reach
  `argv[0]`) and, combined with removing the shell layer below, closes
  finding #1 too (none of the 4 allowed values contain shell
  metacharacters).
- Validates `path` via `check_path_in_worktree()` (the standard
  chokepoint used throughout this initiative since tool #9), closing
  finding #3.

`chat_agent.py`'s shell=True layer is removed entirely (not quoted
around) in favor of the same list-args `subprocess.run([interpreter,
str(script_fp)], ...)` call `tools.py`'s implementation already used —
matching the tool #59/#60 precedent of eliminating an unnecessary shell
layer rather than trying to `shlex.quote()` safety into it. Since both
real implementations became functionally identical once the shell layer
was gone, they are unified into one shared `run_script_handler()` here,
matching the `run_python_snippet`/`run_node`/`run_make` precedent for
tools where the two real call sites had no genuine behavioral
difference worth preserving separately. The one small formatting
difference (an `[exit N]` suffix on nonzero exit) is kept — it was the
more complete/informative of the two, matching `run_make`'s own
existing style.
"""

from __future__ import annotations

from app.tools.execution import safe_subprocess as subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

_ALLOWED_INTERPRETERS = ("python3", "bash", "node")

RUN_SCRIPT_TOOL = {
    "name": "run_script",
    "description": "Execute a script file (.py, .sh, .js). Auto-detects interpreter from extension.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the script file (relative to repo root)",
            },
            "interpreter": {
                "type": "string",
                "description": "Interpreter to use: 'auto', 'python3', 'bash', 'node' (default: auto). No other value is accepted.",
            },
        },
        "required": ["path"],
    },
}


def validate_run_script_inputs(
    path: str, interpreter: str, worktree_path: str
) -> str | None:
    """Returns an [ERROR] string if inputs are unsafe, else None.

    Rejects any `interpreter` outside the documented allowlist (closes a
    real arbitrary-program-execution primitive, proved live even
    against list-args argv construction — see this module's docstring
    finding #2) and validates `path` stays inside the repo (finding
    #3)."""
    if interpreter != "auto" and interpreter not in _ALLOWED_INTERPRETERS:
        allowed = ", ".join(("auto", *_ALLOWED_INTERPRETERS))
        return (
            f"[ERROR] interpreter must be one of {allowed} — got "
            f"{interpreter!r}. Arbitrary interpreter values are rejected "
            "outright since this tool would otherwise execute any host "
            "program against the target file."
        )
    result = check_path_in_worktree(path, worktree_path)
    if not result.allowed:
        return f"[ERROR] {result.reason}"
    return None


def run_script_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core run_script logic shared by both real call sites."""
    path_rel = str(inp["path"])
    interpreter = str(inp.get("interpreter", "auto"))

    validation_error = validate_run_script_inputs(path_rel, interpreter, worktree_path)
    if validation_error:
        return validation_error

    script_fp = root / path_rel
    if not script_fp.exists():
        return f"[ERROR] Script not found: {path_rel}"

    if interpreter == "auto":
        ext = script_fp.suffix
        interpreter = (
            "python3"
            if ext == ".py"
            else "node" if ext in (".js", ".mjs", ".cjs") else "bash"
        )

    try:
        r = subprocess.run(
            [interpreter, str(script_fp)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        result = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            result += f"\n[exit {r.returncode}]"
        return result or "(no output)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Script timed out after 120s"
    except Exception as e:
        return f"[ERROR] {e}"
