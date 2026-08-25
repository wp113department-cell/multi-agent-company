"""run_linter tool — tool_enhance.md productionization pass, tool #101
(2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: run_linter
Old path: app/agents/tools.py (`_RUN_LINTER_TOOL` schema dict) with
    FOUR real implementations: `sr_run_linter`
    (`make_style_reviewer_handlers`), `td_run_linter`
    (`make_tech_debt_handlers`), `run_linter` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/execution/run_linter.py (this file) —
    `RUN_LINTER_TOOL`, `run_linter_handler`. ALL FOUR real call sites
    now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `run_linter` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its
    `_run_subprocess`/`shell=True` invocation entirely).
Affected registries: none — app/fleet/tool_manifest.py's "run_linter"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_run_linter_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/run_linter.md.
---------------------------------------------------------------------------

FOUR real, empirically-verified findings.

1. **The most severe finding: a genuine, direct shell-injection
   (arbitrary command execution), on `chat_agent.py`'s dispatch.**
   `lint_path` was interpolated COMPLETELY UNQUOTED (not even
   `shlex.quote()`'d, unlike the sibling `make_chat_handlers`
   implementation) into an f-string `shell=True` command. Proved live:
   `path="; touch /tmp/PWNED_RUN_LINTER_SHELL; echo x"` genuinely
   created a real file outside any intended scope — the injected
   command executed for real, same severity class as tool #8's
   `run_migration` shell injection.

2. **A real, severe confirmation/opt-in bypass, on `make_chat_handlers`'
   `run_linter`.** The schema documents `fix` as an explicit,
   default-`False` opt-in boolean ("Auto-fix issues where possible").
   But `path` was placed as a bare positional shell token (protected
   only by `shlex.quote()`, which — per the class already established
   many times this window — protects the SHELL from metacharacters,
   not the receiving program's OWN flag parser) — `ruff` accepts its
   own `--fix` flag. Proved live: `path="--fix"` with the caller's
   `fix` explicitly left at its default `False` genuinely caused ruff
   to auto-fix AND REWRITE A REAL FILE ON DISK (`Found 2 errors (2
   fixed, 0 remaining)`, file content changed) — completely bypassing
   the schema's own documented opt-in contract, similar in spirit to
   tool #5's `git_reset` flag-collision confirmation bypass. `ruff`
   also has a real `-o`/`--output-file <path>` flag (arbitrary-file-
   write primitive) reachable the same way.

3. **A real, severe functionality bug: `sr_run_linter`/`td_run_linter`
   are CURRENTLY COMPLETELY BROKEN for every real call, unrelated to
   security.** Both pass `--output-format=text` to ruff — proved live
   this is not a valid ruff output format (`error: invalid value
   'text' for '--output-format <OUTPUT_FORMAT>'`, exit code 2) —
   EVERY real call to either implementation fails outright. On top of
   that, both implementations ignore the `tool`/`fix` fields entirely
   and always hardcode a ruff-only check — the same "dead/ignored
   field" class already established for tools #24/#82/#90/#99.

4. **A real, documented-but-unimplemented gap: `tool="eslint"` is a
   valid enum value in the schema, but NO implementation ever
   supported it** — `run_linter`/`chat_agent.py`'s dispatch would
   return `[ERROR] Unknown linter: eslint`, and `sr_`/`td_` would
   silently run ruff instead and ignore the request entirely. Verified
   `apps/web/package.json` genuinely configures eslint (`"lint":
   "eslint ."`) — a real, available capability the schema promised but
   no implementation ever wired up.

Fixed via a shared `run_linter_handler()`:
 - **structural fix for finding #1/#2, not just validation**: all
   subprocess calls are now LIST-ARGS (no `shell=True` at all,
   anywhere) — this eliminates the shell-injection class by
   construction, not by quoting, and eliminates the
   flag-vs-quoting confusion class the same way;
 - `path`, when given, is additionally validated via
   `check_path_in_worktree()` and rejected if flag-shaped (starts with
   `-`) — defense in depth even though list-args already prevents it
   from being consumed as a *shell* command, an explicit `--` /
   positional-only argv position closes it from being consumed as
   ruff's/black's/mypy's own flag too;
 - `--output-format=text` replaced with ruff's actual default (no flag
   passed at all) — closes finding #3's total breakage;
 - `tool`/`fix` are now read and honored identically across all four
   real call sites — closes finding #3's dead-field bug;
 - real `eslint` support added (`npx eslint .` in `apps/web/`, mirroring
   the existing `tsc` invocation shape exactly) — closes finding #4.

Venv activation no longer goes through a shell snippet
(`_venv_activate_snippet()`) at all — list-args calls invoke the
venv's own `python` binary directly by path when it exists
(`.venv/bin/python` / `.venv\\Scripts\\python.exe`), falling back to
`sys.executable` — simpler and shell-free.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.agents.output_parsers import parse_diagnostic_summary
from app.policy.engine import check_path_in_worktree

MAX_OUTPUT_CHARS = 2000


def _validate_lint_path(path: str, worktree_path: str) -> str | None:
    """Returns an [ERROR] string if `path` is unsafe, else None."""
    if not path:
        return None
    if path.startswith("-"):
        return (
            f"[ERROR] path must not look like a command-line flag: {path!r} — "
            "the linter would interpret a leading '-' as its own option "
            "(e.g. ruff's own --fix/-o flags) rather than a target path."
        )
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"
    return None


def _python_executable(root: Path) -> str:
    """Path to the project's own venv Python if present, else the
    current interpreter — no shell snippet needed since every call
    here is list-args, never shell=True."""
    if sys.platform == "win32":
        venv_python = root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _run(args: list[str], cwd: str, timeout: int) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return (r.stdout + r.stderr)[:MAX_OUTPUT_CHARS] or "clean"
    except subprocess.TimeoutExpired:
        return "[ERROR] Linter timed out"
    except FileNotFoundError as e:
        return f"[ERROR] {e}"


def run_linter_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core run_linter logic shared by all four real call sites."""
    tool = str(inp.get("tool", "all"))
    path = str(inp.get("path", ""))
    fix = bool(inp.get("fix", False))

    error = _validate_lint_path(path, worktree_path)
    if error:
        return error

    target = str(root / path) if path else str(root)
    py = _python_executable(root)
    results: list[str] = []

    if tool in ("ruff", "all"):
        args = [py, "-m", "ruff", "check", target]
        if fix:
            args.append("--fix")
        ruff_out = _run(args, str(root), 60)
        summary = parse_diagnostic_summary(ruff_out, "ruff")
        results.append(f"=== ruff ==={f' {summary}' if summary else ''}\n{ruff_out}")

    if tool in ("mypy", "all"):
        args = [py, "-m", "mypy", target, "--ignore-missing-imports"]
        mypy_out = _run(args, str(root), 90)
        summary = parse_diagnostic_summary(mypy_out, "mypy")
        results.append(f"=== mypy ==={f' {summary}' if summary else ''}\n{mypy_out}")

    if tool in ("tsc", "all"):
        web = str(root.parent / "apps" / "web")
        tsc_out = _run(["npx", "tsc", "--noEmit"], web, 90)
        summary = parse_diagnostic_summary(tsc_out, "tsc")
        results.append(f"=== tsc ==={f' {summary}' if summary else ''}\n{tsc_out}")

    if tool == "eslint":
        web = str(root.parent / "apps" / "web")
        eslint_out = _run(["npx", "eslint", "."], web, 90)
        summary = parse_diagnostic_summary(eslint_out, "eslint")
        results.append(f"=== eslint ==={f' {summary}' if summary else ''}\n{eslint_out}")

    if tool == "black":
        args = [py, "-m", "black"]
        if not fix:
            args.append("--check")
        args.append(target)
        black_out = _run(args, str(root), 60)
        results.append(f"=== black ===\n{black_out}")

    return "\n\n".join(results) if results else f"[ERROR] Unknown linter: {tool}"


RUN_LINTER_TOOL = {
    "name": "run_linter",
    "description": "Run linting and type-checking tools. Returns errors and warnings. Fix these before declaring a task complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "string",
                "enum": ["ruff", "mypy", "tsc", "eslint", "black", "all"],
                "description": "Linter to run (default: all — runs ruff + mypy for Python, tsc for TypeScript)",
            },
            "path": {
                "type": "string",
                "description": "Path to lint (default: backend/ or apps/web/)",
            },
            "fix": {
                "type": "boolean",
                "description": "Auto-fix issues where possible (ruff only, default: false)",
            },
        },
        "required": [],
    },
}
