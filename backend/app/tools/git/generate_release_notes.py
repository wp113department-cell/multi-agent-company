"""generate_release_notes tool — tool_enhance.md productionization
pass, tool #112 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_release_notes
Old path: app/agents/tools.py (`_GENERATE_RELEASE_NOTES_TOOL` schema
    dict) with ONE real implementation: `generate_release_notes_h`
    (inside `make_chat_handlers()`). `app/agents/chat_agent.py` had
    ZERO dispatch branch for this tool despite it being advertised in
    `CHAT_TOOLS` — the same "advertised but never dispatched" class
    already established for tools #4/#6/#22/#25/#33/#44/#45/#46/#48/
    #100/#103/#110. This tool is the direct sibling of tool #100's
    `generate_changelog` — same shape, same two real security
    findings, same fix pattern.
New path: app/tools/git/generate_release_notes.py (this file) —
    `GENERATE_RELEASE_NOTES_TOOL`, `generate_release_notes_handler`.
    The real implementation now delegates to this shared handler, and
    a new real dispatch has been wired into `chat_agent.py`.
Affected agents: per tool_inventory.json, agents declaring
    `generate_release_notes` in `allowed_tools` go through
    `make_chat_handlers()`.
Affected modules: app/agents/tools.py (its closure delegates to the
    shared handler), app/agents/chat_agent.py (new real dispatch
    added).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_release_notes" ToolManifestEntry is pure metadata, keyed
    by tool NAME not file path.
Affected tests: `tests/test_day2_tools.py`'s handler tests call the
    handler with an explicit `repo_path` field pointing at the outer
    project root (deliberately different from the handler factory's
    own configured `.../backend` path) — checked directly (not
    assumed), same reasoning already established for tool #100:
    `git -C <subdir> log` works identically from any subdirectory of a
    git worktree, so ignoring the LLM-supplied `repo_path` override
    (finding #2's fix) does not change these tests' real behavior —
    re-run and confirmed passing unchanged. New tests added: see
    tests/test_generate_release_notes_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_release_notes.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings — the exact same shape as
tool #100's `generate_changelog`.

1. **The most severe finding class of this initiative — silent
   arbitrary-file-write, same class as tools #80/#100.** `from_ref` is
   LLM-controlled and becomes part of `ref_range = f"{from_ref}..HEAD"`
   — a single argv element handed directly to `git log` with zero
   validation. `git log` accepts a generic `--output=<path>` flag.
   Proved live with the EXACT real command shape this tool builds:
   `from_ref="--output=/tmp/PWNED_RELEASE_NOTES_TEST"` produced
   `--output=/tmp/PWNED_RELEASE_NOTES_TEST..HEAD` as the ref_range
   argv token — git parsed everything after `--output=` as the file
   path (including the literal `..HEAD` suffix, which is just
   characters in the filename, not path syntax) and genuinely wrote a
   real file to that attacker-chosen location. The tool's own returned
   text gives ZERO indication anything was written.

2. **`repo_path` is an LLM-controlled field that lets the caller
   redirect ALL git operations at an arbitrary host directory,
   completely outside the intended worktree.** Proved live: pointing
   `repo_path` at a real git repository outside the intended project
   worktree genuinely disclosed that OTHER repo's full commit history.
   Same finding, same fix, as tool #100.

3. **"Advertised but never dispatched"** — see migration report above.

Fixed via a shared `generate_release_notes_handler(root, inp)`,
mirroring tool #100's `generate_changelog_handler()` exactly:
 - the `repo_path` field from `inp` is IGNORED entirely — `root` (the
   handler factory's own configured worktree) is always used, closing
   finding #2 structurally;
 - `validate_git_ref(from_ref)` (reused from tool #100's own module,
   not reimplemented — the exact same validation rule applies here)
   rejects any ref starting with `-` — closes finding #1;
 - a new, real `chat_agent.py` dispatch delegates to this same shared
   handler, closing finding #3.
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import Any

from app.tools.git.generate_changelog import validate_git_ref


def generate_release_notes_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core generate_release_notes logic. `inp.get('repo_path')` is
    deliberately ignored — this always operates on `root`, the
    worktree the handler was built for. See this module's docstring
    (finding #2) for why an LLM-controlled repo_path override is
    rejected rather than validated."""
    version = str(inp["version"])
    _rp = str(root)
    from_ref = str(inp.get("from_ref", ""))

    if from_ref:
        error = validate_git_ref(from_ref)
        if error:
            return error

    try:
        if not from_ref:
            tags = subprocess.run(
                ["git", "-C", _rp, "tag", "--sort=-version:refname"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            tag_list = [t for t in tags.stdout.strip().splitlines() if t]
            from_ref = tag_list[0] if tag_list else ""

        ref_range = f"{from_ref}..HEAD" if from_ref else "HEAD"
        log = subprocess.run(
            [
                "git",
                "-C",
                _rp,
                "log",
                ref_range,
                "--pretty=format:* %s",
                "--no-merges",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        commits = log.stdout.strip()

        notes = [
            f"# Release Notes — {version}",
            f"Released: {datetime.date.today().isoformat()}",
            "",
            "## What's Changed",
            "",
            commits or "No commits found.",
            "",
            f"**Full Changelog:** {from_ref}...{version}" if from_ref else "",
        ]
        return "\n".join(notes)
    except Exception as e:
        return f"[ERROR] generate_release_notes: {e}"


GENERATE_RELEASE_NOTES_TOOL: dict[str, Any] = {
    "name": "generate_release_notes",
    "description": "Generate a formatted release notes document from git history between two version tags.",
    "input_schema": {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "description": "New version number (e.g. v1.2.0)",
            },
            "from_ref": {
                "type": "string",
                "description": "Previous version tag or commit",
            },
            "repo_path": {
                "type": "string",
                "description": (
                    "Ignored — always operates on the configured project repo. "
                    "(Kept in the schema for backward compatibility with existing callers.)"
                ),
            },
        },
        "required": ["version"],
    },
}
