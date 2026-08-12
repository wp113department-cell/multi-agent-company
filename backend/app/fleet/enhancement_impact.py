"""Pre-change impact simulation — AUDIT_Q_BATCH18 §69 gap-closure
(2026-08-12).

"Autonomous Quality Improvement" was YES for the core scan/approve/apply
loop but PARTIAL for completeness: no pre-change impact simulation existed
anywhere — a human approving an EnhancementRequest saw only the SCAN
agent's own prose description, with no independent, deterministic signal
about how many other files in the repo actually depend on what's about to
change.

Design: reuses the exact `path/to/file.ext:NNN` citation convention
app.agents.tool_security.verify_file_line_citations already extracts (the
same agents that file enhancement requests — agent_performance_reviewer,
agent_debugger, quality_auditor — already cite file:line evidence in their
`description`/`evidence` fields), then computes a real, deterministic
blast radius via grep (the same mechanism the `find_references` tool
already uses) — never an LLM's own guess about what else might be
affected.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from app.agents.tool_security import _extract_file_line_citations, _collect_strings

logger = logging.getLogger(__name__)

_MAX_REFERENCING_FILES_PER_TARGET = 30


def _find_referencing_files(repo_root: str, rel_path: str) -> list[str]:
    """Real, deterministic 'who else touches this file' signal: greps the
    repo for the file's own module/base name (same identifier a Python
    `import` or TS/JS `from './x'` statement would use), excluding the
    file itself. Never raises — a grep failure just means an empty (not
    fabricated) result."""
    module_stem = os.path.splitext(os.path.basename(rel_path))[0]
    if not module_stem or module_stem in ("__init__", "index"):
        return []
    try:
        result = subprocess.run(
            [
                "grep",
                "-rl",
                "-E",
                rf"\b{module_stem}\b",
                repo_root,
                "--include=*.py",
                "--include=*.ts",
                "--include=*.tsx",
                "--include=*.js",
                "--include=*.jsx",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        logger.debug("enhancement impact grep failed for %s", rel_path, exc_info=True)
        return []

    referencing = []
    for abs_hit in result.stdout.splitlines():
        try:
            rel_hit = os.path.relpath(abs_hit, repo_root)
        except ValueError:
            continue
        if rel_hit == rel_path:
            continue
        referencing.append(rel_hit)
        if len(referencing) >= _MAX_REFERENCING_FILES_PER_TARGET:
            break
    return referencing


def simulate_enhancement_impact(
    repo_root: str, description: str, evidence: dict[str, Any] | None
) -> dict[str, Any]:
    """Extracts every file:line citation from `description` + `evidence`
    and computes a real blast-radius report for each cited file. Returns
    {targets: {rel_path: [referencing files...]}, total_target_files,
    total_affected_files} — an empty report (not an exception) when no
    citations are found or repo_root doesn't exist, since a SCAN agent
    that describes a fix in plain language with no file citation yet is a
    normal, valid state this shouldn't block.
    """
    if not repo_root or not os.path.isdir(repo_root):
        return {"targets": {}, "total_target_files": 0, "total_affected_files": 0}

    strings = _collect_strings({"description": description, "evidence": evidence or {}})
    target_paths: set[str] = set()
    for text in strings:
        for rel_path, _line in _extract_file_line_citations(text):
            target_paths.add(rel_path)

    targets: dict[str, list[str]] = {}
    all_affected: set[str] = set()
    for rel_path in sorted(target_paths):
        referencing = _find_referencing_files(repo_root, rel_path)
        targets[rel_path] = referencing
        all_affected.update(referencing)

    return {
        "targets": targets,
        "total_target_files": len(target_paths),
        "total_affected_files": len(all_affected),
    }
