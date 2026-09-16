"""zip_files tool — tool_enhance.md productionization pass, tool #209
(2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: zip_files
Old path: app/agents/tools.py (`_ZIP_FILES_TOOL` schema dict,
    `zip_files_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/zip_files.py (this file) —
    `ZIP_FILES_TOOL`, `zip_files_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed:
    `CHAT_TOOLS` membership count is 1); grepped all other agent
    files, none reference `"zip_files"` in their own `allowed_tools`
    — interactive chat is the only real consumer.
Affected modules: app/agents/tools.py (`zip_files_h` delegates to the
    shared handler), app/agents/chat_agent.py (gains a real dispatch
    branch it never had — see finding #3).
Affected registries: none — app/fleet/tool_manifest.py's "zip_files"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path. Separately, `app/agents/base_graph.py::_policy_check()`'s
    generic `write_repo`-permission path-field check (`check_path()`,
    denylist-only — NOT worktree confinement) already covers
    `zip_files`'s `output` field for `run_agent_graph`-based agents —
    but since zero real agents actually dispatch this CHAT_TOOLS-only
    tool through that path (confirmed: no other agent's `allowed_tools`
    references it, and it was never wired into `chat_agent.py`
    either), that coverage was structurally present but practically
    unreachable for this specific tool until this turn's chat_agent.py
    dispatch fix — and even then, `check_path()` alone would not have
    caught the arbitrary-absolute-path escape below (it only denies a
    fixed set of protected filenames, not worktree confinement).
Affected tests: `tests/test_batch11_policy_check_structural_chokepoint.py::
    test_zip_files_protected_output_denied` exercises the unrelated,
    already-existing `_policy_check()` denylist coverage directly —
    unaffected by this change. `tests/test_new_tools.py::test_zip_unzip`
    uses only in-worktree relative paths — unaffected. New tests
    added: see tests/test_zip_files_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/zip_files.md.
---------------------------------------------------------------------------

Three real, empirically-verified findings — the write-side finding is
a severe "arbitrary file write with real, attacker-chosen content"
primitive, the same severity tier as sibling tool #206's
(`unzip_files`) `dest` finding.

1. **`output` had zero worktree-boundary validation — a genuine
   content-exfiltration primitive, not just a write-location bug.**
   `out_path = root / output` silently discards `root` when `output`
   is absolute (the standard `pathlib` behavior already documented for
   many tools this initiative). Proved live: `zip_files({"source":
   "secret_config.py", "output": "<absolute path outside repo>"})`
   genuinely wrote a REAL zip archive containing the real file's full
   content to that arbitrary absolute path — confirmed by reading the
   exfiltrated archive back and finding the real secret string inside
   it, completely outside the intended worktree.
2. **`source` had zero worktree-boundary validation.** `src_path =
   root / source` has the same discard-on-absolute behavior. An
   absolute/outside `source` does not by itself disclose content
   (`f.relative_to(root)` raises `ValueError` before any entry from
   outside `root` is written, since it's computed as the in-archive
   name), but it DOES have two real side effects: (a) it leaves a
   junk/empty `.zip` file behind at whatever `out_path` resolves to
   (which, per finding #1, may itself be an arbitrary absolute
   location when `output` is defaulted from an absolute `source`); (b)
   it is real security-relevant behavior driven entirely by
   LLM-controlled input with no validation, the same class of gap this
   initiative treats as a finding even where full disclosure isn't
   achievable through `source` alone.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206/#207/#208.**
   `zip_files` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: zip_files"`.

Fixed via a shared `zip_files_handler(root, worktree_path, inp)`: both
`source` and `output` are validated with `check_path_in_worktree()`
before either is used, closing findings #1 and #2. A new
`chat_agent.py` dispatch delegates to this same shared handler,
closing finding #3.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

ZIP_FILES_TOOL: dict[str, Any] = {
    "name": "zip_files",
    "description": "Zip a file or directory into an archive.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "File or directory to zip (relative to repo root)",
            },
            "output": {
                "type": "string",
                "description": "Output .zip file path (default: source + .zip)",
            },
        },
        "required": ["source"],
    },
}


def zip_files_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core zip_files logic. Both `source` (read) and `output` (write)
    are validated with `check_path_in_worktree()` — see this module's
    docstring for the real content-exfiltration finding this closes."""
    source = str(inp["source"])
    source_policy = check_path_in_worktree(source, worktree_path)
    if not source_policy.allowed:
        return f"[POLICY DENIED] {source_policy.reason}"

    output = str(inp.get("output", source.rstrip("/") + ".zip"))
    output_policy = check_path_in_worktree(output, worktree_path)
    if not output_policy.allowed:
        return f"[POLICY DENIED] {output_policy.reason}"

    src_path = root / source
    out_path = root / output
    try:
        with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
            if src_path.is_dir():
                for f in src_path.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(root))
            else:
                zf.write(src_path, src_path.relative_to(root))
        return f"Zipped to {output}"
    except Exception as e:
        return f"[ERROR] zip_files: {e}"
