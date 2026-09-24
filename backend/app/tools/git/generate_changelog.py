"""generate_changelog tool — tool_enhance.md productionization pass,
tool #100 (2026-08-25).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_changelog
Old path: app/agents/tools.py (`_GENERATE_CHANGELOG_TOOL` schema dict)
    with ONE real implementation: `generate_changelog_h` (inside
    `make_chat_handlers()`). `app/agents/chat_agent.py` had ZERO
    dispatch branch for this tool despite it being advertised in
    `CHAT_TOOLS` — the same "advertised but never dispatched" class
    already established for tools #4/#6/#22/#25/#33/#44/#45/#46/#48.
New path: app/tools/git/generate_changelog.py (this file) —
    `GENERATE_CHANGELOG_TOOL`, `generate_changelog_handler`. The real
    implementation now delegates to this shared handler, and a new
    real dispatch has been wired into `chat_agent.py`.
Affected agents: per tool_inventory.json, agents declaring
    `generate_changelog` in `allowed_tools` go through
    `make_chat_handlers()`.
Affected modules: app/agents/tools.py (its closure delegates to the
    shared handler), app/agents/chat_agent.py (new real dispatch
    added).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_changelog" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day2_tools.py::TestGenerateChangelogHandler`
    calls the handler with an explicit `repo_path` field pointing at
    the outer project root (deliberately different from the handler
    factory's own configured `.../backend` path) — checked directly
    (not assumed): `git -C <subdir> log` works identically from any
    subdirectory of a git worktree, so ignoring the LLM-supplied
    `repo_path` override (finding #2's fix) and always using the
    factory's own configured repo_path does not change these tests'
    real behavior — re-run and confirmed passing unchanged. New tests
    added: see tests/test_generate_changelog_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_changelog.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings.

1. **The most severe finding class of this initiative — silent
   arbitrary-file-write, same class as tool #80's `git_show`.**
   `from_ref`/`to_ref` are LLM-controlled and, when `from_ref` is
   empty (the common case), `to_ref` becomes the ENTIRE `ref_range`
   argv element handed directly to `git log` with zero validation.
   `git log` accepts a generic `--output=<path>` flag. Proved live
   with the EXACT real command shape this tool builds:
   `to_ref="--output=/tmp/.../PWNED_VIA_TOOL.txt"` (with `from_ref`
   empty) genuinely wrote a real file to an arbitrary host path — the
   tool's own returned text gives ZERO indication anything was
   written (`log.stdout` is empty, so the caller sees only "No commits
   found between start and --output=...").

2. **`repo_path` is an LLM-controlled field that lets the caller
   redirect ALL git operations at an arbitrary host directory,
   completely outside the intended worktree.** Proved live: pointing
   `repo_path` at a real git repository outside the intended project
   worktree genuinely disclosed that OTHER repo's full commit history
   (subjects + author names) through `git -C <arbitrary-dir> log`.
   There is no legitimate use case for letting the LLM redirect a
   changelog-generation tool at an unrelated host repository — this is
   pure scope-escape, not a documented capability. (The sibling tool
   `summarize_repo_h`, right next to this one in `tools.py`, has the
   identical unvalidated `repo_path`-override pattern reaching
   `os.walk()` — out of scope for this turn, logged in
   `tool_enhance_tracking.md` for its own future turn.)

3. **"Advertised but never dispatched"** (see migration report above)
   — `chat_agent.py` had zero dispatch branch despite the tool being
   fully advertised in `CHAT_TOOLS`; every real interactive call would
   have hit "Unknown tool".

Fixed via a shared `generate_changelog_handler(root, inp)`:
 - the `repo_path` field from `inp` is IGNORED entirely — `root` (the
   handler factory's own configured worktree) is always used, closing
   finding #2 structurally rather than trying to validate an
   arbitrary-directory override;
 - `validate_git_ref(from_ref)` / `validate_git_ref(to_ref)` reject
   any ref starting with `-`, matching the `git_checkout`/
   `git_merge`/`git_rebase`/`git_cherry_pick`/`git_pull` validator
   precedent already established across this initiative — closes
   finding #1;
 - a new, real `chat_agent.py` dispatch delegates to this same shared
   handler, closing finding #3.
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import Any


def validate_git_ref(ref: str) -> str | None:
    """Returns an [ERROR] string if `ref` is flag-shaped, else None.

    `from_ref`/`to_ref` are LLM-controlled and (when `from_ref` is
    empty) `to_ref` alone becomes the entire `ref_range` argv element
    handed to `git log` — a leading `-` is consumed as one of git's
    own flags (e.g. `--output=<path>`, a real arbitrary-file-write
    primitive — proved live, see this module's docstring) rather than
    a literal ref. Flag-shaped refs are rejected outright, matching
    the `git_checkout`/`git_merge`/`git_rebase` precedent."""
    if ref.startswith("-"):
        return (
            f"[ERROR] Invalid ref {ref!r} — refs may not start with '-' "
            "(this would be interpreted as a git flag, not a ref — e.g. "
            "'--output=<path>' silently writes an arbitrary file)."
        )
    return None


def generate_changelog_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core generate_changelog logic. `inp.get('repo_path')` is
    deliberately ignored — this always operates on `root`, the
    worktree the handler was built for. See this module's docstring
    (finding #2) for why an LLM-controlled repo_path override is
    rejected rather than validated."""
    _rp = str(root)
    from_ref = str(inp.get("from_ref", ""))
    to_ref = str(inp.get("to_ref", "HEAD"))

    if from_ref:
        error = validate_git_ref(from_ref)
        if error:
            return error
    error = validate_git_ref(to_ref)
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
            from_ref = (
                tag_list[1] if len(tag_list) >= 2 else tag_list[0] if tag_list else ""
            )

        ref_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
        log = subprocess.run(
            [
                "git",
                "-C",
                _rp,
                "log",
                ref_range,
                "--pretty=format:%s (%an)",
                "--no-merges",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        commits = log.stdout.strip().splitlines()
        if not commits:
            return f"No commits found between {from_ref or 'start'} and {to_ref}"

        sections: dict[str, list[str]] = {
            "Added": [],
            "Changed": [],
            "Fixed": [],
            "Other": [],
        }
        for c in commits:
            cl = c.lower()
            if cl.startswith(("feat:", "add ", "new ")):
                sections["Added"].append(f"- {c}")
            elif cl.startswith(("fix:", "bug ", "patch ")):
                sections["Fixed"].append(f"- {c}")
            elif cl.startswith(("refactor:", "chore:", "update ", "change ")):
                sections["Changed"].append(f"- {c}")
            else:
                sections["Other"].append(f"- {c}")

        lines_out = [
            f"## [Unreleased] — {datetime.date.today().isoformat()}",
            f"Changes from {from_ref or 'start'} to {to_ref}",
            "",
        ]
        for sec, items in sections.items():
            if items:
                lines_out.append(f"### {sec}")
                lines_out.extend(items)
                lines_out.append("")
        return "\n".join(lines_out)
    except Exception as e:
        return f"[ERROR] generate_changelog: {e}"


GENERATE_CHANGELOG_TOOL: dict[str, Any] = {
    "name": "generate_changelog",
    "description": "Generate a CHANGELOG.md entry from git log between two refs (Keep-a-Changelog format). Returns the changelog text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_ref": {
                "type": "string",
                "description": "Starting git ref (tag or commit). Defaults to previous tag.",
            },
            "to_ref": {
                "type": "string",
                "description": "Ending git ref (default: HEAD)",
            },
            "repo_path": {
                "type": "string",
                "description": (
                    "Ignored — always operates on the configured project repo. "
                    "(Kept in the schema for backward compatibility with existing callers.)"
                ),
            },
        },
        "required": [],
    },
}
