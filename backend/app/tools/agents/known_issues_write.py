"""known_issues_write tool — tool_enhance.md productionization pass,
tool #161 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: known_issues_write
Old path: app/agents/tools.py (`_KNOWN_ISSUES_WRITE_TOOL` schema
    dict, `known_issues_write_h` inside `make_chat_handlers()` — the
    one real implementation).
New path: app/tools/agents/known_issues_write.py (this file) —
    `KNOWN_ISSUES_WRITE_TOOL`, `known_issues_write_handler`. The
    LLM-calling `embed_bug_sync` is imported with a deferred
    (function-body) import, matching the original code's own
    lazy-import style — `app.memory.store` pulls in a heavier
    dependency chain not needed for the common, non-memory-enabled
    path.
Affected agents: per tool_inventory.json, agents declaring
    `known_issues_write` in `allowed_tools` (plus interactive chat,
    newly — see the one real finding below).
Affected modules: app/agents/tools.py (`known_issues_write_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "known_issues_write" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_known_issues_write_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/known_issues_write.md.
---------------------------------------------------------------------------

`issue` and `severity` are free-text fields appended into a markdown
log file — but the DESTINATION path itself (`known_issues_path()`,
shared with sibling tool #160's `known_issues_read`) is derived
deterministically from `repo_path` alone, never from either input
field, so no worktree-boundary-escape or path-injection surface
exists here, checked directly. `severity`/`issue` reach
`embed_bug_sync()` → `embed_bug()`, which uses SQLAlchemy ORM
parameter binding (not raw string-formatted SQL) — no injection
surface there either, confirmed by direct code inspection of already-
audited, pre-existing shared memory infrastructure.

Preserved unchanged: the original's cross-platform advisory file lock
(`msvcrt.locking()` on Windows, `fcntl.flock()` everywhere else) — a
first draft of this module hardcoded a bare `import fcntl`, which
would have crashed on import on Windows (no `fcntl` module there);
caught before finalizing by re-reading the original's own platform
branch, not by any test failure.

One real, empirically-verified finding — advertised but never
dispatched on the interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160.
`known_issues_write` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: known_issues_write"`.

Fixed via a shared `known_issues_write_handler()`; a new
`chat_agent.py` dispatch branch delegates to it, making
`known_issues_write` genuinely reachable from interactive chat for the
first time.
"""

from __future__ import annotations

import datetime
import sys
from typing import Any

from app.tools.agents.known_issues_read import known_issues_path
import logging

logger = logging.getLogger(__name__)

# Advisory whole-file lock around the read-modify-write append below —
# msvcrt.locking is stdlib and available on Windows; both are used
# purely to serialize concurrent writers, matching the original
# implementation's own platform branch exactly.
if sys.platform == "win32":
    import msvcrt

    def _mem_lock(fh: Any) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _mem_unlock(fh: Any) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _mem_lock(fh: Any) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX)

    def _mem_unlock(fh: Any) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)


KNOWN_ISSUES_WRITE_TOOL: dict[str, Any] = {
    "name": "known_issues_write",
    "description": "Append a new known issue to the project known issues file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "Description of the issue"},
            "severity": {
                "type": "string",
                "description": "critical / high / medium / low",
            },
        },
        "required": ["issue", "severity"],
    },
}


def known_issues_write_handler(repo_path: str, inp: dict[str, Any]) -> str:
    """Core known_issues_write logic — the one real implementation,
    unchanged. Never raises: a memory-backend failure must not turn a
    successful known-issue write into an error."""
    issue = str(inp["issue"])
    severity = str(inp.get("severity", "medium")).upper()
    now = datetime.datetime.utcnow()
    line = f"\n## [{severity}] {now.strftime('%Y-%m-%d')}\n{issue}\n"
    path = known_issues_path(repo_path)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            _mem_lock(fh)
            fh.write(line)
            _mem_unlock(fh)
    except Exception as e:
        return f"[ERROR] {e}"

    # AUDIT_Q_BATCH15 §75/§105/§112 gap-closure — the flat
    # KNOWN_ISSUES.md-style append above is kept unchanged (nothing
    # that reads that file today breaks); this additionally makes the
    # same known issue searchable/retrievable via memory_hook_node,
    # which the flat file alone never was. Best-effort — a memory-
    # backend failure must not turn a successful known-issue write
    # into an error.
    try:
        from app.memory.store import embed_bug_sync

        embed_bug_sync(
            task_id=f"known-issue-{now.strftime('%Y%m%dT%H%M%S%f')}",
            issue=issue,
            severity=severity.lower(),
        )
    except Exception:
        logger.warning(
            "known_issues_write_handler: best-effort step failed", exc_info=True
        )

    return f"Known issue appended (severity: {severity})"
