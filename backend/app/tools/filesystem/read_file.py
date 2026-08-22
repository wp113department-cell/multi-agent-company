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

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read the full contents of a file. Always read a file before editing it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the repo root",
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
                "content to avoid an oversized context. Read a specific "
                "line range if you need implementation detail.\n\n"
                f"{folded}"
            )
        if len(content) > settings.file_fold_fallback_max_chars:
            cap = settings.file_fold_fallback_max_chars
            return (
                content[:cap]
                + f"\n... [TRUNCATED: {rel} is {line_count} lines; showing "
                f"the first {cap} characters]"
            )

    return content
