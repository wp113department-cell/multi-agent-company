"""git_show tool — tool_enhance.md productionization pass, tool #80
(2026-08-23).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_show
Old path: app/agents/tools.py (`READ_ONLY_TOOLS[13]` schema dict and the
    `git_show` handler inside `make_read_only_handlers()`) +
    app/agents/chat_agent.py (a separate but functionally identical
    inline dispatch body).
New path: app/tools/git/show.py (this file) — `GIT_SHOW_TOOL`,
    `validate_git_show_ref`, `git_show_handler`.
Affected agents: per tool_inventory.json, 38 agents declare `git_show`
    in `allowed_tools`. Both real implementations shared the exact same
    bug this turn; every real caller was affected equally.
Affected modules: app/agents/tools.py (`READ_ONLY_TOOLS[13]` now points
    at the shared schema constant, same list index; `make_read_only_
    handlers()`'s own `git_show` closure now delegates to the fixed
    shared handler), app/agents/chat_agent.py (its real dispatch now
    calls the same shared, fixed handler).
Affected registries: none — app/fleet/tool_manifest.py's "git_show"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — no existing tests referenced
    this tool at all (confirmed by grep, matching the tracking table's
    "0" figure). New tests added: see tests/test_git_show_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_show.md.
---------------------------------------------------------------------------

One real, empirically-verified finding — the MOST SEVERE finding
this initiative has found in the low-risk tier so far, on BOTH real
implementations (identical root cause).

**A silent, genuine arbitrary-file-write primitive via git's own
`--output=<path>` flag**, the same flag-collision root cause as tools
#5/#32/#35/#36/#38/#39/#40 (a bare LLM-controlled positional argv
element with no `--` separator, consumed by the external program's own
flag parser when it starts with `-`), but this time with a far more
dangerous flag on the receiving end than any prior occurrence of this
class in this initiative: unlike `git reset`/`git checkout`/`git
merge`/etc., where the worst a hostile flag could do was discard
uncommitted work or abort an in-progress operation, `git show` (and
the `git log` family it shares diff options with) accepts `--output=
<file>`, which redirects the command's own output to an arbitrary
file path chosen entirely by the attacker-controlled value.

Proved live, twice — first at the raw `git` CLI level, then through
both real tool dispatch paths:

```python
await agent._execute_tool("git_show", {"ref": "--output=/tmp/git_show_pwned.txt"})
handlers["git_show"]({"ref": "--output=/tmp/git_show_pwned.txt"})
```

both genuinely wrote a real file (containing the current HEAD commit's
message, author, date, and diffstat) to `/tmp/git_show_pwned.txt` —
and, critically, the tool's own returned text was `"(no output)"` /
`""`, giving the caller (LLM or human observer of the transcript) NO
visible signal that a file was written to the host filesystem at all.
This is a strictly worse failure mode than a visible primitive: the
write is silent. Any path the backend process's OS user can write to
is in scope — not limited to the repo worktree, since this bypasses
filesystem I/O entirely and goes through git's own diff-output
redirection instead of Python's `open()`/`Path.write_text()` (so none
of this initiative's `check_path_in_worktree()` fixes would even apply
here — this is a different code path than every worktree-escape
finding so far).

Fixed via a shared `validate_git_show_ref()` — rejects any `ref`
starting with `-` outright, mirroring the tools #5/#32/#35/#36/#38/
#39/#40 precedent (allowlist-by-exclusion, since enumerating every
dangerous git-show/git-log-family flag is not tractable — `--output`
was merely the most obviously severe one found; this closes the
entire class in one shot, not just this one flag). Since both real
implementations were already functionally identical, they are unified
into one shared `git_show_handler()`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

GIT_SHOW_TOOL = {
    "name": "git_show",
    "description": "Show the full details of a specific commit: message, author, date, and unified diff of changes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Commit hash, tag, or relative ref like HEAD~2 (default: HEAD)",
            },
        },
        "required": [],
    },
}


def validate_git_show_ref(ref: str) -> str | None:
    """Returns an [ERROR] string if `ref` is flag-shaped, else None.

    Real and necessary even with no shell involved: `ref` is a bare
    positional argv element with no `--` separator, so git's own
    argument parser treats a leading `-` as one of its own flags rather
    than a commit ref — including `--output=<path>`, which silently
    redirects the command's output to an arbitrary attacker-chosen
    file path. See this module's docstring."""
    if ref.startswith("-"):
        return (
            f"[ERROR] ref must not look like a command-line flag: {ref!r} — "
            "git would interpret a leading '-' as its own option (e.g. "
            "--output=<path> silently writes to an arbitrary file) rather "
            "than a commit reference. Flag-shaped refs are rejected "
            "outright."
        )
    return None


def git_show_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core git_show logic shared by both real call sites."""
    ref = str(inp.get("ref", "HEAD"))

    validation_error = validate_git_show_ref(ref)
    if validation_error:
        return validation_error

    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--no-color", ref],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=15,
        )
        return (result.stdout or result.stderr)[:5000]
    except Exception as e:
        return f"[ERROR] {e}"
