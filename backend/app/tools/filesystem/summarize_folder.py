"""summarize_folder tool — tool_enhance.md productionization pass,
tool #202 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: summarize_folder
Old path: app/agents/tools.py (`_SUMMARIZE_FOLDER_TOOL` schema dict,
    `summarize_folder_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/summarize_folder.py (this file) —
    `SUMMARIZE_FOLDER_TOOL`, `summarize_folder_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"summarize_folder"` in their own
    `allowed_tools` — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`summarize_folder_h`
    delegates to the shared handler), app/agents/chat_agent.py (gains
    a real dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "summarize_folder" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes (zero pre-existing tests
    referenced this tool at all — `tool_inventory.json` correctly
    lists 0 test files). New tests added: see
    tests/test_summarize_folder_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/summarize_folder.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — a pre-existing code comment
at this tool's old location in tools.py claimed "No LLM-controlled
input reaches disk or a subprocess... so no injection/worktree
surface exists," which this turn's own independent, direct
investigation disproves for finding #1 below (ZERO HALLUCINATION per
tool_enhance.md — the comment was not trusted, the real code was read
and exercised).

1. **Worktree-boundary escape — a real file-existence/absolute-path
   disclosure oracle.** `summarize_folder_h` built `folder = root /
   sf_path` without checking whether `sf_path` was already absolute —
   the same `pathlib`-silently-discards-`root`-for-an-absolute-right-
   operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144
   this initiative. Proved live: `summarize_folder({"path":
   "/tmp/<outside dir>"})` genuinely walked and read the real content
   of a `.py` file entirely outside the intended worktree; the
   `fp.relative_to(root)` call immediately after the read raises
   `ValueError` for an out-of-root file, which the tool's own broad
   `except Exception` catches and surfaces as `f"[ERROR reading
   {fp.name}] {e}"` — and Python's own `ValueError` message for a
   failed `relative_to()` embeds the FULL real absolute path of the
   out-of-worktree file (confirmed live: the error text contained the
   file's true `/tmp/...` path). A narrower disclosure than tools
   #99/etc.'s full structured-content leaks (line/function/class
   counts are silently discarded on this path, not disclosed), but a
   real, exploitable file-existence-and-absolute-path oracle outside
   the worktree — not "no surface" as the old comment claimed.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144.**
   `summarize_folder` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: summarize_folder"`. This finding was
   already correctly identified in the old location's own comment.

Fixed via a shared `summarize_folder_handler()`: `path` is validated
with `check_path_in_worktree()` before any filesystem access, closing
finding #1. A new `chat_agent.py` dispatch branch delegates to this
same shared handler, closing finding #2. All other behavior (up-to-20
file cap, `extensions` filtering, per-file line/function/class counts)
preserved verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

SUMMARIZE_FOLDER_TOOL: dict[str, Any] = {
    "name": "summarize_folder",
    "description": "Return a concise summary of every .py/.ts file in a folder (up to 20 files).",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative folder path to summarize",
            },
            "extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File extensions to include (default: .py, .ts, .tsx)",
            },
        },
        "required": ["path"],
    },
}


def summarize_folder_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core summarize_folder logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path`."""
    sf_path = str(inp.get("path", "."))
    policy = check_path_in_worktree(sf_path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    exts = set(inp.get("extensions", [".py", ".ts", ".tsx"]))
    results: list[str] = []
    folder = root / sf_path
    if not folder.exists():
        return f"[ERROR] Path not found: {sf_path}"
    count = 0
    for fp in sorted(folder.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix not in exts:
            continue
        if count >= 20:
            results.append("(truncated — 20 file limit)")
            break
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            n_lines = len(lines)
            n_funcs = sum(
                1
                for ln in lines
                if ln.strip().startswith("def ") or ln.strip().startswith("async def ")
            )
            n_classes = sum(1 for ln in lines if ln.strip().startswith("class "))
            rel = fp.relative_to(root)
            results.append(
                f"**{rel}** — {n_lines} lines, {n_funcs} functions, {n_classes} classes"
            )
        except Exception as e:
            results.append(f"[ERROR reading {fp.name}] {e}")
        count += 1
    return "\n".join(results) if results else "(no matching files)"
