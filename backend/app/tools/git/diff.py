"""git_diff tool — tool_enhance.md productionization pass, tool #84
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_diff
Old path: app/agents/tools.py, with TWO schema definitions (an inline
    dict in `CODER_TOOLS` and `_GIT_DIFF_TOOL_SPEC`, used by
    `BUG_FIX_AGENT_TOOLS`/`REFACTOR_AGENT_TOOLS`/`CHAT_TOOLS`,
    cosmetically different description text but the identical `file`
    field) and FOUR real implementations: `make_coder_handlers()`'s own
    `git_diff` closure (already safe — the only one that already used
    a `--` pathspec separator, but unstaged-only), the shared
    `_make_git_diff_handler()` factory (used by
    `make_bug_fix_handlers()` and `make_refactor_agent_handlers()`),
    `make_chat_handlers()`'s own `git_diff` closure (staged+unstaged,
    but vulnerable), and `app/agents/chat_agent.py`'s separate
    interactive dispatch (staged+unstaged, also vulnerable).
New path: app/tools/git/diff.py (this file) — `GIT_DIFF_TOOL`,
    `git_diff_handler`. ALL FOUR real call sites now delegate to this
    one shared handler.
Affected agents: per tool_inventory.json, 10 agents declare `git_diff`
    in `allowed_tools`.
Affected modules: app/agents/tools.py (both schema constants now alias
    the shared `GIT_DIFF_TOOL`; all four closures delegate to the
    shared handler), app/agents/chat_agent.py (its dispatch now calls
    the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's "git_diff"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes — every existing real test
    accesses this tool via one of the four handler factories or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_diff_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_diff.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — same severe class as tool
#80's `git_show`, on THREE of the four real implementations
(`_make_git_diff_handler()`, `make_chat_handlers()`'s own closure,
`chat_agent.py`'s dispatch — `make_coder_handlers()`'s own closure was
already correctly protected and is the only implementation this fix
did not need to change behaviorally for security).

**A silent, genuine arbitrary-file-write primitive via git's own
`--output=<path>` flag.** `file` was appended as a bare LAST positional
argv element with no `--` separator in three of the four
implementations, so a flag-shaped value was consumed by git's own
argument parser instead of being treated as a pathspec — the same
class first found in tool #80. Proved live, first at the raw `git`
CLI level, then through all three vulnerable real dispatch paths:

```python
await agent._execute_tool("git_diff", {"file": "--output=/tmp/git_diff_pwned.txt"})
make_chat_handlers(repo)["git_diff"]({"file": "--output=/tmp/git_diff_pwned2.txt"})
make_bug_fix_handlers(repo)["git_diff"]({"file": "--output=/tmp/git_diff_pwned3.txt"})
```

all three genuinely wrote a real file (containing the actual unstaged
diff content) to the attacker-chosen path — and critically, the tool's
own returned text (`"No changes."` / `"(no output)"`) gave the caller
**no visible signal that a file was written to the host filesystem at
all**, the identical silent-failure-mode severity as tool #80.
`make_coder_handlers()`'s own implementation was NOT exploitable — it
already placed `file` after a `--` separator.

A secondary, non-security finding: the four implementations diverged
in real behavior — two showed only the unstaged diff, two showed both
staged and unstaged. The tool's own description ("review your own
changes before submitting") is best served by the more complete
staged+unstaged view (staged changes are exactly the ones about to be
committed), so all four are unified onto that behavior.

Fixed via a shared `git_diff_handler()`: places `file` after a `--`
separator (mirroring `make_coder_handlers()`'s own already-correct
pattern) for both the staged and unstaged `git diff` invocations,
closing the vulnerability everywhere at once; adopts the more complete
staged+unstaged output for all four real call sites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GIT_DIFF_TOOL = {
    "name": "git_diff",
    "description": "Show current staged and unstaged diff. Optionally limit to one file. Use this to review your own changes before submitting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Optional: limit the diff to this file",
            },
        },
        "required": [],
    },
}


def git_diff_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core git_diff logic shared by all four real call sites."""
    file_filter = str(inp.get("file", ""))
    pathspec = ["--", file_filter] if file_filter else []

    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--no-color", *pathspec],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        unstaged = subprocess.run(
            ["git", "diff", "--no-color", *pathspec],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "[ERROR] git diff timed out"

    if unstaged.returncode != 0:
        return f"[ERROR] git diff: {unstaged.stderr[:300]}"

    out = ""
    if staged.stdout.strip():
        out += "=== STAGED ===\n" + staged.stdout
    if unstaged.stdout.strip():
        out += "=== UNSTAGED ===\n" + unstaged.stdout
    return out[:8000] if out else "No changes."
