"""read_files tool — tool_enhance.md productionization pass, tool #71
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_files
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[6]` schema dict and the
    `read_files` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a SEPARATE, unprotected inline dispatch
    body).
New path: app/tools/filesystem/read_files.py (this file) —
    `READ_FILES_TOOL`, `read_files_handler`.
Affected agents: per tool_inventory.json, 72 agents declare
    `read_files` in `allowed_tools` — same shape as tools #65/#67/#68/
    #70, NOT 72 separate implementations: every `run_agent_graph`-based
    agent and `make_chat_handlers()` reach it through the same canonical
    `make_read_only_handlers()` factory; only `chat_agent`'s own
    interactive dispatch was a genuinely separate, unprotected
    duplicate.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[6]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `read_files` closure now delegates to the shared
    handler), app/agents/chat_agent.py (its real dispatch now calls the
    same shared, protected handler).
Affected registries: none — app/fleet/tool_manifest.py's "read_files"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `make_read_only_handlers(...)["read_files"]` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_read_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_files.md.
---------------------------------------------------------------------------

Real, severe, empirically-verified finding — the most severe found in
the low-risk tier so far, worse than tool #65's single-file
`read_file` finding since this tool reads up to 20 files PER CALL:
`chat_agent.py`'s real dispatch had ZERO worktree-boundary validation
— `root / str(rel)` with no `check_path_in_worktree()` call at all for
any path in the batch. Proved live:

```python
await agent._execute_tool("read_files", {
    "paths": ["/etc/passwd", "/etc/hostname"],
})
```

genuinely returned the REAL, FULL CONTENT of both host files —
completely outside the repo, batched into a single call. This is a
real, severe arbitrary-multi-file-read / batch-exfiltration primitive
— the same class as tool #11's original `copy_file`/`write_file`
findings, but on the read side and at up to 20x the throughput per
call. The canonical `make_read_only_handlers()` implementation was NOT
exploitable — already correctly validated every path via
`check_path_in_worktree()`, appending a per-path `[POLICY DENIED]`
result and continuing rather than failing the whole batch.

`chat_agent.py`'s dispatch also lacked the large-file folding/
truncation safeguard the canonical implementation already has (the
same functionality-parity gap already found and fixed for `read_file`,
tool #65, and explicitly documented in `tools.py`'s own comment as
"AUDIT_Q_BATCH09 §15 gap-closure" — reusing `read_file`'s exact folding
logic so both tools behave identically).

Fixed by extracting the canonical, already-correct, already-feature-
complete logic into a shared `read_files_handler()` here, and switching
BOTH real call sites onto it — closing the worktree-escape and the
folding-parity gap in the same move, exactly mirroring tool #65's own
fix shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app.policy.engine import check_path_in_worktree

READ_FILES_TOOL = {
    "name": "read_files",
    "description": "Read multiple files at once. Returns each file's content labeled by path. Far more efficient than calling read_file repeatedly when you need to explore several files. Only 20 files are read per call; if more paths are given, the result ends with a [NOTICE] telling you the offset to pass on the next call to read the rest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths relative to repo root (20 read per call, see offset)",
            },
            "offset": {
                "type": "integer",
                "description": "Index into paths to start reading from, for paging through more than 20 paths across multiple calls (default 0)",
            },
        },
        "required": ["paths"],
    },
}


def read_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_files logic shared by both real call sites."""
    all_paths: list[str] = inp.get("paths", [])
    offset = max(0, int(inp.get("offset", 0)))
    paths = all_paths[offset : offset + 20]
    parts: list[str] = []
    settings = get_settings()

    for rel in paths:
        policy = check_path_in_worktree(rel, worktree_path)
        if not policy.allowed:
            parts.append(f"=== {rel} ===\n[POLICY DENIED] {policy.reason}")
            continue
        p = root / rel
        if not p.exists():
            parts.append(f"=== {rel} ===\n[ERROR] Not found")
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            parts.append(f"=== {rel} ===\n[ERROR] {e}")
            continue

        line_count = content.count("\n") + 1
        if settings.file_fold_enabled and line_count > settings.file_fold_line_threshold:
            from app.repo_tools.file_folding import fold_file_content

            folded = fold_file_content(p, settings.file_fold_max_chars)
            if folded is not None:
                parts.append(
                    f"=== {rel} ===\n[NOTE] {rel} is {line_count} lines "
                    "— showing structure only (functions/classes + "
                    "line ranges) instead of full content to avoid an "
                    "oversized context. Read a specific line range if "
                    f"you need implementation detail.\n\n{folded}"
                )
                continue
            if len(content) > settings.file_fold_fallback_max_chars:
                cap = settings.file_fold_fallback_max_chars
                parts.append(
                    f"=== {rel} ===\n{content[:cap]}\n... [TRUNCATED: "
                    f"{rel} is {line_count} lines; showing the first "
                    f"{cap} characters]"
                )
                continue
        parts.append(f"=== {rel} ===\n{content}")

    if not parts:
        return "[ERROR] No paths provided" if not all_paths else "(no paths at this offset)"

    remaining = len(all_paths) - (offset + len(paths))
    if remaining > 0:
        parts.append(
            f"[NOTICE] {remaining} of {len(all_paths)} requested path(s) were "
            f"not read (20-per-call limit). Call again with "
            f"offset={offset + len(paths)} to continue."
        )
    return "\n\n".join(parts)
