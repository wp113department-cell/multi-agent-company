"""review_diff tool — tool_enhance.md productionization pass, tool
#179 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: review_diff
Old path: app/agents/tools.py (`_REVIEW_DIFF_TOOL` schema dict,
    `review_diff` inside `make_chat_handlers()`) AND
    app/agents/chat_agent.py (its own separate, line-for-line
    duplicated `if tool_name == "review_diff":` dispatch body) — TWO
    real, independently vulnerable implementations of the exact same
    `base` → `git diff <base>...HEAD` argument-building logic.
New path: app/tools/git/review_diff.py (this file) —
    `REVIEW_DIFF_TOOL`, `build_review_diff_args` (the one shared,
    fixed piece of logic both call sites now use).
Affected agents: per tool_inventory.json, agents declaring
    `review_diff` in `allowed_tools` (both `make_chat_handlers()`-
    based one-shot agents and interactive chat — both real call
    sites were vulnerable).
Affected modules: app/agents/tools.py (`review_diff` now calls the
    shared arg builder before running its own subprocess calls, its
    own stdout-only capture behavior otherwise unchanged),
    app/agents/chat_agent.py (its dispatch now calls the same shared
    arg builder before its own `_git()` calls, its own combined-
    stdout+stderr/timeout/"(no output)" behavior otherwise
    unchanged — deliberately NOT unified into one handler, since the
    two callers have genuinely different, pre-existing subprocess-
    invocation conventions and unifying them would be an unnecessary
    rewrite of otherwise-working code; only the vulnerable arg-
    building step is shared).
Affected registries: none — app/fleet/tool_manifest.py's
    "review_diff" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_review_diff_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/review_diff.md.
---------------------------------------------------------------------------

Real, SEVERE finding on BOTH real implementations (identical logic,
duplicated verbatim): a flag-collision bug, same class as tools
#5/#32/#148/#149/#153/#158, but here escalating to a genuine
ARBITRARY FILE WRITE with real content, not just a misinterpreted
read. `base` was embedded unguarded into a single argv token
(`f"{base}...HEAD"`) handed to `git diff` via list-args
`subprocess.run` (no `shell=True` — so this is NOT a shell-injection
bug; it is git's OWN argument parser being fed a flag it accepts).
Proved live against a real git repository with real uncommitted
changes:
- `base = "--upload-pack=<cmd>"` → git correctly rejected it as an
  unrecognized diff option (`error: invalid option`) — this specific
  flag is NOT accepted by `git diff` in this position, REFUTED as an
  attack vector for command execution.
- `base = "--output=/tmp/<attacker-chosen-path>"` → **genuinely
  wrote the real diff output (actual file content, actual code
  changes) to an attacker-chosen filesystem path** — proved live
  with a real unstaged change, the written file's content was
  confirmed to be the real, exact diff text. The final path carries a
  literal `...HEAD` suffix (from the unguarded string concatenation),
  which the attacker cannot avoid but can otherwise fully choose the
  prefix of — a genuine, severe arbitrary-file-write primitive using
  attacker-controlled content (the repo's own diff), not merely an
  attacker-chosen empty file.

Fixed the same way as every other flag-collision finding this
initiative: `base` is now rejected outright with `[ERROR]` whenever it
starts with `-`, via the one shared `build_review_diff_args()`,
BEFORE either call site's subprocess invocation. `staged_only` was
never attacker-influenceable in a dangerous way (a plain bool,
controls only `--cached` vs no flag) and is unchanged.
"""

from __future__ import annotations

from typing import Any

REVIEW_DIFF_TOOL: dict[str, Any] = {
    "name": "review_diff",
    "description": "LLM-generated structured review of a real git diff — summary, risk callouts, and notable omissions grounded strictly in the diff content. Distinct from git_diff, which returns only raw stdout.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staged_only": {
                "type": "boolean",
                "description": "Review only staged changes (default: true)",
            },
            "base": {
                "type": "string",
                "description": "If set, review the diff against this ref/branch instead of staged/unstaged working-tree changes",
            },
        },
        "required": [],
    },
}


def build_review_diff_args(inp: dict[str, Any]) -> list[str] | str:
    """Build the `git diff ...` argument list for review_diff, shared by
    both real call sites. Returns the arg list on success, or an
    `[ERROR]` string if `base` is flag-shaped (closing the arbitrary-
    file-write finding — see module docstring) — callers must check
    `isinstance(result, str)` and return it directly in that case."""
    staged_only = bool(inp.get("staged_only", True))
    base = str(inp.get("base", "")).strip()
    if base.startswith("-"):
        return f"[ERROR] review_diff: 'base' must be a ref/branch name, not a flag: {base!r}"
    if base:
        return ["diff", f"{base}...HEAD"]
    if staged_only:
        return ["diff", "--cached"]
    return ["diff"]
