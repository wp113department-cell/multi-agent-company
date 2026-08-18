"""semver_bump tool — tool_enhance.md productionization pass, tool #25
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: semver_bump
Old path: app/agents/tools.py (`_SEMVER_BUMP_TOOL` schema dict and the
    `semver_bump_h` handler inside `make_chat_handlers()` — no
    chat_agent.py dispatch existed at all before this pass)
New path: app/tools/filesystem/semver_bump.py (this file) —
    `SEMVER_BUMP_TOOL`, `semver_bump_handler`.
Affected agents: 2 per tool_inventory.json. `semver_bump` is advertised
    in `CHAT_TOOLS` (chat_agent's own tool list), so `chat_agent` is one
    of them — but its real dispatch never had a branch for it (same
    class as tool #22's `git_tag`); every real call fell through to the
    generic "[ERROR] Unknown tool: semver_bump" response.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (gains a
    real dispatch branch for the first time).
Affected registries: none — app/fleet/tool_manifest.py's "semver_bump"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["semver_bump"](...)`. New tests added: see
    tests/test_semver_bump_hardening.py, including new coverage of
    chat_agent.py's real dispatch (didn't exist before).

Runtime verification: PASS — see
    backend/docs/tool_productionization/semver_bump.md.
---------------------------------------------------------------------------

Real findings:

1. **"Advertised but never dispatched"** (same class as tool #22's
   `git_tag`): verified directly, a real call returned the generic
   `"[ERROR] Unknown tool: semver_bump"` fallback.
2. **Real path-boundary-escape write** (same class as tools #10/#11/...):
   the optional `file` field was joined via `root / cand` with zero
   worktree-boundary validation before being read AND rewritten. Proved
   directly, before writing any fix: a real file completely outside the
   target repo, containing a version-shaped string, was rewritten by a
   `semver_bump` call with `file` pointing outside the repo — a real,
   if pattern-constrained (only files matching a version-assignment
   regex like `version = "X.Y.Z"` get touched), arbitrary-file-write
   primitive.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

SEMVER_BUMP_TOOL: dict[str, Any] = {
    "name": "semver_bump",
    "description": "Bump the project version (patch/minor/major) in pyproject.toml, package.json, or VERSION file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "part": {
                "type": "string",
                "enum": ["patch", "minor", "major"],
                "description": "Which part to bump",
            },
            "file": {
                "type": "string",
                "description": "Version file path (auto-detected if omitted)",
            },
        },
        "required": ["part"],
    },
}

_VERSION_PATTERN = re.compile(r'(version\s*[=:]\s*["\']?)(\d+)\.(\d+)\.(\d+)(["\']?)')


def semver_bump_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    part = str(inp["part"])
    version_file = str(inp.get("file", ""))
    if version_file:
        result = check_path_in_worktree(version_file, worktree_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        candidates = [version_file]
    else:
        candidates = ["pyproject.toml", "package.json", "VERSION"]

    for cand in candidates:
        fp = root / cand
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8")
        m = _VERSION_PATTERN.search(text)
        if not m:
            continue
        major, minor, patch_v = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if part == "major":
            major, minor, patch_v = major + 1, 0, 0
        elif part == "minor":
            minor, patch_v = minor + 1, 0
        else:
            patch_v += 1
        new_ver = f"{major}.{minor}.{patch_v}"
        new_text = _VERSION_PATTERN.sub(
            lambda x: f"{x.group(1)}{new_ver}{x.group(5)}", text, count=1
        )
        fp.write_text(new_text, encoding="utf-8")
        return f"Bumped version to {new_ver} in {cand}"
    return "[ERROR] No version file found (tried pyproject.toml, package.json, VERSION)"
