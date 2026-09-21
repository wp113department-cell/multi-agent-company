"""replace_class tool — tool_enhance.md productionization pass, tool
#57 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: replace_class
Old path: app/agents/tools.py (`_REPLACE_CLASS_TOOL` schema dict and
    the `replace_class_h` handler inside `make_chat_handlers()`) +
    app/agents/chat_agent.py (inline dispatch body — near-identical
    logic to the tools.py handler, including the same bug below).
New path: app/tools/filesystem/replace_class.py (this file) —
    `REPLACE_CLASS_TOOL`, `replace_class_handler`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller.
    `make_chat_handlers`'s own copy is also reachable by any other
    agent declaring this tool.
Affected modules: app/agents/tools.py (schema re-export; handler now
    delegates to the shared implementation), app/agents/chat_agent.py
    (dispatch now delegates to the same shared implementation instead
    of duplicating it).
Affected registries: none — app/fleet/tool_manifest.py's
    "replace_class" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_replace_class_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/replace_class.md.
---------------------------------------------------------------------------

Worktree-boundary handling was already correct on both real
implementations (tool #11's fix, re-verified here, not re-fixed):
`_is_protected_path(path, repo_path)` is called with `repo_path` passed
as `worktree_path`, enabling full `check_path_in_worktree()`
containment checking.

**Real, severe, empirically-proven finding instead: a genuine content-
loss bug in the class-boundary-detection algorithm**, identical in both
real implementations. The end-boundary scan skipped any line starting
with `"#"`/`"@"` when looking for where the target class's block ends —
intended (presumably) to avoid stopping early on some in-between
comment/decorator, but in practice this means a decorator or comment
belonging to the NEXT top-level class/function gets silently swallowed
into (and discarded along with) the replaced target's region, instead
of being preserved as untouched file content.

Proved live against a real 4-class file: replacing the middle class
`Bar` — followed by `@dataclass\nclass Baz:` — deleted the blank lines
AND the `@dataclass` decorator entirely from the output, genuinely
corrupting `Baz`'s real behavior (a `@dataclass`-decorated class
silently losing its decorator is a real, functional regression, not
cosmetic).

Fixed by removing the `#`/`@` special-case: the end boundary is simply
the next non-blank line at or below the target class's own
indentation, full stop — a trailing decorator or comment for the *next*
symbol now correctly ends the current class's block and survives
untouched in the `after` text.

**The identical bug was also found in the sibling `replace_function`
tool (#24, already shipped)** — retroactively fixed in that same
module during this turn, matching the established precedent (tool #9)
for fixing an identical bug found affecting an already-closed tool; see
`app/tools/filesystem/replace_function.py`'s own docstring correction
note and `docs/tool_productionization/replace_function.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tool_security import _is_protected_path
import ast

from app.tools.filesystem._textio import (
    find_python_block,
    read_text_lf,
    split_keepends_lf,
    trim_trailing_blank_lines,
    write_text_lf,
)

REPLACE_CLASS_TOOL = {
    "name": "replace_class",
    "description": (
        "Replace an entire class block in a Python file by class name. "
        "Finds the class by its `class <name>` line and replaces everything up to the next "
        "top-level definition. Always read the file first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (relative to repo root)",
            },
            "class_name": {
                "type": "string",
                "description": "Name of the class to replace",
            },
            "new_code": {
                "type": "string",
                "description": "Complete new class code (including the class definition line)",
            },
        },
        "required": ["path", "class_name", "new_code"],
    },
}


def replace_class_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    """Core replace_class logic shared by every real call site. Finds
    `class <name>(`/`class <name>:`/bare `class <name>` at any
    indentation level by scanning stripped lines, then replaces through
    the next same-or-lower-indent, non-blank line (a blank line doesn't
    end the block; anything else at or below the class's own
    indentation — including a decorator or comment belonging to the
    next symbol — correctly does)."""
    rel = str(inp["path"])
    class_name = str(inp["class_name"])
    new_code = str(inp["new_code"])
    if _is_protected_path(rel, worktree_path):
        return f"[POLICY DENIED] Protected path: {rel}"
    target = root / rel
    if not target.exists():
        return f"[ERROR] File not found: {rel}"
    try:
        text, nl_style = read_text_lf(target)
        lines = split_keepends_lf(text)
        # Real syntax tree first (see replace_function for why the indentation
        # heuristic is unsafe around unindented multi-line strings).
        block = find_python_block(text, class_name, (ast.ClassDef,))
        start: int | None = None
        base_indent = 0
        for i, line in enumerate(lines):
            if block is not None:
                break
            stripped = line.strip()
            if (
                stripped.startswith(f"class {class_name}(")
                or stripped.startswith(f"class {class_name}:")
                or stripped == f"class {class_name}"
            ):
                start = i
                base_indent = len(line) - len(line.lstrip())
                break
        if block is not None:
            start, end = block
        else:
            if start is None:
                return f"[ERROR] Class '{class_name}' not found in {rel}"
            end = len(lines)
            for j in range(start + 1, len(lines)):
                jline = lines[j]
                if jline.strip() == "":
                    continue
                jindent = len(jline) - len(jline.lstrip())
                if jindent <= base_indent and jline.strip():
                    end = j
                    break
            end = trim_trailing_blank_lines(lines, start, end)
        before = "".join(lines[:start])
        after = "".join(lines[end:])
        new_code = new_code.replace("\r\n", "\n")
        new_final = new_code if new_code.endswith("\n") else new_code + "\n"
        write_text_lf(target, before + new_final + after, nl_style)
        return f"Replaced class '{class_name}' in {rel} (was lines {start + 1}–{end})"
    except Exception as e:
        return f"[ERROR] {e}"
