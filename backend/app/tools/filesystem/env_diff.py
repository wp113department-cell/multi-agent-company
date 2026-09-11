"""env_diff tool — tool_enhance.md productionization pass, tool #135
(2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: env_diff
Old path: app/agents/tools.py (`_ENV_DIFF_TOOL` schema dict,
    `env_diff_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/env_diff.py (this file) —
    `ENV_DIFF_TOOL`, `env_diff_handler`.
Affected agents: per tool_inventory.json, agents declaring `env_diff`
    in `allowed_tools` (plus interactive chat, newly — see finding
    #3).
Affected modules: app/agents/tools.py (`env_diff_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's "env_diff"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_env_diff_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/env_diff.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **Worktree-boundary escape on BOTH `example` and `actual` — a
   genuine ENVIRONMENT-VARIABLE-NAME DISCLOSURE oracle.** `env_diff_h`
   built `root / str(inp.get("example", ...))` and `root /
   str(inp.get("actual", ...))` without checking whether either was
   already absolute — the same `pathlib`-silently-discards-`root`-
   for-an-absolute-right-operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134 this initiative. Even
   though this tool never returns variable *values* (only key names),
   the key names of an arbitrary `.env`-shaped file anywhere on the
   host are themselves sensitive — they can confirm which secrets
   (`AWS_SECRET_ACCESS_KEY`, `STRIPE_API_KEY`, etc.) an unrelated
   project on the same host uses. Proved live: pointing both fields at
   real files outside the intended worktree genuinely disclosed a key
   name (`EXTRA_OUTSIDE_ONLY_KEY`) unique to the outside file.
2. **A real robustness gap — an uncaught crash on a real permission
   error.** Neither `_keys()`'s `fp.read_text()` call was wrapped in a
   `try/except`, same class already fixed for tools #70/#72/#76.
   Proved live with a real `chmod 000` file: a genuine
   `PermissionError` propagated straight out of the handler.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134.**
   `env_diff` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: env_diff"`.

Fixed via a shared `env_diff_handler()`: both `example` and `actual`
are validated for worktree containment before any filesystem access,
closing finding #1. `_keys()` now catches read errors and returns an
empty set with the error noted, closing finding #2 without turning a
legitimate "one file present, one absent" comparison into a hard
failure. A new `chat_agent.py` dispatch branch delegates to this same
shared handler, closing finding #3.

**A deliberate departure from the usual `check_path_in_worktree()`
reuse**: that function also runs the general secrets/`.env` DENYLIST
(`app/policy/engine.py::_matches_path_rule`) on top of the worktree
check — appropriate for tools that return file *content*, but this
tool's entire documented purpose is comparing `.env`/`.env.example`-
shaped files by KEY NAME ONLY; it never returns values. Reusing the
full denylist verbatim would have broken the tool's own default
behavior outright (verified live: `.env.example`/`.env` with no
arguments — the tool's documented default — was rejected with
`"[POLICY DENIED] ... matches .env pattern"` before this was caught
and fixed). `_worktree_boundary_only()` below replicates exactly the
worktree-containment logic from `check_path_in_worktree()`
(realpath-based, symlink-safe) without the denylist, since disclosing
only key *names* — never values — does not carry the same risk the
denylist exists to prevent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _worktree_boundary_only(file_path: str, worktree_path: str) -> str | None:
    """Same worktree-containment check as
    `app.policy.engine.check_path_in_worktree()`, deliberately WITHOUT
    its `.env`/secrets denylist — see this module's own docstring for
    why that denylist is inapplicable here. Returns a denial reason,
    or None if the path stays inside the worktree."""
    abs_worktree = os.path.realpath(os.path.abspath(worktree_path))
    candidate = (
        file_path if os.path.isabs(file_path) else os.path.join(abs_worktree, file_path)
    )
    abs_file = os.path.realpath(candidate)
    if not (abs_file == abs_worktree or abs_file.startswith(abs_worktree + os.sep)):
        return f"path {file_path!r} escapes worktree boundary {worktree_path!r}"
    return None

ENV_DIFF_TOOL: dict[str, Any] = {
    "name": "env_diff",
    "description": "Compare .env.example with .env (or a named env file) to find missing or extra variables.",
    "input_schema": {
        "type": "object",
        "properties": {
            "example": {
                "type": "string",
                "description": "Path to example env file (default: .env.example)",
            },
            "actual": {
                "type": "string",
                "description": "Path to actual env file (default: .env)",
            },
        },
        "required": [],
    },
}


def _keys(fp: Path) -> tuple[set[str], str | None]:
    if not fp.exists():
        return set(), None
    try:
        text = fp.read_text(encoding="utf-8")
    except Exception as e:
        return set(), str(e)
    keys: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys, None


def env_diff_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core env_diff logic — the one real implementation, reused
    unchanged in behavior except for the worktree-boundary check now
    applied to both fields and the read-error crash fix."""
    example_rel = str(inp.get("example", ".env.example"))
    actual_rel = str(inp.get("actual", ".env"))

    denial = _worktree_boundary_only(example_rel, worktree_path)
    if denial:
        return f"[POLICY DENIED] {denial}"
    denial = _worktree_boundary_only(actual_rel, worktree_path)
    if denial:
        return f"[POLICY DENIED] {denial}"

    example_keys, example_err = _keys(root / example_rel)
    actual_keys, actual_err = _keys(root / actual_rel)
    if example_err:
        return f"[ERROR] Could not read {example_rel}: {example_err}"
    if actual_err:
        return f"[ERROR] Could not read {actual_rel}: {actual_err}"

    missing = sorted(example_keys - actual_keys)
    extra = sorted(actual_keys - example_keys)
    lines = []
    if missing:
        lines.append(f"Missing in {actual_rel} ({len(missing)}):")
        lines.extend(f"  - {k}" for k in missing)
    if extra:
        lines.append(f"Extra in {actual_rel} (not in example, {len(extra)}):")
        lines.extend(f"  + {k}" for k in extra)
    if not missing and not extra:
        lines.append("✅ No differences — .env matches .env.example")
    return "\n".join(lines)
