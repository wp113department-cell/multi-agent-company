"""git_commit tool — tool_enhance.md productionization pass, tool
#37 (2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_commit
Old path: app/agents/tools.py (`_GIT_COMMIT_TOOL` schema dict and the
    `git_commit` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body)
New path: app/tools/git/commit.py (this file) — `GIT_COMMIT_TOOL`,
    `stage_and_commit()` (the shared, hardened implementation both real
    call sites now delegate to).
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other agent
    declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; `git_commit`
    handler now delegates to the shared `stage_and_commit()`),
    app/agents/chat_agent.py (its real dispatch now delegates too).
Affected registries: none — app/fleet/tool_manifest.py's "git_commit"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["git_commit"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_git_commit_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_commit.md.
---------------------------------------------------------------------------

Real finding (severe — a genuine secret-to-history leak, proven live):
neither real implementation of `git_commit` did ANY secret-content
scanning or worktree validation before staging+committing whatever
`files` named. Proved directly against a real repo through
`make_chat_handlers`'s own `git_commit`: `files=[".env"]` containing a
real-looking AWS key and a Stripe secret key was staged AND COMMITTED
into git history with zero warning, zero redaction, zero refusal —
`git show HEAD:.env` showed both secrets in plain text afterward.

This codebase already has the exact right protection built and proven
elsewhere: `make_git_commit_change_handler`'s `git_commit_change`
(app/agents/tools.py, a separate, narrower tool) already calls
`check_path_in_worktree()` per file and `_scan_content_for_secrets()` on
each file's content before ever running `git commit`, refusing with
`[POLICY DENIED]` if a secret shape is found. `git_commit` — the tool
actually advertised to and used by nearly every agent — never had this
wired in at all.

Second, smaller finding (same flag-collision shape as tools #5/#32/#35/
#36, but here git's own `git add` already refuses any file argument that
resolves outside the repository — proved empirically with both an
absolute outside-repo path and a `../`-traversal path, both rejected by
git itself with "is outside repository", exit 128, mirroring GNU
`patch`'s own protection found in tool #27): `files` entries were passed
to `git add` one at a time with no `--` pathspec separator, so a
flag-shaped entry like `-u` reaches `git add` as a real flag (scope-
widening to stage all tracked modifications, not just the named files)
rather than a literal filename. Fixed by staging with a single
`git add -- <files>` call (matching `git_commit_change`'s own pattern),
which makes git treat everything after `--` as a literal pathspec.

Fix: a new shared `stage_and_commit(repo_path, message, files)` used by
both real call sites. Stages via `git add -A` (unchanged special case
for `files == ["--all"]`/`["-a"]`) or `git add -- <files>` otherwise,
then reads back the real staged file list via `git diff --cached
--name-only` (correct for both branches, including `--all`) and scans
each staged file's on-disk content with `_scan_content_for_secrets()`
before ever calling `git commit`. Any match aborts with
`[POLICY DENIED]` and unstages everything first, leaving the repo in the
same clean state it was in before the call — a fail-closed design
mirroring `git_commit_change`'s own contract, not a new one invented for
this fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.agents.tool_security import _scan_content_for_secrets

GIT_COMMIT_TOOL = {
    "name": "git_commit",
    "description": "Stage specified files and create a git commit. Uses conventional commit format. Always run tests before committing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message (use conventional commits: feat/fix/docs/refactor: description)",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage and commit. Use ['--all'] to stage all changes.",
            },
        },
        "required": ["message", "files"],
    },
}


def stage_and_commit(repo_path: str, message: str, files: list[Any]) -> str:
    """Shared, hardened git_commit implementation used by both real call
    sites (chat_agent.py's dispatch and make_chat_handlers()).

    Stages `files` (or everything, for the documented ['--all']/['-a']
    sentinel), refuses to commit if any staged file's real on-disk
    content looks like it contains a secret, then commits. Fail-closed:
    on a secret match, everything staged by this call is unstaged again
    before returning, so a retried/adjacent call doesn't inherit
    dangling staged state.
    """
    str_files = [str(f) for f in files]
    try:
        if str_files == ["--all"] or str_files == ["-a"]:
            subprocess.run(
                ["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True
            )
        else:
            subprocess.run(
                ["git", "add", "--", *str_files],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

        staged_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        staged_files = [f for f in staged_result.stdout.splitlines() if f]

        for staged in staged_files:
            fpath = Path(repo_path) / staged
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            secret_reason = _scan_content_for_secrets(content)
            if secret_reason:
                if staged_files:
                    subprocess.run(
                        ["git", "reset", "HEAD", "--", *staged_files],
                        cwd=repo_path,
                        capture_output=True,
                    )
                return (
                    f"[POLICY DENIED] Refusing to commit {staged}: "
                    f"{secret_reason}. Remove the secret and use an "
                    "environment variable/config reference instead."
                )

        r = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        return (r.stdout + r.stderr).strip()
    except subprocess.CalledProcessError as e:
        return f"[ERROR] git add failed: {e}"
    except Exception as e:
        return f"[ERROR] {e}"
