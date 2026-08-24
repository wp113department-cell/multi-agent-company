"""git_blame tool — tool_enhance.md productionization pass, tool #81
(2026-08-23).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_blame
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[14]` schema dict and the
    `git_blame` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally identical
    inline dispatch body).
New path: app/tools/git/blame.py (this file) — `GIT_BLAME_TOOL`,
    `validate_git_blame_path`, `git_blame_handler`.
Affected agents: per tool_inventory.json, 34 agents declare `git_blame`
    in `allowed_tools`. Both real implementations shared the exact same
    shape this turn; every real caller was affected equally.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[14]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `git_blame` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "git_blame"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: no existing tests referenced this tool beyond two
    comment/tuple mentions (`test_phase63_prompt_injection_defense.py`,
    `test_phase4_item5_git_awareness.py`) — verified directly, neither
    exercises the real handler. New tests added: see
    tests/test_git_blame_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_blame.md.
---------------------------------------------------------------------------

Same flag-collision root cause class as tool #80's `git_show` (a bare
LLM-controlled positional argv element with no `--` separator), on
BOTH real implementations — but checked and confirmed LOWER severity
here: `git blame` has no `--output`-equivalent flag (verified via
`git blame --help`), and its two file-reading flags that could
otherwise be concerning (`--contents <file>`, `-S <file>` / `--ignore-
revs-file <file>`) both require a SEPARATE target-path argument that a
single-field `path` value cannot also supply — proved live:
`path="--contents=/etc/passwd"` alone produces git's own usage error
(`exit 129`, "you must supply exactly one path"), not a working
exploit.

`path`'s worktree-boundary was also checked and confirmed already safe
by construction, same as tool #78's `file`/tool #80's precedent: git's
own `git blame -- <path>` already refuses any path outside the
repository on its own — verified live with both `path="/etc/hostname"`
and `path="../../../etc/hostname"`, both producing `fatal: ... is
outside repository at '<repo>'`.

Fixed anyway, defensively, matching this initiative's consistent
policy from tools #5/#32/#35/#36/#38/#39/#40/#80 (reject flag-shaped
positional values outright regardless of whether a maximally severe
flag was found for this specific tool — this closes the class for any
current or future git-blame flag, not just the ones checked today, and
avoids a real correctness bug where a legitimate filename starting
with `-` would otherwise be silently misinterpreted as a flag): a
shared `validate_git_blame_path()` rejects any `path` starting with
`-`. `start_line`/`end_line` were checked and confirmed already safe —
always embedded inside a fixed `-L{start},{end}` prefix before
reaching argv, so they can never be interpreted as a different flag
(same structurally-immune class established for tools #73-77's
`kind`/`pattern` fields).

Since both real implementations were already functionally identical,
they are unified into one shared `git_blame_handler()`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GIT_BLAME_TOOL = {
    "name": "git_blame",
    "description": "Show who last modified each line of a file and in which commit. Use to understand history and context of specific code.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to repo root",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to blame (optional)",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to blame (optional)",
            },
        },
        "required": ["path"],
    },
}


def validate_git_blame_path(path: str) -> str | None:
    """Returns an [ERROR] string if `path` is flag-shaped, else None.

    Real and necessary even with no shell involved: `path` is a bare
    positional argv element with no `--` separator, so git's own
    argument parser treats a leading `-` as one of its own flags rather
    than a file path — see this module's docstring."""
    if path.startswith("-"):
        return (
            f"[ERROR] path must not look like a command-line flag: "
            f"{path!r} — git would interpret a leading '-' as its own "
            "option rather than the file path. Flag-shaped paths are "
            "rejected outright."
        )
    return None


def git_blame_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core git_blame logic shared by both real call sites."""
    rel = str(inp["path"])

    validation_error = validate_git_blame_path(rel)
    if validation_error:
        return validation_error

    start = inp.get("start_line")
    end = inp.get("end_line")
    cmd = ["git", "blame", "--date=short", "-w"]
    if start and end:
        cmd.append(f"-L{start},{end}")
    cmd.append(rel)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(root), timeout=15
        )
        return (result.stdout or result.stderr)[:5000]
    except Exception as e:
        return f"[ERROR] {e}"
