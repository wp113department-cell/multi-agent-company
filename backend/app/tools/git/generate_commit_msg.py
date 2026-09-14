"""generate_commit_msg tool — tool_enhance.md productionization pass,
tool #145 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_commit_msg
Old path: app/agents/tools.py (`_GENERATE_COMMIT_MSG_TOOL` schema
    dict) with TWO real, near-identical implementations:
    `generate_commit_msg` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch.
New path: app/tools/git/generate_commit_msg.py (this file) —
    `GENERATE_COMMIT_MSG_TOOL`, `generate_commit_msg_handler`. BOTH
    real call sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `generate_commit_msg` in `allowed_tools` (plus interactive chat,
    which already had a real dispatch — unlike most other tools this
    initiative, this one was never missing its dispatch branch).
Affected modules: app/agents/tools.py (its own closure delegates to
    the shared handler), app/agents/chat_agent.py (its dispatch now
    calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_commit_msg" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_generate_commit_msg_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_commit_msg.md.
---------------------------------------------------------------------------

No LLM-controlled filesystem path anywhere in this tool's input schema
(only a boolean `staged_only`) — the worktree-boundary-escape class
established repeatedly this initiative does not apply here, and both
real implementations already use list-args `subprocess.run(["git",
...], cwd=repo_path)` with no `shell=True` anywhere, so shell injection
does not apply either — checked directly, not assumed.

One real finding — a message-accuracy bug on BOTH real
implementations: when `staged_only=False` (checking the UNSTAGED
working-tree diff) and there are genuinely no unstaged changes, the
"no changes" error unconditionally said `"No staged changes. Stage
files with git_commit or git add first."` — factually backwards in
that mode (there is no unstaged diff; staging has nothing to do with
it, and the advice to stage files doesn't apply when the caller
explicitly asked to look at unstaged changes). Proved live: a real
git repo with a clean working tree and `staged_only=False` produced
this exact misleading message.

Fixed via a shared `generate_commit_msg_handler()`: the "no changes"
message is now conditional on `staged_only`, correctly describing
staged vs. unstaged state and giving the right suggestion for each
mode. `_llm_generate_commit_message()` (a private helper in
`app/agents/tools.py`, used only by this one tool — confirmed via
grep, not a broadly-shared utility like `_llm_generate_text`) is
deliberately left in place and passed into this handler as an injected
`generate_fn` callable, matching the same pattern already established
for tool #136's `explain_merge_conflict` — avoiding a circular import
without needing to relocate anything.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

GENERATE_COMMIT_MSG_TOOL = {
    "name": "generate_commit_msg",
    "description": "Generate a conventional commit message via LLM from the real staged diff, plus the raw diff summary it was grounded in. Falls back to just the raw diff summary if generation is unavailable.",
    "input_schema": {
        "type": "object",
        "properties": {
            "staged_only": {
                "type": "boolean",
                "description": "Use only staged changes (default: true)",
            },
        },
        "required": [],
    },
}


def generate_commit_msg_handler(
    repo_path: str, inp: dict[str, Any], generate_fn: Callable[[str, str], str]
) -> str:
    """Core generate_commit_msg logic shared by both real call sites.
    `generate_fn` is the LLM-backed commit-message generator
    (`_llm_generate_commit_message` in app.agents.tools), injected by
    the caller to avoid a circular import."""
    staged = bool(inp.get("staged_only", True))
    diff_args = ["diff", "--cached"] if staged else ["diff"]
    stat_args = diff_args + ["--stat"]
    r_stat = subprocess.run(
        ["git"] + stat_args, cwd=repo_path, capture_output=True, text=True
    )
    r_diff = subprocess.run(
        ["git"] + diff_args, cwd=repo_path, capture_output=True, text=True
    )
    stat = r_stat.stdout.strip()
    diff = r_diff.stdout[:3000]
    if not stat:
        if staged:
            return (
                "[ERROR] No staged changes. Stage files with git_commit "
                "or git add first."
            )
        return "[ERROR] No unstaged changes to describe."

    generated = generate_fn(stat, diff)
    if generated:
        return (
            f"=== Generated commit message ===\n{generated}\n\n"
            f"=== Changed files ===\n{stat}\n\n"
            f"=== Diff (truncated to 3000 chars) ===\n{diff}"
        )
    return (
        f"=== Changed files ===\n{stat}\n\n"
        f"=== Diff (truncated to 3000 chars) ===\n{diff}\n\n"
        "Analyze the diff above and write a conventional commit message:\n"
        "Format: <type>(<scope>): <description>\n"
        "Types: feat, fix, docs, refactor, test, chore, style, perf"
    )
