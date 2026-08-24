"""list_functions tool — tool_enhance.md productionization pass, tool
#82 (2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_functions
Old path: app/agents/tools.py (`_LIST_FUNCTIONS_TOOL` schema dict) with
    NINE separate real implementations: `make_chat_handlers()`'s own
    `list_functions` closure, `app/agents/chat_agent.py`'s separate
    interactive dispatch, and SEVEN agent-specific handlers —
    `ar_list_functions` (`make_arch_reviewer_handlers`),
    `rf_list_functions` (`make_refactor_agent_handlers`),
    `rm_list_functions` (`make_readme_agent_handlers`),
    `ad_list_functions` (`make_api_docs_agent_handlers`),
    `pr_list_functions` (`make_performance_reviewer_handlers`),
    `sr_list_functions` (`make_style_reviewer_handlers`),
    `td_list_functions` (`make_tech_debt_agent_handlers`).
New path: app/tools/filesystem/list_functions.py (this file) —
    `LIST_FUNCTIONS_TOOL`, `list_functions_handler`. ALL NINE real call
    sites now delegate to this one shared handler — the widest
    consolidation in this initiative's low-risk tier so far (tool #12's
    `write_file` consolidated 4 GENERIC implementations while
    deliberately leaving 6 domain-scoped ones alone; here, none of the
    seven agent-specific implementations had any legitimate
    domain-specific reason to diverge from the tool's own documented
    single-file contract, so all seven are unified too).
Affected agents: per tool_inventory.json, 32 agents declare
    `list_functions` in `allowed_tools`.
Affected modules: app/agents/tools.py (all nine closures now delegate
    to the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "list_functions" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the nine handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_list_functions_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_functions.md.
---------------------------------------------------------------------------

FOUR real, empirically-verified findings across the nine
implementations.

1. **Worktree-boundary escape + uncaught `PermissionError`, on the two
   single-file implementations (`chat_agent.py`'s dispatch and
   `make_chat_handlers()`'s own `list_functions`) — same class as tool
   #76's `analyze_file`.** Neither called `check_path_in_worktree()` —
   `root / rel` let `path` resolve to any absolute host path. Proved
   live: `list_functions({"path": "/tmp/outside/secret.py"})` genuinely
   listed a real function definition from a file completely outside
   the repo, through both real call sites. The unguarded `p.exists()`
   call also raised an uncaught `PermissionError` when the parent
   directory was inaccessible (a real `chmod 000` fixture), same as
   tool #76's finding #2.

2. **A field-name mismatch causing every real call to silently ignore
   the requested path, in FOUR agent-specific implementations**
   (`ar_list_functions`, `rf_list_functions`, `rm_list_functions`,
   `ad_list_functions`). The schema these agents actually advertise
   (`_LIST_FUNCTIONS_TOOL`, via `ARCH_REVIEWER_TOOLS` /
   `REFACTOR_AGENT_TOOLS` / the readme agent's / api_docs agent's own
   tool lists) declares the field as `"path"` (required) — but all four
   handlers read `inp.get("file", "")` instead. Since the LLM only ever
   populates the field the schema actually declares, `file` is ALWAYS
   absent, so `fp` is ALWAYS `""`, and the code falls back to grepping
   the **entire repository root recursively** every single time,
   completely ignoring whatever path was actually requested. Proved
   live: a schema-conformant call for `{"path": "src/target.py"}`
   returned function definitions from BOTH `src/target.py` AND a
   completely unrelated `unrelated.py` elsewhere in the repo — a 100%
   real-call failure rate for path-scoping, present since these
   handlers were written (no test ever caught it, same shape as tool
   #24's `new_body`/`new_code` mismatch).

3. **Worktree-boundary escape via relative `../` traversal, in THREE
   agent-specific implementations** (`pr_list_functions`,
   `sr_list_functions`, `td_list_functions` — the ones that DID read
   the correct `path` field). `(root / path).rglob("*.py")` had no
   `check_path_in_worktree()` call. An ABSOLUTE outside-repo path is
   accidentally masked (not genuinely protected) by a downstream
   `fp.relative_to(root)` call inside a bare `except Exception:
   continue` — `relative_to()` raises `ValueError` for a path with no
   common prefix, so results are silently dropped. But `relative_to()`
   compares path PARTS LEXICALLY, not the resolved filesystem path — so
   a **relative `../` traversal** (e.g. `"../../../../tmp/outside"`)
   still has `root` as a literal string prefix of its own parts, so
   `relative_to()` succeeds and the result is NOT dropped. Proved live:
   `list_functions({"path": "../../../../tmp/outside"})` via
   `pr_list_functions` genuinely returned a real function definition
   from a file outside the repo — the absolute-path exploit shape is
   blocked only by accident, not by design, and the traversal shape
   defeats that accident entirely.

4. **A genuine functionality/design mismatch, not a security bug on
   its own, but the root cause enabling findings #2 and #3's severity**:
   the tool's own schema and description ("List all function and
   method definitions **in a file**", `path` described as "File path")
   promise single-file analysis, matching the two single-file
   implementations (`chat_agent.py`, `make_chat_handlers()`) — but the
   seven agent-specific implementations instead grep/rglob an entire
   subtree, a real behavioral divergence from the tool's own documented
   contract that none of the seven had any legitimate domain-specific
   reason for (unlike, say, `write_file`'s genuinely different
   `docs/`-only or `migrations/`-only policies from tool #12).

Fixed via one shared `list_functions_handler()`, adopted by ALL NINE
real call sites: `check_path_in_worktree()` closes findings #1 and #3;
reading the correct `path` field (not `file`) closes finding #2;
adopting the single-file text-scan behavior everywhere (the more
complete detection logic already shared by `chat_agent.py` and
`make_chat_handlers()`, covering Python `def`/`async def` and
TypeScript/JS `export function`/`function`/`export const`/`const`
arrow-function forms) closes finding #4 and gives every one of the 32
real calling agents the SAME, correct, schema-conformant behavior for
the first time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

LIST_FUNCTIONS_TOOL = {
    "name": "list_functions",
    "description": "List all function and method definitions in a file with their line numbers and signatures.",
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


def list_functions_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core list_functions logic shared by all nine real call sites."""
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
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith(("def ", "async def ")):
            sig = s.split(":")[0] if ":" in s else s
            results.append(f"  L{i}: {sig}")
        elif (
            s.startswith(("export function ", "export async function ", "function "))
            and "(" in s
        ):
            results.append(f"  L{i}: {s[:120]}")
        elif s.startswith(("export const ", "const ")) and (
            "=>" in s or "= (" in s or "= async" in s
        ):
            results.append(f"  L{i}: {s[:120]}")

    if not results:
        return f"(no function definitions found in {rel})"
    return f"Functions in {rel} ({len(results)}):\n" + "\n".join(results)
