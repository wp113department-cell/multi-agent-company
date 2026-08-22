"""list_files tool — tool_enhance.md productionization pass, tool #68
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: list_files
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[1]` schema dict and the
    `list_files` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE inline dispatch body with a
    real robustness/info-leak gap the canonical implementation didn't
    have).
New path: app/tools/filesystem/list_files.py (this file) —
    `LIST_FILES_TOOL`, `list_files_handler`.
Affected agents: per tool_inventory.json, 79 agents declare `list_files`
    in `allowed_tools` — same shape as tools #65/#67, NOT 79 separate
    implementations: every `run_agent_graph`-based agent and
    `make_chat_handlers()` reach it through the same canonical
    `make_read_only_handlers()` factory; only `chat_agent`'s own
    interactive dispatch was a genuinely separate implementation.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[1]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `list_files` closure now delegates to the shared
    handler), app/agents/chat_agent.py (its real dispatch now calls the
    same shared, protected handler).
Affected registries: none — app/fleet/tool_manifest.py's "list_files"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["list_files"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_list_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/list_files.md.
---------------------------------------------------------------------------

Real, empirically-verified finding, different shape from tools #65/#67:
`chat_agent.py`'s dispatch does NOT have a worktree-boundary escape that
leaks file contents or a full directory listing — an out-of-repo
`directory` still finds no genuinely returnable results, matching the
canonical implementation's own safety mechanism (`fp.relative_to(root)`
raises `ValueError` for anything outside the repo, since `search_root`
itself resolves outside `root` when `directory` is absolute — the usual
`root / directory` pathlib bug from tools #10/#11/#18/#23/#43/#59/#61/
#62/#64/#65/#67). BUT: the canonical implementation wraps that
`relative_to()` call in try/except and silently skips non-matching
entries, while `chat_agent.py`'s dispatch called it unguarded inside a
generator passed straight to `sorted()` — the very first out-of-repo
match raises an UNCAUGHT `ValueError`.

Proved live, in two stages: (1) calling `_execute_tool()` directly
raises the raw `ValueError`; (2) the REAL call path (the graph-node
tool-execution loop, `chat_agent.py` line ~3875) wraps every
`_execute_tool()` call in a generic `except Exception as e: result =
f"[ERROR] Tool {name} failed: {e}"` — so in practice this doesn't crash
the turn, but the resulting error message embeds the exception's own
text, which includes the ABSOLUTE PATH of a real file outside the repo
(e.g. `'/etc/environment' is not in the subpath of '<repo>'`). That is
a real, if minor, information-disclosure primitive: an attacker could
enumerate filenames in an arbitrary host directory one call at a time
(each call's error reveals one real filename), something the canonical
implementation's silent-skip behavior never permits.

Fixed via a shared `list_files_handler()` that adds an explicit
`check_path_in_worktree()` check on `directory` up front (clearer,
consistent `[POLICY DENIED]` behavior, matching the
`read_file`/`get_file_tree` precedent, rather than relying solely on
the incidental `relative_to()` side effect) while keeping the existing
try/except around each glob result as defense in depth.

One cosmetic consolidation: the two original implementations capped
results at a different count (`tools.py`'s canonical version at 200,
`chat_agent.py`'s at 300) — no test or documented contract depends on
the exact number, so the shared handler keeps 200, matching the
canonical implementation that ~40 real call sites already exercise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

LIST_FILES_TOOL = {
    "name": "list_files",
    "description": "List files in a directory. Returns file paths relative to repo root. Use pattern='**/*.py' to filter by type.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory path (default: repo root)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern filter (e.g. '**/*.py', '**/*.ts')",
            },
        },
        "required": [],
    },
}


def list_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core list_files logic shared by both real call sites."""
    directory = str(inp.get("directory", ""))
    pattern = str(inp.get("pattern", "**/*"))

    if directory:
        policy = check_path_in_worktree(directory, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"

    search_root = root / directory if directory else root
    if not search_root.exists():
        return f"[ERROR] Directory not found: {directory}"

    str_paths: list[str] = []
    for p in search_root.glob(pattern):
        if p.is_file():
            try:
                str_paths.append(str(p.relative_to(root)))
            except ValueError:
                pass  # skip symlinks or paths that escape the repo root

    return "\n".join(sorted(str_paths)[:200])
