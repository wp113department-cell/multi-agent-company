"""read_pdf tool — tool_enhance.md productionization pass, tool #177
(2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_pdf
Old path: app/agents/tools.py (`_READ_PDF_TOOL` schema dict,
    `read_pdf_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/read_pdf.py (this file) —
    `READ_PDF_TOOL`, `read_pdf_handler`.
Affected agents: per tool_inventory.json, agents declaring `read_pdf`
    in `allowed_tools` (plus interactive chat, newly — see finding
    #2).
Affected modules: app/agents/tools.py (`read_pdf_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's "read_pdf"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes. New tests added: see
    tests/test_read_pdf_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_pdf.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings — identical shape to sibling
tool #174's `read_image`, fixed the same day.

1. **SEVERE — worktree-boundary escape, an ARBITRARY PDF FILE READ
   oracle.** `read_pdf_h` didn't just fail to validate `path` — it
   explicitly special-cased `Path(path).is_absolute()` to bypass
   `root` entirely: `fpath = Path(path) if Path(path).is_absolute()
   else root / path`. Proved live: `read_pdf({"path": "/tmp/<outside
   PDF>"})` genuinely extracted and returned the real text content
   (including a secret-shaped string) of a PDF file entirely outside
   the worktree.
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#176.**
   `read_pdf` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: read_pdf"`.

Fixed via a shared `read_pdf_handler()`: `path` is now validated with
`check_path_in_worktree()` before the file is ever opened, closing
finding #1 (the absolute-path special-case is removed entirely —
`root / path` is used unconditionally, matching every other
filesystem-reading tool in this initiative). A new `chat_agent.py`
dispatch branch delegates to this same shared handler, closing
finding #2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

READ_PDF_TOOL: dict[str, Any] = {
    "name": "read_pdf",
    "description": "Extract text content from a PDF file using pdfplumber. Returns plain text, one paragraph per page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file"},
            "max_pages": {
                "type": "integer",
                "description": "Maximum pages to extract (default: 20)",
            },
        },
        "required": ["path"],
    },
}


def read_pdf_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_pdf logic — the one real implementation, reused
    unchanged in behavior except: (1) the worktree-boundary check now
    applied to `path`, and (2) the absolute-path bypass of `root` is
    removed (an absolute `path` is now validated exactly like a
    relative one, matching every other filesystem tool)."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    max_pages = int(inp.get("max_pages", 20))
    fpath = root / path
    try:
        import pdfplumber

        pages_text: list[str] = []
        with pdfplumber.open(str(fpath)) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages]):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"--- Page {i + 1} ---\n{text.strip()}")
        if not pages_text:
            return f"[WARN] No text extracted from {fpath} (may be image-only PDF)"
        return "\n\n".join(pages_text)
    except ImportError:
        return "[ERROR] pdfplumber not installed. Run: pip install pdfplumber==0.11.10"
    except Exception as e:
        return f"[ERROR] read_pdf: {e}"
