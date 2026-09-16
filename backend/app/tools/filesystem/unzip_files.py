"""unzip_files tool — tool_enhance.md productionization pass, tool
#206 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: unzip_files
Old path: app/agents/tools.py (`_UNZIP_FILES_TOOL` schema dict,
    `unzip_files_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/unzip_files.py (this file) —
    `UNZIP_FILES_TOOL`, `unzip_files_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"unzip_files"` in their own
    `allowed_tools` — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`unzip_files_h` delegates to
    the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's
    "unzip_files" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: `tests/test_new_tools.py::test_zip_and_unzip_files`
    passes a relative `dest="extracted"` and only asserted on the
    RETURNED STRING content, never on the extracted file actually
    existing at the expected location — a real, pre-existing coverage
    gap this turn also closes (see Tests section) rather than a
    behavior this fix breaks. Re-run and confirmed passing, now with a
    real assertion added on top. New tests added: see
    tests/test_unzip_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/unzip_files.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings — a severe "arbitrary file
write" class primitive, worse than most `path`-only worktree-escape
findings this initiative because BOTH the read side (`archive`) and
the write side (`dest`) were uncontrolled.

1. **`dest` resolution was fully broken, not merely unvalidated — a
   genuine logic bug that also amounted to an arbitrary-directory-
   write primitive.** The original ternary,
   `dest_path = root / dest if not (root / dest).is_absolute() else
   Path(dest)`, is a tautology: since `root` (the configured repo
   root) is always itself an absolute path, `root / dest` is ALWAYS
   absolute regardless of `dest`'s own shape — so `not (root /
   dest).is_absolute()` is ALWAYS `False`, and `dest_path` ALWAYS
   evaluated to the `else` branch, `Path(dest)`, completely
   discarding `root` in every real call. Proved live two ways:
   (a) a relative `dest` (the schema's own documented common case)
   resolves against the process's current working directory instead
   of the repo root — a real functional bug, not just insecure;
   (b) an absolute `dest` extracts a real archive's content to that
   exact absolute path with zero repo confinement — proved live with
   a real archive extracted to a directory completely outside the
   intended worktree.
2. **`archive` (the source zip) had zero worktree-boundary
   validation** — `root / archive` never checked, the same class
   already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#202/#203/#204
   this initiative, letting the tool read and extract an arbitrary
   host `.zip` file the caller can name by absolute path.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204.**
   `unzip_files` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: unzip_files"`.

**Investigated and REFUTED, not treated as a finding**: classic
"zip slip" path-traversal via crafted archive entry names (`../` or
absolute-path entries inside the zip itself). Proved live against this
project's real Python 3.12.3 `zipfile.extractall()`: both a
`../../../../tmp/PWNED.txt`-shaped entry and a `/etc/PWNED.txt`-shaped
entry were correctly sanitized and confined inside the destination
directory — CPython's `zipfile` module has included this protection
since Python 3.6.4/2.7.15. Not a real vulnerability on this real
runtime; not fixed because there was nothing real to fix.

Fixed via a shared `unzip_files_handler(root, worktree_path, inp)`:
`archive` is validated with `check_path_in_worktree()` before opening,
closing finding #2; `dest` is now correctly resolved against `root`
when relative (matching the schema's own documented contract) and then
ALSO validated with `check_path_in_worktree()` regardless of shape,
closing finding #1 both as a functional fix and a security fix. A new
`chat_agent.py` dispatch delegates to this same shared handler,
closing finding #3.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

UNZIP_FILES_TOOL: dict[str, Any] = {
    "name": "unzip_files",
    "description": "Extract a .zip archive to a directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "archive": {
                "type": "string",
                "description": ".zip file path (relative to repo root)",
            },
            "dest": {
                "type": "string",
                "description": "Destination directory (default: archive directory)",
            },
        },
        "required": ["archive"],
    },
}


def unzip_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core unzip_files logic. Both `archive` (read) and `dest` (write)
    are validated with `check_path_in_worktree()` — see this module's
    docstring for the real dest-resolution logic bug and the two
    worktree-escape findings this closes. Zip-slip via crafted archive
    entry names was investigated and empirically refuted on this
    project's real Python runtime — `zipfile.extractall()` already
    sanitizes traversal/absolute entry names."""
    archive = str(inp["archive"])
    archive_policy = check_path_in_worktree(archive, worktree_path)
    if not archive_policy.allowed:
        return f"[POLICY DENIED] {archive_policy.reason}"

    dest = str(inp.get("dest", str((root / archive).parent)))
    dest_policy = check_path_in_worktree(dest, worktree_path)
    if not dest_policy.allowed:
        return f"[POLICY DENIED] {dest_policy.reason}"

    arc_path = root / archive
    dest_path = Path(dest) if Path(dest).is_absolute() else root / dest
    try:
        with zipfile.ZipFile(str(arc_path), "r") as zf:
            zf.extractall(str(dest_path))
        return f"Extracted {archive} to {dest}"
    except Exception as e:
        return f"[ERROR] unzip_files: {e}"
