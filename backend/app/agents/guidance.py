"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #126/#146 "Step-by-Step Guidance
(dedicated renderer)") — parses a role file's own advisory step list into a
structured, numbered format instead of leaving it buried in prose only the
LLM (reading the raw system prompt) ever sees.

Real role files (roles/*.md) already write a genuine numbered process list
today — e.g. roles/bug_fix.md's "## Process (fixed order)" section, numbered
1-6 — this was never a missing capability at the prompt-authoring level, only
a missing STRUCTURED extraction of it. No new content is invented here: this
is a deterministic markdown parse of exactly what the role file's own author
already wrote, so `AgentResult.guidance_steps` (and, from there, a real
frontend checklist) shows the SAME steps the model was told to follow.
"""

from __future__ import annotations

import re

# Matches a level-2 markdown heading whose title contains "process",
# "steps", or "workflow" (case-insensitive) — covers every real heading
# style already in roles/*.md ("## Process (fixed order)", "## Workflow",
# "## Process Steps", ...) without hardcoding one exact phrase.
_PROCESS_HEADING_RE = re.compile(
    r"(?im)^##\s+.*\b(process|steps|workflow)\b.*$"
)
# A top-level numbered list item: "1. text" / "2) text", at the start of a
# line (allowing leading whitespace for a nested list, which the heading
# scope below still keeps section-local).
_NUMBERED_ITEM_RE = re.compile(r"(?m)^\s*\d+[.)]\s+(.+)$")
# The other real numbering convention this codebase's role files use (13 of
# them, e.g. roles/qa.md): "**Step N — text**" / "**Step N: text**", the
# whole line bolded rather than a plain "N." list marker.
_BOLD_STEP_RE = re.compile(r"(?m)^\s*\*\*Step\s+\d+\s*[—:-]\s*(.+?)\*\*\s*:?\s*(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MAX_STEPS = 20
_MAX_STEP_LENGTH = 200


def extract_guidance_steps(role_markdown: str) -> list[str]:
    """Returns the numbered items under the first "Process"/"Steps"/
    "Workflow" heading in `role_markdown` (typically load_role()'s output —
    _GLOBAL_STANDARDS.md concatenated with the role-specific file), each
    trimmed of markdown bold markers, capped at _MAX_STEPS items and
    _MAX_STEP_LENGTH characters each (a checklist item, not a paragraph).
    Returns [] when the role file has no such section — never fabricates
    steps that aren't really in the prompt."""
    heading_match = _PROCESS_HEADING_RE.search(role_markdown)
    if heading_match is None:
        return []

    section_start = heading_match.end()
    rest = role_markdown[section_start:]
    next_heading = re.search(r"(?m)^##\s+\S", rest)
    section = rest[: next_heading.start()] if next_heading else rest

    raw_items = [m.group(1).strip() for m in _NUMBERED_ITEM_RE.finditer(section)]
    if not raw_items:
        # Fall back to the other real convention this codebase's role files
        # use ("**Step N — label**: rest") — see _BOLD_STEP_RE's own comment.
        for m in _BOLD_STEP_RE.finditer(section):
            label, rest = m.group(1).strip(), m.group(2).strip()
            raw_items.append(f"{label}: {rest}" if rest else label)

    steps: list[str] = []
    for raw in raw_items:
        text = _BOLD_RE.sub(r"\1", raw)
        if len(text) > _MAX_STEP_LENGTH:
            text = text[: _MAX_STEP_LENGTH - 1].rstrip() + "…"
        if text:
            steps.append(text)
        if len(steps) >= _MAX_STEPS:
            break
    return steps
