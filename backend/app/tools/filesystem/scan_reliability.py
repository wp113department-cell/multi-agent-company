"""scan_reliability tool — T2-B9 (2026-09-24, GRIDIRON_PARTIAL #149
"Reliability Engineering / Maintainability (beyond lint gates)").

See app.repo_tools.reliability_review's own module docstring for the real
detection logic (unguarded external-I/O calls — HTTP, subprocess, a raw DB
`.execute()`, the Anthropic client) and its honestly-stated scope
boundaries (why "missing retry/circuit-breaker coverage" is deliberately
NOT a second, fabricated heuristic here).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.repo_tools.reliability_review import (
    find_unguarded_external_calls,
    format_reliability_report,
)

SCAN_RELIABILITY_TOOL: dict[str, Any] = {
    "name": "scan_reliability",
    "description": (
        "Real, structural scan for external-I/O calls (HTTP requests, subprocess, "
        "a raw DB execute, the Anthropic client) with NO try/except anywhere in "
        "their own enclosing function — a real, checkable reliability gap lint "
        "gates don't catch. Use before recommending a change is 'reliable' or "
        "reporting no issues found in error-handling coverage."
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


def scan_reliability_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core scan_reliability logic — same (root, worktree_path, inp) shape
    as scan_code_hygiene_handler for a consistent call convention across
    the per-agent handler factories that wire both."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    target = root / directory if directory else root
    report = find_unguarded_external_calls(str(target))
    return format_reliability_report(report)
