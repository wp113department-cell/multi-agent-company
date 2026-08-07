"""Merge-conflict marker parsing + resolution — extracted from
app/agents/tools.py (AUDIT_Q_BATCH05_PERFORMANCE_ARCHITECTURE.md §10
"Modularity" — tools.py was a 12,993-line god-module; this pure,
self-contained text-processing pair had zero coupling to anything else in
that file, making it a safe first extraction). Behavior is unchanged —
`app.agents.tools` re-exports both names for full backward compatibility
with existing internal call sites and `tests/test_gap51_merge_conflict_resolution.py`.

No repo in repos/ implements real git-merge-conflict-marker parsing
(aider's own `<<<<<<<`/`=======`/`>>>>>>>` hits are its unrelated
SEARCH/REPLACE edit-block format, not git conflicts).
"""

from __future__ import annotations

from typing import Any


def _parse_conflict_markers(text: str) -> list[dict[str, Any]]:
    """Pure line-scan (no regex) over a file's real content, extracting every
    git conflict region delimited by <<<<<<</=======/>>>>>>> markers (with
    optional diff3-style ||||||| base section). Returns one dict per hunk:
    index, ours_label, base_label, theirs_label, ours_text, base_text,
    theirs_text, start_line, end_line (1-indexed, inclusive)."""
    lines = text.split("\n")
    hunks: list[dict[str, Any]] = []
    state = "context"
    ours_label = base_label = theirs_label = ""
    ours_lines: list[str] = []
    base_lines: list[str] = []
    theirs_lines: list[str] = []
    start_line = 0

    for lineno, line in enumerate(lines, start=1):
        if state == "context":
            if line.startswith("<<<<<<<"):
                state = "ours"
                start_line = lineno
                ours_label = line[len("<<<<<<<") :].strip()
                ours_lines, base_lines, theirs_lines = [], [], []
                base_label = ""
            continue
        if state == "ours":
            if line.startswith("|||||||"):
                state = "base"
                base_label = line[len("|||||||") :].strip()
            elif line.startswith("======="):
                state = "theirs"
            else:
                ours_lines.append(line)
            continue
        if state == "base":
            if line.startswith("======="):
                state = "theirs"
            else:
                base_lines.append(line)
            continue
        if state == "theirs":
            if line.startswith(">>>>>>>"):
                theirs_label = line[len(">>>>>>>") :].strip()
                hunks.append(
                    {
                        "index": len(hunks),
                        "ours_label": ours_label,
                        "base_label": base_label,
                        "theirs_label": theirs_label,
                        "ours_text": "\n".join(ours_lines),
                        "base_text": "\n".join(base_lines) if base_lines else "",
                        "theirs_text": "\n".join(theirs_lines),
                        "start_line": start_line,
                        "end_line": lineno,
                    }
                )
                state = "context"
            else:
                theirs_lines.append(line)
            continue
    return hunks


def _apply_conflict_resolutions(
    text: str, resolutions: dict[int, dict[str, Any]]
) -> tuple[str, list[int], list[int]]:
    """Rewrites text, replacing each conflict hunk with the resolved content
    per `resolutions` (index -> {"choice": "ours"|"theirs"|"custom",
    "custom_content": str}). Hunks with no matching (or invalid) resolution
    are left untouched (markers intact). Returns (new_text, applied_indices,
    unresolved_indices) — every real hunk is accounted for in exactly one of
    the two lists, so a resolutions entry for a non-existent index is never
    silently counted as applied."""
    lines = text.split("\n")
    out: list[str] = []
    applied: list[int] = []
    unresolved: list[int] = []
    state = "context"
    ours_lines: list[str] = []
    theirs_lines: list[str] = []
    marker_block: list[str] = []
    hunk_index = -1

    for line in lines:
        if state == "context":
            if line.startswith("<<<<<<<"):
                state = "ours"
                hunk_index += 1
                ours_lines, theirs_lines = [], []
                marker_block = [line]
            else:
                out.append(line)
            continue
        if state == "ours":
            marker_block.append(line)
            if line.startswith("|||||||"):
                state = "base"
            elif line.startswith("======="):
                state = "theirs"
            else:
                ours_lines.append(line)
            continue
        if state == "base":
            marker_block.append(line)
            if line.startswith("======="):
                state = "theirs"
            continue
        if state == "theirs":
            marker_block.append(line)
            if line.startswith(">>>>>>>"):
                resolution = resolutions.get(hunk_index)
                choice = resolution.get("choice") if resolution else None
                if choice == "ours":
                    out.extend(ours_lines)
                    applied.append(hunk_index)
                elif choice == "theirs":
                    out.extend(theirs_lines)
                    applied.append(hunk_index)
                elif choice == "custom" and resolution is not None:
                    out.extend(str(resolution.get("custom_content", "")).split("\n"))
                    applied.append(hunk_index)
                else:
                    out.extend(marker_block)
                    unresolved.append(hunk_index)
                state = "context"
            else:
                theirs_lines.append(line)
            continue
    return "\n".join(out), applied, unresolved
