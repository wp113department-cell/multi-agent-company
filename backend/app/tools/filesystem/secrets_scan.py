"""secrets_scan tool — tool_enhance.md productionization pass, tool
#102 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: secrets_scan
Old path: app/agents/tools.py (`_SECRETS_SCAN_TOOL` schema dict) with
    THREE real implementations: `sec_secrets_scan`
    (`make_security_reviewer_handlers`), `secrets_scan` (inside
    `make_chat_handlers()`) + `app/agents/chat_agent.py`'s own
    interactive dispatch (a THIRD, independently-maintained
    implementation — see finding #2 below).
New path: app/tools/filesystem/secrets_scan.py (this file) —
    `SECRETS_SCAN_TOOL`, `secrets_scan_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `secrets_scan` in `allowed_tools`.
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler, dropping its own
    third regex list and `shell=True` grep invocation entirely).
    `app/agents/tool_security.py`'s own `_scan_directory_for_secrets()`
    / `_scan_content_for_secrets()` are left completely untouched —
    they are the existing canonical detector (per AUDIT_Q_BATCH11
    §96), reused here rather than reimplemented; worktree-boundary
    validation is added at THIS tool's own call sites, not inside that
    shared lower-level utility (which has no other real callers today,
    but is a general-purpose module not tied to policy-engine
    concepts).
Affected registries: none — app/fleet/tool_manifest.py's
    "secrets_scan" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the two handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_secrets_scan_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/secrets_scan.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape + real content disclosure, on all three
   implementations.** None validated `directory` before it reached
   `_scan_directory_for_secrets()` (or, for `chat_agent.py`'s dispatch,
   its own separate grep invocation) — `root / directory` let
   `directory` resolve to any absolute host path. Proved live:
   `secrets_scan({"directory": "/tmp/outside"})` genuinely scanned and
   reported on a directory completely outside the repo, disclosing
   that a secret-shaped value exists there (file path + a redacted
   preview) — a real information-disclosure primitive, not just a
   listing.

2. **The most severe finding: a genuine, direct shell-injection
   (arbitrary command execution) on `chat_agent.py`'s dispatch,** which
   was NEVER migrated onto the canonical scanner despite
   AUDIT_Q_BATCH11 §96 explicitly unifying the other two
   implementations years earlier — it still maintains its OWN, third,
   independently-drifted regex list, AND builds its `grep` invocation
   by interpolating `ss_root` (built directly from the LLM-controlled
   `directory` field) COMPLETELY UNQUOTED into an f-string `shell=True`
   command — only the search PATTERN was `shlex.quote()`'d, never the
   directory. Proved live: `directory="; touch /tmp/PWNED_SECRETS_SCAN;
   echo x"` genuinely executed the injected command — same severity
   class as tool #101's `run_linter` chat_agent.py dispatch finding.

Fixed via a shared `secrets_scan_handler()`: `check_path_in_worktree()`
closes finding #1. `chat_agent.py`'s dispatch now delegates to this
same shared handler instead of its own drifted, shell-vulnerable
implementation — closes finding #2 AND, as a side effect, brings it
onto the same canonical, more complete secret-shape detection
(assignment-style + provider-token + PEM headers) the other two
implementations already had, closing the detection-coverage gap
AUDIT_Q_BATCH11 §96 originally set out to fix but never actually
finished for this one call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _scan_directory_for_secrets
from app.policy.engine import check_path_in_worktree

SECRETS_SCAN_TOOL = {
    "name": "secrets_scan",
    "description": "Scan the repository for hardcoded secrets, API keys, passwords, and tokens.",
    "input_schema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to scan (default: entire repo)",
            },
        },
        "required": [],
    },
}


def secrets_scan_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core secrets_scan logic shared by all three real call sites."""
    directory = str(inp.get("directory", ""))
    policy = check_path_in_worktree(directory, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    return _scan_directory_for_secrets(root, directory)
