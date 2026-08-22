"""analyze_file tool — tool_enhance.md productionization pass, tool
#76 (2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: analyze_file
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[15]` schema dict and the
    `analyze_file` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate, less complete inline dispatch
    body).
New path: app/tools/filesystem/analyze_file.py (this file) —
    `ANALYZE_FILE_TOOL`, `analyze_file_handler`.
Affected agents: per tool_inventory.json, 61 agents declare
    `analyze_file` in `allowed_tools`. UNLIKE tools #65/#67/#68/#70/#71/
    #72/#73/#74/#75, the vulnerability here affected the CANONICAL
    `make_read_only_handlers()` factory itself, not just
    `chat_agent.py`'s separate dispatch — meaning every real caller
    (every `run_agent_graph`-based agent, `make_chat_handlers()`'s ~35
    one-shot agents, AND the interactive chat session) was exposed, the
    widest blast radius of any finding in the low-risk tier so far.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[15]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `analyze_file` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "analyze_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["analyze_file"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_analyze_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/analyze_file.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **Worktree-boundary escape, on BOTH implementations, including the
   canonical `make_read_only_handlers()` factory.** Neither called
   `check_path_in_worktree()` at all — `root / rel` (the usual pathlib
   bug from tools #10/#11/#18/#23/#43/#59/#61/#62/#64/#65/#67/#68/#70/
   #71/#72/#74) let `path` resolve to any absolute host path. Proved
   live on BOTH real call sites: `analyze_file({"path":
   "/etc/passwd"})` genuinely analyzed the real content of a host file
   completely outside the repo, disclosing its real line count (and,
   for a source file, would disclose real import statements and
   function/class signatures — up to 30 imports and 50 definitions,
   echoing real file content, not just size/type metadata like tool
   #72's `file_info` finding).

2. **An uncaught `PermissionError`, on BOTH implementations — same
   finding class as tools #70/#72.** The canonical implementation's own
   `try/except Exception` around `read_text()` did NOT cover the
   earlier `p.exists()` call, which itself raises `PermissionError`
   when the parent directory is inaccessible. Proved live with a real
   file inside a `chmod 000` parent directory: BOTH implementations
   raised the same uncaught exception.

3. **A real functionality-parity gap between the two implementations
   (not present in prior READ_ONLY_TOOLS turns, which were either
   fully identical or had only cosmetic wording differences).** The
   canonical implementation recognizes 12 TypeScript/JS definition
   prefixes (`export function `, `export async function `, `export
   class `, `export const `, `export default `, `export interface `,
   `export type `, plus the NON-exported forms `function `, `const `,
   `class `, `interface `, `type `) gated behind an additional
   `"=" in stripped or "(" in stripped or "{" in stripped` sanity
   check; `chat_agent.py`'s dispatch recognized only 10 forms, missing
   every NON-exported form (`function `, `const `, `interface `,
   `type `) entirely and with no sanity-check gate. A plain (non-
   exported) TypeScript `interface Foo {}` or `const x = ...` was
   silently invisible to `chat_agent.py`'s version while correctly
   detected by the canonical one — a real, if non-security,
   behavioral divergence between the two real call sites.

Fixed via a shared `analyze_file_handler()`: `check_path_in_worktree()`
closes finding #1; wrapping BOTH `p.exists()` and `read_text()` in one
`try/except PermissionError` closes finding #2 (returning `[ERROR]
Permission denied: {rel}`, matching `file_info`'s established
convention); adopting the canonical implementation's more complete
12-form detection logic (with its sanity-check gate) for both real call
sites closes finding #3, since it was the strictly more capable of the
two and should not have been thinned out in `chat_agent.py`'s separate
copy in the first place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

ANALYZE_FILE_TOOL = {
    "name": "analyze_file",
    "description": "Get a structural summary of a file: top-level imports, class names, function/method signatures. Fast way to understand what a file contains before reading it fully.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root (.py, .ts, .tsx supported)",
            },
        },
        "required": ["path"],
    },
}

_TS_JS_DEFINITION_PREFIXES = (
    "export function ",
    "export async function ",
    "export class ",
    "export const ",
    "export default ",
    "export interface ",
    "export type ",
    "function ",
    "const ",
    "class ",
    "interface ",
    "type ",
)


def analyze_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core analyze_file logic shared by both real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    p = root / rel
    try:
        if not p.exists():
            return f"[ERROR] File not found: {rel}"
        content = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f"[ERROR] Permission denied: {rel}"
    except Exception as e:
        return f"[ERROR] {e}"

    lines = content.splitlines()
    total = len(lines)
    imports: list[str] = []
    definitions: list[str] = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            imports.append(f"  L{i}: {stripped}")
        elif stripped.startswith(("def ", "async def ", "class ")):
            definitions.append(f"  L{i}: {stripped.rstrip(':')}")
        elif any(
            stripped.startswith(prefix) for prefix in _TS_JS_DEFINITION_PREFIXES
        ) and ("=" in stripped or "(" in stripped or "{" in stripped):
            definitions.append(f"  L{i}: {stripped[:100]}")

    summary = [f"File: {rel}  ({total} lines)"]
    if imports:
        summary.append(f"\nImports ({len(imports)}):")
        summary.extend(imports[:30])
    if definitions:
        summary.append(f"\nDefinitions ({len(definitions)}):")
        summary.extend(definitions[:50])
    return "\n".join(summary)
