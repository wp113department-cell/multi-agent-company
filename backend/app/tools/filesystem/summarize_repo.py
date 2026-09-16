"""summarize_repo tool — tool_enhance.md productionization pass, tool
#203 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: summarize_repo
Old path: app/agents/tools.py (`_SUMMARIZE_REPO_TOOL` schema dict,
    `summarize_repo_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/summarize_repo.py (this file) —
    `SUMMARIZE_REPO_TOOL`, `summarize_repo_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"summarize_repo"` in their own
    `allowed_tools` — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`summarize_repo_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "summarize_repo" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: `tests/test_day2_tools.py` checks tool-list membership
    and handler callability only — no test ever passed an explicit
    `repo_path` override, so ignoring it structurally (finding #1's
    fix, matching sibling tool #100's `generate_changelog` precedent)
    changes no existing test's observed behavior; re-run and confirmed
    passing unchanged. New tests added: see
    tests/test_summarize_repo_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/summarize_repo.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — this is exactly the deferred
item logged in tool #100's (`generate_changelog`) own docstring:
"The sibling tool `summarize_repo_h`, right next to this one in
tools.py, has the identical unvalidated `repo_path`-override pattern
reaching `os.walk()` — out of scope for this turn, logged in
`tool_enhance_tracking.md` for its own future turn." This turn closes
that deferred item.

1. **`repo_path` is an LLM-controlled field that lets the caller
   redirect the ENTIRE summary at an arbitrary host directory,
   completely outside the intended worktree.** `summarize_repo_h`'s
   original body did `_rp = str(inp.get("repo_path", repo_path))` and
   then passed `_rp` directly to `os.walk()` and to a raw
   `os.path.join()` + `open()` for the README excerpt — zero
   validation. Proved live: pointing `repo_path` at an arbitrary host
   directory outside the intended project worktree genuinely
   disclosed that OTHER directory's real file tree, file-extension
   breakdown, and (when present) README content. There is no
   legitimate use case for letting the LLM redirect a repo-summary
   tool at an unrelated host directory — pure scope-escape, not a
   documented capability, exactly the same reasoning already applied
   to `generate_changelog`'s finding #2.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202.**
   `summarize_repo` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: summarize_repo"`.

Fixed via a shared `summarize_repo_handler(root, inp)`, mirroring
`generate_changelog_handler`'s exact precedent: the `repo_path` field
from `inp` is IGNORED entirely — `root` (the handler factory's own
configured worktree) is always used, closing finding #1 structurally
rather than trying to validate an arbitrary-directory override. A new,
real `chat_agent.py` dispatch delegates to this same shared handler,
closing finding #2. All other behavior (3-level directory tree,
extension breakdown, README excerpt, output formatting) preserved
verbatim.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SUMMARIZE_REPO_TOOL: dict[str, Any] = {
    "name": "summarize_repo",
    "description": "Generate a high-level summary of the repository: file tree (top 3 levels), line counts, language breakdown, and README excerpt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": (
                    "Ignored — always operates on the configured project repo. "
                    "(Kept in the schema for backward compatibility with existing callers.)"
                ),
            }
        },
        "required": [],
    },
}


def summarize_repo_handler(root: Path, inp: dict[str, Any]) -> str:
    """Core summarize_repo logic. `inp.get('repo_path')` is
    deliberately ignored — this always operates on `root`, the
    worktree the handler was built for. See this module's docstring
    (finding #1) for why an LLM-controlled repo_path override is
    rejected rather than validated."""
    _rp = str(root)
    try:
        # File tree (3 levels)
        tree_lines: list[str] = []
        for dirpath, dirnames, filenames in os.walk(_rp):
            dirnames[:] = [
                d
                for d in sorted(dirnames)
                if d not in (".git", ".venv", "node_modules", "__pycache__")
            ]
            depth = dirpath.replace(_rp, "").count(os.sep)
            if depth > 2:
                continue
            indent = "  " * depth
            tree_lines.append(f"{indent}{os.path.basename(dirpath)}/")
            if depth < 2:
                for f in sorted(filenames)[:10]:
                    tree_lines.append(f"{indent}  {f}")

        # Line counts by extension
        ext_counts: dict[str, int] = {}
        total_files = 0
        for dirpath, dirnames, filenames in os.walk(_rp):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in (".git", ".venv", "node_modules", "__pycache__")
            ]
            for fname in filenames:
                ext = os.path.splitext(fname)[1] or "other"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                total_files += 1

        top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:8]

        # README excerpt
        readme_excerpt = ""
        for rname in ("README.md", "readme.md", "README.rst"):
            rpath = os.path.join(_rp, rname)
            if os.path.exists(rpath):
                with open(rpath, encoding="utf-8", errors="ignore") as rf:
                    readme_excerpt = rf.read(800)
                break

        summary = [
            f"## Repository Summary: {os.path.basename(_rp)}",
            f"Total files: {total_files}",
            "",
            "### Top file types",
        ]
        for ext, count in top_exts:
            summary.append(f"  {ext:10} {count}")
        summary += ["", "### Directory tree (3 levels)"] + tree_lines[:50]
        if readme_excerpt:
            summary += ["", "### README (first 800 chars)", readme_excerpt]
        return "\n".join(summary)
    except Exception as e:
        return f"[ERROR] summarize_repo: {e}"
