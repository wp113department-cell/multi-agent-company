"""scan_code_hygiene tool — T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396
"Broken imports / unused files / duplicate functions detection").

Complements dead_code_detect (dead functions), find_unused_imports (ruff
F401) and the circular-import detector — the three real gaps Task 1's own
verification of #396 found: no detector existed for broken/unresolvable
imports, unused files, or duplicate/cloned functions (as opposed to
duplicated NAMES, which dead_code_detect's own dict-keyed-by-name silently
overwrites rather than surfaces). See app.repo_tools.code_hygiene's module
docstring for the real detection logic and its honest limitations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.code_hygiene import (
    find_broken_imports,
    find_duplicate_functions,
    find_unused_files,
)

SCAN_CODE_HYGIENE_TOOL: dict[str, Any] = {
    "name": "scan_code_hygiene",
    "description": (
        "Real, structural scan for three code-hygiene issues plain heuristics can't "
        "reliably catch: (1) broken/unresolvable imports — a module that genuinely "
        "cannot be found, not a claim from memory; (2) unused files — never imported "
        "anywhere else in this directory's own tree; (3) duplicate/cloned functions — "
        "structurally identical bodies across different files or names, not just "
        "identical function names. Use before recommending a cleanup or reporting "
        "'no dead code found' — this catches classes of issue dead_code_detect alone "
        "cannot."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan, relative to the repo root (empty = whole repo)",
            }
        },
    },
}


def scan_code_hygiene_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core scan_code_hygiene logic — same (root, worktree_path, inp) shape
    as dead_code_detect_handler for a consistent call convention across the
    per-agent handler factories that wire both."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / directory if directory else root
    target_str = str(target)

    broken = find_broken_imports(target_str)
    unused = find_unused_files(target_str)
    duplicates = find_duplicate_functions(target_str)

    if broken is None and unused is None and duplicates is None:
        return "(no .py files found)"

    lines: list[str] = []

    if broken:
        lines.append(f"⚠️  {len(broken)} broken/unresolvable import(s):")
        for b in broken:
            lines.append(f"  {b.module}  ← {b.file}:{b.line}")
    else:
        lines.append("✅ No broken imports detected.")

    if unused:
        lines.append(
            f"⚠️  {len(unused)} file(s) never imported anywhere in this directory:"
        )
        for f in unused:
            lines.append(f"  {f}")
    else:
        lines.append(
            "✅ No unused files detected (within this directory's own import graph)."
        )

    if duplicates:
        lines.append(
            f"⚠️  {len(duplicates)} group(s) of structurally duplicate function(s):"
        )
        for group in duplicates:
            lines.append("  - " + " == ".join(group.locations))
    else:
        lines.append("✅ No duplicate/cloned functions detected.")

    return "\n".join(lines)
