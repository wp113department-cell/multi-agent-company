"""find_function_body tool — tool_enhance.md productionization pass,
tool #111 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: find_function_body
Old path: app/agents/tools.py (`_FIND_FUNCTION_BODY_TOOL` schema dict)
    with FOUR real implementations: `bf_find_function_body`
    (`make_bug_fix_handlers`), `rf_find_function_body`
    (`make_refactor_agent_handlers`), `find_function_body` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch.
New path: app/tools/filesystem/find_function_body.py (this file) —
    `FIND_FUNCTION_BODY_TOOL`, `find_function_body_handler`. ALL FOUR
    real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `find_function_body` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler — `bf_`/`rf_find_function_body` are
    fully replaced, see finding #1 below), app/agents/chat_agent.py
    (its dispatch now calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "find_function_body" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the three handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_find_function_body_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/find_function_body.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **A real, severe functionality bug: `bf_find_function_body` and
   `rf_find_function_body` are BOTH completely broken, in three
   separate ways.** They read `inp["name"]` — but the schema declares
   the field as `function_name`, never `name`. Proved live: any real,
   schema-conformant call (`{"path": ..., "function_name": ...}`)
   raises an uncaught `KeyError: 'name'` — a 100% crash rate. On top
   of that, even if the field name were fixed, both implementations
   also completely ignore `path` (they `grep -rn` the ENTIRE repo
   instead of reading the specified file) and never actually extract
   "the complete source code... including its body" as the schema
   promises — they return raw `grep` match lines (just the `def ...`
   signature line itself), not the function body. Same "dead/wrong
   field read" class already established for tools #24/#82/#90/#91.

2. **Worktree-boundary escape, on the two already-correct
   implementations (`find_function_body` in `make_chat_handlers` and
   `chat_agent.py`'s dispatch).** Neither validated `path` before
   `root / path` — an absolute path discards `root` entirely (pathlib
   behavior). Proved live: `find_function_body({"path":
   "/tmp/outside/secret.py", "function_name": "leaked_secret_function"})`
   genuinely read and returned the COMPLETE SOURCE of a function from a
   file completely outside the repo — a severe file-disclosure
   primitive, made worse by this tool's own explicit purpose being to
   dump out full function source.

Fixed via a shared `find_function_body_handler()`: `path` is validated
via `check_path_in_worktree()` — closes finding #2. `bf_`/
`rf_find_function_body` are fully replaced by this shared, correct
handler (adopting the real, working `path`+`function_name`-based
line-scan extraction already proven correct by the other two call
sites) rather than kept as second, broken implementations — closes
finding #1, a genuine capability increase (real body extraction
instead of a crash) for those two call sites, not a narrowing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree


def find_function_body_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core find_function_body logic shared by all four real call sites."""
    rel = str(inp["path"])
    function_name = str(inp["function_name"])

    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fp = root / rel
    if not fp.exists():
        return f"[ERROR] File not found: {rel}"

    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    start: int | None = None
    base_indent = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(f"def {function_name}(") or s.startswith(
            f"async def {function_name}("
        ):
            start = i
            base_indent = len(line) - len(line.lstrip())
            break
    if start is None:
        return f"[ERROR] Function '{function_name}' not found in {rel}"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if (
            indent <= base_indent
            and line.strip()
            and not line.strip().startswith(("@", "#"))
        ):
            end = j
            break

    body = "".join(lines[start:end])
    return f"=== {function_name} (lines {start + 1}-{end}) ===\n{body}"


FIND_FUNCTION_BODY_TOOL = {
    "name": "find_function_body",
    "description": "Extract the complete source code of a named function or method, including its body.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "function_name": {
                "type": "string",
                "description": "Name of the function or method to extract",
            },
        },
        "required": ["path", "function_name"],
    },
}
