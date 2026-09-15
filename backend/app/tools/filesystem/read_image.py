"""read_image tool — tool_enhance.md productionization pass, tool
#174 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: read_image
Old path: app/agents/tools.py (`_READ_IMAGE_TOOL` schema dict,
    `read_image_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/read_image.py (this file) —
    `READ_IMAGE_TOOL`, `read_image_handler`.
Affected agents: per tool_inventory.json, agents declaring
    `read_image` in `allowed_tools` (plus interactive chat, newly —
    see finding #2).
Affected modules: app/agents/tools.py (`read_image_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "read_image" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_read_image_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/read_image.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **SEVERE — worktree-boundary escape, an ARBITRARY IMAGE FILE READ
   oracle, WORSE than the usual `pathlib`-silently-discards-`root`
   class.** `read_image_h` didn't just fail to validate `path` — it
   explicitly special-cased `Path(path).is_absolute()` to bypass
   `root` entirely: `fpath = Path(path) if Path(path).is_absolute()
   else root / path`. Both access vectors were proved live:
   `read_image({"path": "/tmp/<outside image>"})` genuinely read and
   returned the real format/mode/size metadata plus a base64-encoded
   PNG thumbnail of an image file entirely outside the worktree, and
   `read_image({"path": "../secret.png"})` (relative traversal)
   equally succeeded. This is a real arbitrary-file-read primitive
   for any file PIL can open as an image (which includes many
   non-image formats it will still attempt to parse).
2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173.**
   `read_image` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch at all. Proved live: a
   real call through the real `chat_agent.py` dispatch returned
   `"[ERROR] Unknown tool: read_image"`.

Fixed via a shared `read_image_handler()`: `path` is now validated
with `check_path_in_worktree()` before the file is ever opened,
closing finding #1 for BOTH the absolute and relative access vectors
(the absolute-path special-case is removed entirely — `root / path`
is used unconditionally, matching every other filesystem-reading tool
in this initiative). A new `chat_agent.py` dispatch branch delegates
to this same shared handler, closing finding #2.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

READ_IMAGE_TOOL: dict[str, Any] = {
    "name": "read_image",
    "description": "Read an image file and return basic metadata (format, size, mode) plus a base64-encoded thumbnail for vision inspection.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the image file (PNG, JPG, GIF, BMP, WebP)",
            },
        },
        "required": ["path"],
    },
}


def read_image_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core read_image logic — the one real implementation, reused
    unchanged in behavior except: (1) the worktree-boundary check now
    applied to `path`, and (2) the absolute-path bypass of `root` is
    removed (an absolute `path` is now validated exactly like a
    relative one, matching every other filesystem tool)."""
    path = str(inp["path"])
    policy = check_path_in_worktree(path, worktree_path)
    if not policy.allowed:
        return f"[POLICY DENIED] {policy.reason}"

    fpath = root / path
    try:
        from PIL import Image

        img = Image.open(str(fpath))
        meta = {
            "format": img.format,
            "mode": img.mode,
            "size": f"{img.width}x{img.height}",
            "path": str(fpath),
        }
        thumb = img.copy()
        thumb.thumbnail((256, 256))
        buf = io.BytesIO()
        thumb.save(buf, format="PNG")
        b64_thumb = base64.b64encode(buf.getvalue()).decode()
        return (
            f"Image: {meta['path']}\n"
            f"Format: {meta['format']} | Mode: {meta['mode']} | Size: {meta['size']}\n"
            f"Thumbnail (base64 PNG, 256x256): {b64_thumb[:200]}…"
        )
    except Exception as e:
        return f"[ERROR] read_image: {e}"
