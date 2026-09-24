"""batch_edit tool — T2-B8 (2026-09-24, GRIDIRON_PARTIAL #257 "Modify
100+ files (dedicated batch-edit tool)").

Genuinely new capability, not a wiring fix: no generic "apply the same
find/replace transformation to an explicit, caller-specified list of
files" tool existed anywhere in this codebase before this. `rename_symbol`
(app/repo_tools/ast_engine.py) is the closest prior art but is scoped
specifically to a single identifier, glob-matched under one directory —
this tool takes an explicit file list and a literal-or-regex find/replace,
useful for changes like "update a copyright year across 200 files" or
"change an import path string across the whole repo" that aren't a single
identifier rename.

Mirrors rename_symbol's own three-stage safety pipeline exactly (same
config-driven cap, same dry-run-with-override shape, same all-or-nothing
write with rollback), plus the same GRIDIRON_PARTIAL #38 "[ARCHITECTURE
CHECK]" pass rename_symbol already runs after itself — reused here from
day one rather than retrofitted later, per that item's own plan ("...
batch-edit tool once #257 is built").
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree
from app.tools.filesystem._textio import read_text_lf, write_text_lf

BATCH_EDIT_TOOL = {
    "name": "batch_edit",
    "description": (
        "Apply the same find-and-replace transformation across an explicit list "
        "of files (not a glob — you name every file). Use for a change that "
        "isn't a single identifier rename (rename_symbol) but still needs to land "
        "identically across many files, e.g. a copyright year or an import path "
        "string. Literal substring match by default; set regex=true to use a "
        "regex pattern instead. If more files would actually change than the "
        "configured safety threshold, returns a no-write dry-run preview instead "
        "— pass confirm_large_batch=true to actually apply it. All-or-nothing: "
        "if any file fails to write, every already-written file in this call is "
        "rolled back."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit list of file paths (relative to repo root) to edit",
            },
            "find": {
                "type": "string",
                "description": "Text (or regex pattern, if regex=true) to find",
            },
            "replace": {
                "type": "string",
                "description": "Replacement text",
            },
            "regex": {
                "type": "boolean",
                "description": "Treat 'find' as a regex pattern (default: false — literal substring match)",
            },
            "confirm_large_batch": {
                "type": "boolean",
                "description": "Set true to actually apply an edit that would touch more files than the safety threshold (otherwise a dry-run preview is returned instead)",
            },
        },
        "required": ["files", "find", "replace"],
    },
}


def batch_edit_handler(root: Path, worktree_path: str, inp: dict[str, Any]) -> str:
    files = inp.get("files") or []
    if not files:
        return "[ERROR] files must be a non-empty list of file paths"
    find = str(inp.get("find", ""))
    if not find:
        return "[ERROR] find must be non-empty"
    replace = str(inp.get("replace", ""))
    use_regex = bool(inp.get("regex", False))
    confirm_large_batch = bool(inp.get("confirm_large_batch", False))

    pattern: re.Pattern[str] | None = None
    if use_regex:
        try:
            pattern = re.compile(find)
        except re.error as e:
            return f"[ERROR] invalid regex in 'find': {e}"

    skipped: list[str] = []
    candidates: list[Path] = []
    for f in files:
        f = str(f)
        policy = check_path_in_worktree(f, worktree_path)
        if not policy.allowed:
            skipped.append(f"{f} ({policy.reason})")
            continue
        fp = root / f
        if not fp.is_file():
            skipped.append(f"{f} (not found)")
            continue
        candidates.append(fp)

    # First pass: count matches per file without writing anything, so a
    # dry-run preview never has to do the rewrite work twice — same shape
    # as rename_symbol's own first pass.
    planned: list[tuple[Path, str, int]] = []  # (path, new_content, count)
    styles: dict[Path, str] = {}
    for fp in candidates:
        try:
            original, styles[fp] = read_text_lf(fp)
        except (OSError, UnicodeDecodeError) as e:
            skipped.append(f"{fp.relative_to(root).as_posix()} ({e})")
            continue
        if pattern is not None:
            modified, count = pattern.subn(replace, original)
        else:
            count = original.count(find)
            modified = original.replace(find, replace) if count else original
        if count:
            planned.append((fp, modified, count))

    skipped_note = (
        "\n[SKIPPED] " + "; ".join(skipped[:20]) + (" ..." if len(skipped) > 20 else "")
        if skipped
        else ""
    )
    if not planned:
        return f"(no occurrences of {find!r} found in the given file(s))" + skipped_note

    from app.config import get_settings

    max_files = get_settings().batch_edit_max_files
    if len(planned) > max_files and not confirm_large_batch:
        preview = "\n".join(
            f"  {fp.relative_to(root)}  ({count} occurrence(s))"
            for fp, _modified, count in planned[:50]
        )
        more = (
            f"\n  ... and {len(planned) - 50} more file(s)" if len(planned) > 50 else ""
        )
        return (
            f"[DRY RUN] {find!r} → {replace!r} would touch {len(planned)} file(s), "
            f"above the safety threshold of {max_files}. No files were written. "
            f"Preview:\n{preview}{more}\n"
            "Re-run with confirm_large_batch=true to actually apply this edit."
        )

    # All-or-nothing: refuse up front if any file cannot be written, and
    # roll back already-written files if a write still fails part-way —
    # same protection rename_symbol's own write phase provides.
    unwritable = [
        fp.relative_to(root).as_posix()
        for fp, _m, _c in planned
        if not os.access(fp, os.W_OK)
    ]
    if unwritable:
        return (
            f"[ERROR] batch_edit aborted before writing anything: "
            f"{len(unwritable)} file(s) are not writable: {', '.join(unwritable[:20])}"
            + skipped_note
        )

    changed: list[str] = []
    changed_py_count = 0
    written: list[tuple[Path, bytes]] = []
    try:
        for fp, modified, count in planned:
            before = fp.read_bytes()
            write_text_lf(fp, modified, styles[fp])
            written.append((fp, before))
            changed.append(f"  {fp.relative_to(root)}  ({count} replacement(s))")
            if fp.suffix == ".py":
                changed_py_count += 1
    except OSError as exc:
        failed_restore: list[str] = []
        for wfp, before in reversed(written):
            try:
                wfp.write_bytes(before)
            except OSError:
                failed_restore.append(wfp.relative_to(root).as_posix())
        msg = (
            f"[ERROR] batch_edit aborted: {exc}. "
            f"{len(written) - len(failed_restore)} already-written file(s) were rolled back"
        )
        if failed_restore:
            msg += f"; COULD NOT restore: {', '.join(failed_restore)}"
        return msg

    result = (
        f"Applied {find!r} → {replace!r} across {len(changed)} file(s):\n"
        + "\n".join(changed)
        + skipped_note
    )

    # GRIDIRON_PARTIAL #38 "Preserve architecture consistency across
    # multi-file edits" — same real check rename_symbol/sync_files/
    # apply_patch already run; see those modules' own comments.
    if changed_py_count > 1:
        from app.repo_tools.ast_engine import detect_circular_imports

        consistency = detect_circular_imports(worktree_path)
        if "No circular imports detected" not in consistency:
            result += f"\n\n[ARCHITECTURE CHECK] {consistency}"

    return result
