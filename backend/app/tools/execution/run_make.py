"""run_make tool — tool_enhance.md productionization pass, tool #59
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_make
Old path: app/agents/tools.py (`_RUN_MAKE_TOOL` schema dict and the
    `run_make` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body).
New path: app/tools/execution/run_make.py (this file) — `RUN_MAKE_TOOL`,
    `validate_run_make_inputs`, `run_make_handler`.
Affected agents: 1 per tool_inventory.json (chat_agent's own interactive
    dispatch) + `make_chat_handlers()`'s own `run_make` (whichever
    one-shot agents declare it in `allowed_tools`).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the same shared function via `asyncio.to_thread`
    instead of duplicating the subprocess logic inline with the
    shell=True `_run_subprocess` helper).
Affected registries: none — app/fleet/tool_manifest.py's "run_make"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["run_make"](...)` or `ChatAgent._execute_tool`.
    New tests added: see tests/test_run_make_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_make.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings:

1. **Classic shell injection in `chat_agent.py`'s real dispatch only**
   (the `tools.py` implementation already used list-args, not exposed to
   this one). `target` was interpolated raw into an f-string
   (`f"make {make_target}"`) then run via `_run_subprocess(..., shell=
   True, ...)`. Proved live: `target="build; touch /tmp/PWNED; echo"`
   genuinely created the marker file, arbitrary command execution
   alongside the intended `make build`.

2. **A second, independent code-execution primitive that affects BOTH
   implementations, including the one already using list-args** — GNU
   Make's own argument parser recognizes flag-shaped values even when
   passed as a single argv element with no shell involved. Proved live
   against the ALREADY-LIST-ARGS `tools.py` implementation (no shell=
   True anywhere in this path): `target="--eval=$(shell touch
   /tmp/PWNED)"` was accepted by `make` as its own `--eval` flag, which
   evaluates arbitrary Makefile syntax — and `$(shell ...)` inside that
   evaluated syntax runs an arbitrary shell command. This is NOT a
   Python-level shell-injection bug; it's `make` itself interpreting an
   attacker-controlled "target" string as an option. List-args argv
   construction, which closes the classic shell-injection class
   elsewhere in this initiative (tools #16/#18/#19/#20/#21), does
   nothing to prevent this.

3. **Worktree-boundary escape via `directory`, on BOTH implementations**
   — same root-cause pathlib bug class as tools #10/#11/#18/#23/#43:
   `root / directory` silently discards `root` entirely when `directory`
   is an absolute path. Proved live end-to-end: `directory=
   "/tmp/rm_outside_dir"` (a real directory outside the repo, containing
   its own real Makefile with an `evil` target that touches a marker
   file) had that marker file genuinely created — `make` ran a real,
   attacker-controlled target from OUTSIDE the repo entirely, with no
   restriction.

Fix: a shared `validate_run_make_inputs()` chokepoint —

- Rejects any `target` starting with `-` outright. This single check
  closes finding #2 completely (GNU make's own flags — `--eval`, `-f`,
  `-C`, etc. — all require a leading `-`) and is deliberately broader
  than an allowlist of specific dangerous flags, since `make`'s flag
  surface is large and this tool has no legitimate need for a
  flag-shaped target value in the first place (real Makefile targets
  are plain names).
- Validates `directory` via `check_path_in_worktree()` (the standard
  chokepoint used throughout this initiative since tool #9), closing
  finding #3.

Finding #1 (the classic shell-injection layer) is closed by switching
`chat_agent.py`'s dispatch off the shell=True `_run_subprocess` helper
entirely, onto the same list-args `subprocess.run(["make", target],
...)` call `tools.py`'s implementation already correctly used — not by
attempting to `shlex.quote()` around a shell layer that has no reason to
exist here. Since both real implementations now share byte-identical
logic (list-args execution + the same validator + the same target-
listing branch when `target` is empty), they're unified into one shared
`run_make_handler()` here, matching the `run_python_snippet`/
`replace_class`/`rename_file` precedent for tools where the two real
call sites had no genuine behavioral difference worth preserving
separately.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

RUN_MAKE_TOOL = {
    "name": "run_make",
    "description": "Run a Makefile target. Lists available targets if no target specified.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Make target to run (e.g. 'test', 'build', 'lint'). Leave empty to list.",
            },
            "directory": {
                "type": "string",
                "description": "Directory containing Makefile (default: repo root)",
            },
        },
        "required": [],
    },
}


def validate_run_make_inputs(
    target: str, directory: str, worktree_path: str
) -> str | None:
    """Returns an [ERROR] string if inputs are unsafe, else None.

    Rejects a flag-shaped `target` (closes GNU make's own `--eval`/`-f`/
    `-C`-style option-injection, real and proven even with list-args argv
    construction — see this module's docstring finding #2) and validates
    `directory` stays inside the repo (finding #3)."""
    if target and target.startswith("-"):
        return (
            f"[ERROR] target must not look like a command-line flag: "
            f"{target!r} — GNU make's own flags (e.g. --eval, -f, -C) can "
            "run arbitrary code even with no shell involved, so "
            "flag-shaped target values are rejected outright."
        )
    if directory:
        result = check_path_in_worktree(directory, worktree_path)
        if not result.allowed:
            return f"[ERROR] {result.reason}"
    return None


def run_make_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core run_make logic shared by both real call sites."""
    target = str(inp.get("target", ""))
    directory_rel = str(inp.get("directory", ""))

    validation_error = validate_run_make_inputs(target, directory_rel, worktree_path)
    if validation_error:
        return validation_error

    make_dir = (root / directory_rel) if directory_rel else root
    if not (make_dir / "Makefile").exists() and not (make_dir / "makefile").exists():
        return f"[ERROR] No Makefile found in {make_dir}"

    if not target:
        try:
            r = subprocess.run(
                ["make", "-pRrq"],
                cwd=str(make_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            return f"[ERROR] {e}"
        tgts: list[str] = []
        for mk_line in r.stdout.splitlines():
            if mk_line and not mk_line.startswith(("\t", "#", " ")) and ":" in mk_line:
                tgt = mk_line.split(":")[0].strip()
                if tgt and not tgt.startswith(".") and " " not in tgt:
                    tgts.append(tgt)
        return (
            "Targets:\n" + "\n".join(sorted(set(tgts[:30])))
            if tgts
            else "Makefile found but targets not parseable"
        )

    try:
        r = subprocess.run(
            ["make", target],
            cwd=str(make_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (r.stdout + r.stderr)[:5000] or f"make {target} complete"
    except subprocess.TimeoutExpired:
        return f"[ERROR] make {target} timed out"
    except Exception as e:
        return f"[ERROR] {e}"
