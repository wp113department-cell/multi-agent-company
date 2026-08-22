"""sync_files tool — tool_enhance.md productionization pass, tool #64
(2026-08-22).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: sync_files
Old path: app/agents/tools.py (`_SYNC_FILES_TOOL` schema dict and the
    `sync_files` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body, missing the
    worktree-boundary checks the other implementation already had).
New path: app/tools/filesystem/sync_files.py (this file) —
    `SYNC_FILES_TOOL`, `sync_files_handler`.
Affected agents: 1 per tool_inventory.json (chat_agent's own interactive
    dispatch) + `make_chat_handlers()`'s own `sync_files` (whichever
    one-shot agents declare it in `allowed_tools`).
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the same shared, protected function).
Affected registries: none — app/fleet/tool_manifest.py's "sync_files"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["sync_files"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_sync_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/sync_files.md.
---------------------------------------------------------------------------

This tool appears to have been missed by tool #11's cross-cutting
worktree-boundary sweep (2026-08-17) — it is not among the tracking-
table rows that sweep annotated as pre-closed.

Real, severe, empirically-verified finding: `chat_agent.py`'s real
dispatch had ZERO worktree-boundary validation on either `source` or
any entry of `paths` — `root / source` / `root / target` silently
discard `root` when the value is an absolute path (the same pathlib bug
class as tools #10/#11/#18/#23/#43/#59/#61/#62). `tools.py`'s own
`make_chat_handlers` implementation already correctly validated BOTH
via `check_path_in_worktree()` — only `chat_agent.py`'s dispatch had the
gap.

Proved live, combined in one call (a real, severe exfiltration +
arbitrary-write primitive, not two separate minor issues): `source=
"/etc/hostname"` (a real file outside the repo) with `paths=
["exfiltrated.txt", "/tmp/PWNED.txt"]` genuinely READ the host file and
WROTE its content both into the repo (a real exfiltration vector — the
content becomes visible to anyone who can later read the repo) AND to
an arbitrary path outside the repo entirely (a real arbitrary-host-file-
write primitive).

Fixed by switching `chat_agent.py`'s dispatch onto the same shared,
already-correct logic `tools.py`'s implementation used (moved here
verbatim, not rewritten) — `check_path_in_worktree()` on `source` before
any read, and independently on every `paths` entry before any write
(one target failing validation does not block the others — matches the
original per-target error-collection behavior).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree


SYNC_FILES_TOOL = {
    "name": "sync_files",
    "description": "Copy a source file's content to one or more target paths, but only where the content actually differs (also creates targets that don't exist yet). Use to keep intentionally-duplicated files (e.g. a shared config copied into multiple packages) consistent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Source file path relative to repo root",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Target file paths to synchronize from source",
            },
        },
        "required": ["source", "paths"],
    },
}


def sync_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core sync_files logic shared by both real call sites."""
    source = str(inp["source"])
    targets = inp.get("paths") or []
    if not targets:
        return "[ERROR] paths must be a non-empty list of target file paths"

    source_policy = check_path_in_worktree(source, worktree_path)
    if not source_policy.allowed:
        return f"[POLICY DENIED] {source_policy.reason}"

    source_path = root / source
    if not source_path.exists():
        return f"[ERROR] Source file not found: {source}"
    try:
        content = source_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Could not read source {source}: {e}"

    results: list[str] = []
    for target in targets:
        target = str(target)
        target_policy = check_path_in_worktree(target, worktree_path)
        if not target_policy.allowed:
            results.append(f"  {target}: [POLICY DENIED] {target_policy.reason}")
            continue
        target_path = root / target
        try:
            existing = (
                target_path.read_text(encoding="utf-8")
                if target_path.exists()
                else None
            )
        except Exception as e:
            results.append(f"  {target}: [ERROR] {e}")
            continue
        if existing == content:
            results.append(f"  {target}: unchanged (already in sync)")
            continue
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            results.append(
                f"  {target}: {'created' if existing is None else 'updated'} from {source}"
            )
        except Exception as e:
            results.append(f"  {target}: [ERROR] {e}")

    return f"Synchronized '{source}' to {len(targets)} target(s):\n" + "\n".join(results)
