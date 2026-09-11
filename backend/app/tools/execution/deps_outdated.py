"""deps_outdated tool — tool_enhance.md productionization pass, tool
#134 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: deps_outdated
Old path: app/agents/tools.py (`_DEPS_OUTDATED_TOOL` schema dict,
    `deps_outdated_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/execution/deps_outdated.py (this file) —
    `DEPS_OUTDATED_TOOL`, `deps_outdated_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `deps_outdated` in `allowed_tools` (plus interactive chat, newly —
    see finding #3).
Affected modules: app/agents/tools.py (`deps_outdated_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's
    "deps_outdated" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_deps_outdated_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/deps_outdated.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **Severe: a worktree-boundary escape, on the `npm` branch —
   `directory` was passed straight to `subprocess.run(..., cwd=
   target_dir)` without validation.** `target_dir = str(root /
   directory)` never checked whether `directory` was already
   absolute — the same `pathlib`-silently-discards-`root`-for-an-
   absolute-right-operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132 this initiative, but here it
   changes the *working directory of an external program invocation*
   rather than a plain file read, letting `npm outdated` run — with
   its own network calls and any configured npm lifecycle hooks —
   against an arbitrary host directory. Proved live: a real fake
   `npm` script placed on `PATH` reported its own `cwd` was genuinely
   the injected absolute `directory`, not anything inside the intended
   worktree.
2. **A real correctness bug: `has_npm` was computed but never used**
   (marked `# noqa: F841` — a linter suppression for code someone
   already knew was unused, same dead-code-from-incomplete-logic class
   as tool #130's `cpu_profile`). The `auto` manager-detection logic
   was `manager = "pip" if has_pip else "npm"` — meaning a directory
   with NEITHER `requirements.txt`/`pyproject.toml` NOR
   `package.json` still silently defaulted to `"npm"`, and because
   `npm outdated` exits cleanly with empty output when run against a
   directory with no `package.json`, the tool then returned the
   misleading `"✅ All dependencies are up to date"` — a false
   positive — instead of reporting that no recognized package manager
   was found at all. Proved live: a directory with none of the three
   manifest files still returned the "up to date" success message.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133.**
   `deps_outdated` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: deps_outdated"`.

Note (documented, not changed): for `manager == "pip"`, `directory` has
always had zero effect — `pip list --outdated` inspects the active
Python environment, not a directory's manifest file, and the original
implementation never passed `cwd=` for that branch either. This is an
inherent limitation of `pip list`'s own design (there is no clean way
to scope it to an arbitrary directory without parsing
`requirements.txt` directly, a materially different mechanism), not a
bug to fix here — left as-is, matching this initiative's precedent for
noting a real but out-of-scope-for-a-clean-fix limitation rather than
force-changing unrelated behavior.

Fixed via a shared `deps_outdated_handler()`: `directory` is validated
with `check_path_in_worktree()` before being used as a subprocess
`cwd`, closing finding #1. The `auto` branch now genuinely uses
`has_npm` and returns a clear message when neither manager's manifest
file is present, closing finding #2. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #3.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

DEPS_OUTDATED_TOOL: dict[str, Any] = {
    "name": "deps_outdated",
    "description": "Check for outdated pip or npm dependencies. Returns package name, current version, and latest version.",
    "input_schema": {
        "type": "object",
        "properties": {
            "manager": {
                "type": "string",
                "enum": ["pip", "npm", "auto"],
                "description": "Package manager (default: auto-detect)",
            },
            "directory": {
                "type": "string",
                "description": "Directory to check (default: repo root)",
            },
        },
        "required": [],
    },
}


def deps_outdated_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core deps_outdated logic — the one real implementation."""
    manager = str(inp.get("manager", "auto"))
    directory = str(inp.get("directory", "."))

    if manager == "auto":
        has_pip = (root / "requirements.txt").exists() or (
            root / "pyproject.toml"
        ).exists()
        has_npm = (root / "package.json").exists()
        if has_pip:
            manager = "pip"
        elif has_npm:
            manager = "npm"
        else:
            return (
                "(no recognized package manager found — no requirements.txt, "
                "pyproject.toml, or package.json)"
            )

    try:
        if manager == "pip":
            r = subprocess.run(
                ["pip", "list", "--outdated", "--format=columns"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:
            # Matches the original's exact branching: anything that
            # isn't literally "pip" (after auto-resolution, this is
            # always "npm") reaches here.
            policy = check_path_in_worktree(directory, worktree_path)
            if not policy.allowed:
                return f"[POLICY DENIED] {policy.reason}"
            target_dir = str(root / directory)
            r = subprocess.run(
                ["npm", "outdated"],
                capture_output=True,
                text=True,
                cwd=target_dir,
                timeout=60,
            )
        return r.stdout.strip() or "✅ All dependencies are up to date"
    except Exception as e:
        return f"[ERROR] deps_outdated: {e}"
