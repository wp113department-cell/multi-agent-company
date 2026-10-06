"""git_commit_change tool — tool_enhance.md productionization pass,
tool #213 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: git_commit_change
Old path: app/agents/tools.py (`_GIT_COMMIT_CHANGE_TOOL` schema dict,
    `make_git_commit_change_handler()` factory — the one real
    implementation, shared by every real caller).
New path: app/tools/git/commit_change.py (this file) —
    `GIT_COMMIT_CHANGE_TOOL`, `make_git_commit_change_handler`.
Affected agents: exactly 4 real agents, confirmed via direct grep of
    every real `"git_commit_change"` reference — `agent_debugger`,
    `knowledge_curator`, `quality_auditor`, `agent_performance_reviewer`
    (matching `tool_inventory.json`'s `agent_count: 4` exactly — this
    tool's inventory metadata was accurate, unlike several NO_MANIFEST
    siblings audited earlier in this initiative). Deliberately NOT in
    `CHAT_TOOLS` — confirmed via membership check (count is 0); this
    is the APPLY-phase-only, human-approval-gated counterpart to
    `git_commit` (tool #37), not exposed to interactive chat.
Affected modules: app/agents/tools.py re-exports the schema and
    factory under their old names — all 4 real consumer files
    continue `from app.agents.tools import make_git_commit_change_handler`
    unchanged.
Affected registries: none — app/fleet/tool_manifest.py's
    "git_commit_change" entry (if present) is pure metadata, keyed by
    tool NAME not file path.
Affected tests: 3 existing test files already exercise this tool
    (`tests/test_tools_py_file_ops_worktree_boundary_hardening.py`,
    `tests/test_git_commit_hardening.py`, `tests/test_day9_fleet_agents.py`
    — `tool_inventory.json`'s "0 test files" is a heuristic false
    negative, the same class already documented for tools #3/#7). All
    re-run and confirmed passing unchanged, no fix needed. New tests
    added: see tests/test_git_commit_change_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/git_commit_change.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found. This tool is
notable in this initiative as the REFERENCE implementation another
tool was fixed to match: tool #37's (`git_commit`) own docstring cites
this exact tool — "This codebase already has the exact right
protection built and proven elsewhere:
`make_git_commit_change_handler`'s `git_commit_change`... already
calls `check_path_in_worktree()` per file and
`_scan_content_for_secrets()` on each file's content before ever
running `git commit`" — and `git_commit`'s own fix was explicitly
modeled on this tool's contract, not a new one invented for it.

Audited directly (not assumed safe from that reputation):

- Every file in `files` is validated with `check_path_in_worktree()`
  before anything else — a real worktree-escape rejection, re-verified
  live via the existing `test_git_commit_change_rejects_outside_repo_file`
  test.
- Every in-worktree file's real on-disk content is scanned with
  `_scan_content_for_secrets()` before staging — a real secret-to-
  history-leak guard, the exact protection `git_commit` (tool #37) was
  missing and had to add.
- `git add -- <files>` already uses the `--` pathspec separator (the
  same flag-collision protection tool #37 had to add for `git_commit`,
  and the same class of fix as tools #5/#32/#35/#36) — a flag-shaped
  entry like `-u` cannot widen staging scope here; it was never
  vulnerable to this class in the first place.
- `message` reaches `git commit -m <message>` as a single, separate
  argv element via `subprocess.run([...])` with no `shell=True` — no
  shell injection surface, and git's own `-m` option parsing always
  consumes the very next argv element as a literal value regardless of
  its content, so a flag-shaped message cannot be reinterpreted as a
  flag either.
- The one theoretical gap investigated — an uncaught exception from
  `Path.is_file()` on an edge-case path (e.g. a non-directory component
  in the middle of the path) — was checked directly against this
  Python version's real `pathlib` behavior: it catches the underlying
  `OSError` internally and returns `False` rather than raising, so
  this is not a real crash risk.

Modularized purely for structural consistency with the rest of this
initiative — no behavior change.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.agents.tool_security import _scan_content_for_secrets
from app.policy.engine import check_path_in_worktree

GIT_COMMIT_CHANGE_TOOL: dict[str, Any] = {
    "name": "git_commit_change",
    "description": "Stage exactly the named files (never all changes) and commit them. Only usable in the APPLY phase, after a human has approved this specific fix.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths (relative to repo root) to stage. Never pass a wildcard — list every file explicitly.",
            },
            "message": {"type": "string", "description": "Commit message."},
        },
        "required": ["files", "message"],
    },
}


def _identity_fallback(repo_path: str) -> list[str]:
    """`-c user.name/-c user.email` only when git has no identity for this
    repo. A fresh server or container user has none, and every fleet APPLY
    commit then failed ("Author identity unknown") — found when GitHub CI
    ran the self-improvement cycle test (audit 15). A configured identity
    always wins."""
    probe = subprocess.run(
        ["git", "config", "user.email"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return []
    return ["-c", "user.name=Gridiron Agent", "-c", "user.email=agent@gridiron.local"]


def make_git_commit_change_handler(repo_path: str) -> Any:
    """Factory shared by all 4 real APPLY-phase agents (agent_debugger,
    knowledge_curator, quality_auditor, agent_performance_reviewer).
    Already-correct worktree/secret-scan/pathspec-separator protection
    — see this module's own docstring — preserved verbatim."""

    def git_commit_change(inp: dict[str, Any]) -> str:
        files = [str(f) for f in (inp.get("files") or [])]
        message = str(inp.get("message", "")).strip()
        if not files:
            return "[ERROR] files is required — list every file explicitly, never a wildcard"
        if not message:
            return "[ERROR] message is required"

        for f in files:
            result = check_path_in_worktree(f, repo_path)
            if not result.allowed:
                return f"[POLICY DENIED] {f}: {result.reason}"
            fpath = Path(repo_path) / f
            if fpath.is_file():
                try:
                    fcontent = fpath.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    fcontent = ""
                secret_reason = _scan_content_for_secrets(fcontent)
                if secret_reason:
                    return (
                        f"[POLICY DENIED] Refusing to commit {f}: {secret_reason}. "
                        "Remove the secret and use an environment variable/config "
                        "reference instead."
                    )

        try:
            add_result = subprocess.run(
                ["git", "add", "--"] + files,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add_result.returncode != 0:
                return f"[ERROR] git add failed: {add_result.stderr.strip()}"
            commit_result = subprocess.run(
                ["git", *_identity_fallback(repo_path), "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if commit_result.returncode != 0:
                return f"[ERROR] git commit failed: {(commit_result.stdout + commit_result.stderr).strip()}"
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            sha = sha_result.stdout.strip()
            return f"Committed {len(files)} file(s) as {sha[:12]}: {message}"
        except subprocess.TimeoutExpired:
            return "[ERROR] git operation timed out"
        except Exception as exc:
            return f"[ERROR] {exc}"

    return git_commit_change
