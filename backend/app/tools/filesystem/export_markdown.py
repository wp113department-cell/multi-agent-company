"""export_markdown tool — tool_enhance.md productionization pass, tool
#137 (2026-09-11).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: export_markdown
Old path: app/agents/tools.py (`_EXPORT_MARKDOWN_TOOL` schema dict,
    `export_markdown_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/export_markdown.py (this file) —
    `EXPORT_MARKDOWN_TOOL`, `export_markdown_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `export_markdown` in `allowed_tools` (plus interactive chat, newly
    — see finding #2).
Affected modules: app/agents/tools.py (`export_markdown_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "export_markdown" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_export_markdown_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/export_markdown.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Most severe: a worktree-boundary escape on BOTH `path` and
   `output` — a genuine ARBITRARY FILE WRITE (not just a read).**
   `export_markdown_h` built `root / str(inp["path"])` for the read
   AND `root / output_name` for the write without checking whether
   either was already absolute — the same `pathlib`-silently-
   discards-`root`-for-an-absolute-right-operand class already
   documented for tools #99/#107/#116/#120/#122/#127/#129/#132/#134/
   #135 this initiative, but here it produces a real disk write, the
   same severity class as tools #80/#100/#112's silent
   arbitrary-file-write findings. Worse still: when `output` is
   omitted, the default is DERIVED from `path`
   (`str(inp["path"]).replace(".md", ".html")`) — so an absolute
   `path` alone (with no `output` given at all) ALSO produces a
   write outside the worktree by default, without the caller ever
   supplying a malicious `output`. Proved live, in an isolated `/tmp`
   directory (never the real project, per the established safe-
   mutation-testing rule): (a) an explicit absolute `output` genuinely
   wrote a real HTML file outside the intended worktree; (b) an
   absolute `path` with no `output` at all also wrote outside the
   worktree, via the derived-default path.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136.**
   `export_markdown` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` has NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: export_markdown"`.

Fixed via a shared `export_markdown_handler()`: both `path` and the
resolved `output` (the caller-supplied value, or the same
`path`-derived default the original computed) are validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1 for both the read and the write, and for both the explicit-
`output` and default-`output` cases. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

EXPORT_MARKDOWN_TOOL: dict[str, Any] = {
    "name": "export_markdown",
    "description": "Render a Markdown file to HTML and save it. Returns the output HTML file path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Markdown file path (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output HTML file path (default: same name + .html)",
            },
        },
        "required": ["path"],
    },
}


def export_markdown_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core export_markdown logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to both the read (`path`) and the write (the
    resolved `output`, explicit or default-derived)."""
    rel = str(inp["path"])
    policy = check_path_in_worktree(rel, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    output_name = str(inp.get("output", rel.replace(".md", ".html")))
    policy = check_path_in_worktree(output_name, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / rel
    out_path = root / output_name
    try:
        text = fpath.read_text(encoding="utf-8")
        try:
            import markdown

            html = markdown.markdown(text, extensions=["fenced_code", "tables"])
        except ImportError:
            html = f"<pre>{text}</pre>"
        out_path.write_text(
            f"<!DOCTYPE html><html><body>{html}</body></html>", encoding="utf-8"
        )
        return f"Exported to {output_name}"
    except Exception as e:
        return f"[ERROR] export_markdown: {e}"
