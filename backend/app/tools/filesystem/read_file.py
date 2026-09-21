"""read_file tool — tool_enhance.md productionization pass, tool #65
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_file
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[0]` schema dict and the
    `read_file` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE, unprotected inline dispatch
    body).
New path: app/tools/filesystem/read_file.py (this file) —
    `READ_FILE_TOOL`, `read_file_handler`.
Affected agents: per tool_inventory.json, 82 agents declare `read_file`
    in `allowed_tools` — but this is NOT 82 separate implementations.
    Every `run_agent_graph`-based agent (coder, qa, planner, architect,
    ~35+ others) reaches `read_file` through the SAME single canonical
    `make_read_only_handlers()` factory (confirmed by grepping every
    real call site: ~40 callers all invoke `make_read_only_handlers(...)`
    fresh, none reimplement the logic). The only genuinely separate
    implementation is `chat_agent`'s own interactive dispatch — which is
    also the one that had the real vulnerability (see below). This
    initiative previously saw the inverse mistake for `write_file`/
    `edit_file` (tools #12/#13, ~12 real separate implementations behind
    a wide `allowed_tools` fan-out) — worth checking per-tool rather
    than assuming inventory agent-count implies implementation count
    either way.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[0]` now points
    at the shared schema constant — kept as the exact same list index,
    since `RESEARCH_TOOLS` and others index into `READ_ONLY_TOOLS`
    positionally; `make_read_only_handlers()`'s own `read_file` closure
    now delegates to the shared handler), app/agents/chat_agent.py (its
    real dispatch now calls the same shared, protected handler instead
    of its own unprotected duplicate).
Affected registries: none — app/fleet/tool_manifest.py's "read_file"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["read_file"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_read_file_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_file.md.
---------------------------------------------------------------------------

Real, severe, empirically-verified finding: `chat_agent.py`'s real
dispatch had ZERO worktree-boundary validation — `root / path` with no
`check_path_in_worktree()` call at all, unlike the canonical
`make_read_only_handlers()` implementation which already had it. Proved
live: `read_file({"path": "/etc/hostname"})` through
`ChatAgent._execute_tool` genuinely returned the real content of a host
file completely outside the repo — a real arbitrary-file-read /
exfiltration primitive, the same class found repeatedly throughout this
initiative (tools #10/#11/#18/#23/#43/#59/#61/#62/#64). The canonical
factory's own `read_file` was NOT exploitable by this payload — already
correctly rejected it.

`chat_agent.py`'s dispatch also lacked the large-file folding/truncation
safeguard (`file_fold_enabled` / `file_fold_line_threshold`) the
canonical implementation already has (Gap-closure Days 45-47 Stage 2) —
a functionality gap, not a security one, but real: a 9,000+ line file
read through the interactive chat session would load in full into
context instead of being folded to its structural signature.

Fixed by extracting the canonical, already-correct, already-feature-
complete logic into a shared `read_file_handler()` here, and switching
BOTH real call sites onto it — closing the worktree-escape and the
folding-parity gap in the same move, rather than patching
`chat_agent.py`'s duplicate separately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import check_path_in_worktree

# A single ranged read is bounded so it can never itself become an oversized
# context dump; the response says exactly how to continue.
MAX_RANGE_LINES = 400
MAX_RANGE_CHARS = 30_000
# Even a file with few (but enormous) lines — minified JS, one-line JSON — must
# not be able to put megabytes into an agent's context.
HARD_MAX_CHARS = 200_000

READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read the contents of a file. Always read a file before editing it. "
        "Very large files come back as a structure outline or truncated; use "
        "start_line/end_line to read any specific range of them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the repo root",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to return (1-based). Optional — reads a range instead of the whole file.",
            },
            "end_line": {
                "type": "integer",
                "description": f"Last line to return (inclusive). Optional; a range is capped at {MAX_RANGE_LINES} lines per call.",
            },
        },
        "required": ["path"],
    },
}


def read_file_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_file logic shared by both real call sites."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"
    p = root / rel
    if not p.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        content = str(p.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[ERROR] Cannot read {rel}: {e}"

    if inp.get("start_line") is not None or inp.get("end_line") is not None:
        return _read_line_range(rel, content, inp)

    # Gap-closure Days 45-47 (Stage 2) — this file has "no truncation/
    # chunking safeguard" for 9,000+ line files (answers.md); a large
    # file is folded to its structural signature instead of loaded in
    # full, or bounded-truncated when folding isn't possible (non-code
    # file types).
    settings = get_settings()
    line_count = content.count("\n") + 1
    if settings.file_fold_enabled and line_count > settings.file_fold_line_threshold:
        from app.repo_tools.file_folding import fold_file_content

        folded = fold_file_content(p, settings.file_fold_max_chars)
        if folded is not None:
            return (
                f"[NOTE] {rel} is {line_count} lines — showing structure "
                "only (functions/classes + line ranges) instead of full "
                "content to avoid an oversized context. Call read_file again "
                "with start_line/end_line to read any specific range.\n\n"
                f"{folded}"
            )
        if len(content) > settings.file_fold_fallback_max_chars:
            cap = settings.file_fold_fallback_max_chars
            return (
                content[:cap]
                + f"\n... [TRUNCATED: {rel} is {line_count} lines; showing "
                f"the first {cap} characters. Call read_file again with "
                "start_line/end_line to read any other range.]"
            )

    if len(content) > HARD_MAX_CHARS:
        return (
            content[:HARD_MAX_CHARS]
            + f"\n... [TRUNCATED: {rel} is {len(content)} characters on "
            f"{line_count} line(s); showing the first {HARD_MAX_CHARS}. Use "
            "search_code or a shell command to inspect the rest.]"
        )
    return content


def _read_line_range(rel: str, content: str, inp: dict[str, Any]) -> str:
    """Return lines [start_line, end_line] (1-based, inclusive) of `content`."""
    try:
        start = int(inp["start_line"]) if inp.get("start_line") is not None else 1
        end_raw = inp.get("end_line")
        end = int(end_raw) if end_raw is not None else start + MAX_RANGE_LINES - 1
    except (TypeError, ValueError):
        return "[ERROR] read_file: start_line/end_line must be integers"
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline is not an extra line
    total = len(lines)
    if start < 1 or end < start:
        return f"[ERROR] read_file: invalid range {start}-{end} (lines are 1-based, end >= start)"
    if start > total:
        return f"[ERROR] read_file: {rel} has only {total} line(s); start_line={start} is past the end"
    stop = min(end, total, start + MAX_RANGE_LINES - 1)
    chunk = lines[start - 1 : stop]
    text = "\n".join(chunk)
    capped_by_chars = len(text) > MAX_RANGE_CHARS
    if capped_by_chars:
        text = text[:MAX_RANGE_CHARS]
        stop = start + text.count("\n")
    header = f"[{rel}: lines {start}-{stop} of {total}]"
    footer = ""
    if stop < min(end, total) or (end > stop and stop < total):
        footer = f"\n[range capped — continue with start_line={stop + 1}]"
    elif stop < total:
        footer = (
            f"\n[{total - stop} more line(s) — continue with start_line={stop + 1}]"
        )
    return f"{header}\n{text}{footer}"
