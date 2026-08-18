"""apply_patch tool — tool_enhance.md productionization pass, tool #27
(2026-08-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: apply_patch
Old path: app/agents/tools.py (`_APPLY_PATCH_TOOL_DEF` schema dict and the
    `apply_patch` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body, the vulnerable one)
New path: app/tools/filesystem/apply_patch.py (this file) —
    `APPLY_PATCH_TOOL`, `apply_patch_handler`.
Affected agents: 1 per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy (already correctly guarded) is also
    reachable by any other agent declaring this tool.
Affected modules: app/agents/tools.py (compatibility re-export, handler
    delegates to the shared function), app/agents/chat_agent.py (its real
    dispatch now calls the shared handler via `asyncio.to_thread` instead
    of duplicating the unguarded logic inline).
Affected registries: none — app/fleet/tool_manifest.py's "apply_patch"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file path.
Affected tests: none required changes — every existing real test accesses
    this tool via `handlers["apply_patch"](...)` or
    `ChatAgent._execute_tool`. New tests added: see
    tests/test_apply_patch_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/apply_patch.md.
---------------------------------------------------------------------------

Real finding (severe — a proven, live protected-path bypass):
`chat_agent.py`'s real dispatch wrote the LLM-controlled `patch` content
straight to a temp file and ran the real `patch` CLI against it with
**zero validation of what file(s) the patch actually targets** —
`apply_patch`'s schema has no top-level `path` field (targets are
embedded in the diff's own `+++`/`---` header lines), so none of this
codebase's usual path checks ever had anything to inspect.
`make_chat_handlers`'s own implementation already closed this (a prior,
cited audit finding — "Blocker 1", audit_v1.md 4.5/4.8) via
`_extract_patch_target_paths()` (parses every real target path out of
the diff's own headers) + `_is_protected_path()` on each one — but
`chat_agent.py`'s dispatch, the actual live path real users talk to,
never had it.

Proved directly, before writing any fix: a real unified diff targeting
`.env` — a file every other write-capable tool in this codebase refuses
to touch — was applied successfully through `chat_agent.py`'s dispatch,
genuinely overwriting the file's real content. Separately investigated
(and could not reproduce) a classic patch-path-traversal exploit
(absolute paths / `../` in the diff headers) — this system's GNU `patch`
binary already refuses those with its own built-in "Ignoring
potentially dangerous file name" check. That protection is external and
version/OS-dependent, not something this codebase controls, so the
shared handler still validates every target path itself (matching
`make_chat_handlers`'s already-correct, defense-in-depth approach)
rather than relying solely on the installed `patch` binary's own
behavior.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any

from app.agents.tool_security import _extract_patch_target_paths, _is_protected_path

APPLY_PATCH_TOOL = {
    "name": "apply_patch",
    "description": "Apply a unified diff patch (git diff format) to files in the repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Unified diff string (output of git diff or diff -u)",
            },
            "strip": {
                "type": "integer",
                "description": "Strip N leading path components (like patch -pN, default: 1)",
            },
        },
        "required": ["patch"],
    },
}


def apply_patch_handler(repo_path: str, inp: dict[str, Any]) -> str:
    patch_content = str(inp["patch"])
    strip = int(inp.get("strip", 1))

    # Blocker 1 fix (audit_v1.md 4.5/4.8): apply_patch's schema has no
    # top-level "path" field (targets are embedded in the diff's own
    # +++/--- header lines), so any generic tool_input.get("path", "")
    # style gate silently passes. Extract every target path from the diff
    # text itself and run each through the same worktree-containment +
    # denylist check every other write tool enforces.
    target_paths = _extract_patch_target_paths(patch_content, strip)
    if not target_paths:
        return (
            "[ERROR] Could not determine any target file path from the "
            "patch's +++/--- headers — refusing to apply"
        )
    for tp in target_paths:
        if _is_protected_path(tp, repo_path):
            return f"[POLICY DENIED] apply_patch target {tp!r} is denied by policy"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False
        ) as pf:
            pf.write(patch_content)
            pf_name = pf.name
    except Exception as e:
        return f"[ERROR] Cannot write patch file: {e}"
    try:
        r = subprocess.run(
            ["patch", f"-p{strip}", "--input", pf_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or "Patch applied"
    except FileNotFoundError:
        return "[ERROR] 'patch' command not found"
    except subprocess.TimeoutExpired:
        return "[ERROR] patch timed out"
    except Exception as e:
        return f"[ERROR] {e}"
    finally:
        try:
            os.unlink(pf_name)
        except Exception:
            pass
