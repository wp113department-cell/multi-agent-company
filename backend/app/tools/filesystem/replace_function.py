"""replace_function tool — tool_enhance.md productionization pass, tool
#24 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: replace_function
Old path: app/agents/tools.py (`_REPLACE_FUNCTION_TOOL` schema dict and
    the `replace_function`/`rf_replace_function` handlers) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/filesystem/replace_function.py (this file) —
    `REPLACE_FUNCTION_TOOL`, `replace_function_handler`.
Affected agents: 2 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch and `refactor_agent` (via `rf_replace_function`,
    the broken one — see below). `make_chat_handlers`'s own
    `replace_function` is also reachable by any other agent declaring
    this tool.
Affected modules: app/agents/tools.py (compatibility re-export;
    `rf_replace_function` and `make_chat_handlers`'s own
    `replace_function` both now delegate to the shared handler),
    app/agents/chat_agent.py (its real dispatch now calls the shared
    handler directly).
Affected registries: none — app/fleet/tool_manifest.py's
    "replace_function" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["replace_function"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_replace_function_hardening.py, including new coverage of
    `refactor_agent`'s own handler (previously untestable — it always
    raised).

Runtime verification: PASS — see
    backend/docs/tool_productionization/replace_function.md.
---------------------------------------------------------------------------

Real finding (severe — a genuine "this feature has never worked" bug,
found while auditing this tool's already-worktree-fixed implementations
from tool #11): `refactor_agent`'s `rf_replace_function` read
`inp["new_body"]`, but `REPLACE_FUNCTION_TOOL`'s own schema — the one
`refactor_agent` itself advertises to its LLM — documents the field as
`new_code`. Proved directly: a real call built exactly the way the
schema instructs (`{"path": ..., "function_name": ..., "new_code":
...}`) raised an unhandled `KeyError('new_body')` inside the handler.
The agent framework catches this centrally (`_run_tool_with_retry` in
app/agents/base_graph.py turns any handler exception into an
`[ERROR] ... raised: ...` string, so it never crashes a whole run) — but
every real `refactor_agent` call to this tool has failed 100% of the
time since it was written, silently, with no test ever having caught it
(the field-name typo meant a hand-constructed test dict using the wrong
key by coincidence would have "worked" while never exercising a real
schema-conformant call).

A second, related gap in the same handler: its regex only matched
UNINDENTED (top-level) function definitions (anchored on a line
starting with "def"/"async def" with no leading whitespace allowed) —
it could never match a class method. Both
`chat_agent.py`'s dispatch and `make_chat_handlers`'s own implementation
already handle methods correctly (they `.strip()` each line before
comparing, so indentation doesn't exclude a match). Rather than fix the
regex version's two independent bugs in place, this pass switches
`rf_replace_function` onto the shared, already-correct, already-used-by-
two-other-call-sites implementation — a strict capability increase (top-
level functions it could already find, PLUS methods it never could), not
a narrowing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path

REPLACE_FUNCTION_TOOL = {
    "name": "replace_function",
    "description": "Replace an entire function/method definition in a Python file. Finds by name and replaces the full block.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Python file path relative to repo root",
            },
            "function_name": {
                "type": "string",
                "description": "Name of the function or method to replace",
            },
            "new_code": {
                "type": "string",
                "description": "Complete new function code (def line + body, properly indented)",
            },
        },
        "required": ["path", "function_name", "new_code"],
    },
}


def replace_function_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core replace_function logic shared by every real call site.
    Finds `def <name>(`/`async def <name>(` at ANY indentation level
    (top-level function or class method) by scanning stripped lines, then
    replaces through the next same-or-lower-indent, non-continuation
    line (a blank line, decorator, or comment doesn't end the block)."""
    rel = str(inp["path"])
    func_name = str(inp["function_name"])
    new_code = str(inp["new_code"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Cannot write to protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        start: int | None = None
        indent = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"def {func_name}(") or stripped.startswith(
                f"async def {func_name}("
            ):
                start = i
                indent = len(line) - len(line.lstrip())
                break
        if start is None:
            return f"[ERROR] Function '{func_name}' not found in {rel}"
        end = len(lines)
        for j in range(start + 1, len(lines)):
            jline = lines[j]
            if jline.strip() == "":
                continue
            jindent = len(jline) - len(jline.lstrip())
            if (
                jindent <= indent
                and jline.strip()
                and not jline.strip().startswith(("#", "@"))
            ):
                end = j
                break
        new_final = new_code if new_code.endswith("\n") else new_code + "\n"
        result = lines[:start] + [new_final] + lines[end:]
        target.write_text("".join(result), encoding="utf-8")
        return f"Replaced '{func_name}' in {rel} (lines {start + 1}-{end})"
    except Exception as e:
        return f"[ERROR] {e}"
