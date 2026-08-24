"""list_classes tool — tool_enhance.md productionization pass, tool
#87 (2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_classes
Old path: app/agents/tools.py (`_LIST_CLASSES_TOOL` schema dict) with
    SEVEN real implementations: `chat_agent.py`'s own interactive
    dispatch, `make_chat_handlers()`'s own `list_classes` closure, and
    FIVE agent-specific handlers — `ar_list_classes`
    (`make_arch_reviewer_handlers`), `rf_list_classes`
    (`make_refactor_agent_handlers`), `rm_list_classes`
    (`make_readme_agent_handlers`), `sr_list_classes`
    (`make_style_reviewer_handlers`), `td_list_classes`
    (`make_tech_debt_agent_handlers`). The exact sibling tool to tool
    #82's `list_functions`, sharing the identical bug shapes (this
    time missing `ad_`/`pr_` from the agent-specific set — `list_
    classes` was never wired into `make_api_docs_agent_handlers()` or
    `make_performance_reviewer_handlers()` at all).
New path: app/tools/filesystem/list_classes.py (this file) —
    `LIST_CLASSES_TOOL`, `list_classes_handler`. ALL SEVEN real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, 7 agents declare
    `list_classes` in `allowed_tools`.
Affected modules: app/agents/tools.py (its own closures delegate to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "list_classes"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the seven handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_list_classes_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_classes.md.
---------------------------------------------------------------------------

The exact same four finding classes already established for tool #82's
`list_functions` — proved live independently for this sibling tool,
not assumed to transfer automatically.

1. **Worktree-boundary escape + uncaught `PermissionError`, on the two
   single-file implementations** (`chat_agent.py`'s dispatch and
   `make_chat_handlers()`'s own closure) — same class as tool #76's
   `analyze_file`/tool #82's `list_functions`. Proved live:
   `list_classes({"path": "/tmp/outside/secret.py"})` genuinely listed
   a real class definition (and its methods) from a file completely
   outside the repo, through both real call sites. The unguarded
   `p.exists()` call also raised an uncaught `PermissionError`.

2. **A field-name mismatch causing every real call to silently ignore
   the requested path, in THREE agent-specific implementations**
   (`ar_list_classes`, `rf_list_classes`, `rm_list_classes`). The
   schema these agents actually advertise declares the field as
   `"path"` (required) — but all three handlers read `inp.get("file",
   "")` instead, always falling back to grepping the entire repository
   root recursively. Proved live: a schema-conformant call for
   `{"path": "src/target.py"}` returned class definitions from BOTH
   `src/target.py` AND a completely unrelated file elsewhere in the
   repo.

3. **Worktree-boundary escape via relative `../` traversal, in TWO
   agent-specific implementations** (`sr_list_classes`,
   `td_list_classes` — the ones that DID read the correct `path`
   field). `(root / path).rglob("*.py")` had no `check_path_in_
   worktree()` call; an absolute outside-repo path is accidentally
   masked by a swallowed `ValueError` from `relative_to()`, but a
   relative traversal path defeats that accident. Proved live:
   `list_classes({"path": "../../../../tmp/outside"})` via
   `sr_list_classes` genuinely returned a real class definition from a
   file outside the repo.

4. **A design mismatch**: the tool's own schema/description promise
   single-file analysis ("List all class definitions IN A FILE"),
   matching the two single-file implementations — but the five
   agent-specific implementations instead grep/rglob an entire
   subtree, with no legitimate domain-specific reason for the
   divergence.

Fixed via one shared `list_classes_handler()`, adopted by ALL SEVEN
real call sites: `check_path_in_worktree()` closes findings #1 and #3;
reading the correct `path` field (not `file`) closes finding #2;
adopting the single-file, indentation-aware class+method-detection
logic already shared by `chat_agent.py`/`make_chat_handlers()`
everywhere closes finding #4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

LIST_CLASSES_TOOL = {
    "name": "list_classes",
    "description": "List all class definitions in a file with their methods and line numbers.",
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


def list_classes_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core list_classes logic shared by all seven real call sites."""
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
    results: list[str] = []
    current: str | None = None
    base_indent = 0
    for i, line in enumerate(lines, 1):
        s = line.strip()
        curr_indent = len(line) - len(line.lstrip())
        if s.startswith(("class ", "export class ", "export default class ")):
            current = s.split("(")[0].split("{")[0].rstrip()
            base_indent = curr_indent
            results.append(f"\nL{i}: {current}")
        elif current and curr_indent > base_indent:
            if s.startswith(("def ", "async def ")):
                results.append(f"    L{i}: {s.split(':')[0]}")
            elif (
                s.startswith(("public ", "private ", "protected ", "async ", "static "))
                and "(" in s
            ):
                results.append(f"    L{i}: {s[:120]}")
        elif (
            current
            and line.strip()
            and curr_indent <= base_indent
            and not s.startswith(("@", "#", "/"))
        ):
            current = None

    if not results:
        return f"(no class definitions found in {rel})"
    return f"Classes in {rel}:\n" + "\n".join(results)
