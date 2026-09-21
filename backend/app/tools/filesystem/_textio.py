"""Shared text I/O for the line-editing filesystem tools (edit_file,
insert_*, delete_*, replace_function/class, append_file, write_file, sync_files).

Verification batch B1 (item #30, "preserve formatting"), defects proved live:

* Every one of these tools read with `Path.read_text()` (universal newlines:
  CRLF -> LF on read) and wrote back plain LF, so a one-word edit to a CRLF file
  silently rewrote EVERY line ending (a whole-file diff, broken diffs/blame, and
  a broken build for tools that require CRLF).
* replace_function / replace_class located the end of a block with an
  indentation heuristic, so a function containing an unindented multi-line
  string (SQL, templates, help text - very common) was only partly replaced: the
  tool reported success and left the rest of the old body behind, producing a file
  that no longer parses. They also swallowed the blank lines separating the block
  from the next symbol.

Helpers here keep each tool's own logic unchanged: text is handled with "\\n"
line endings internally and converted back to the file's own style on write.
"""

from __future__ import annotations

import ast
from pathlib import Path

_STYLE_SNIFF_BYTES = 256 * 1024


def _style_of(raw: str) -> str:
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def read_text_lf(path: Path) -> tuple[str, str]:
    """(text with "\\n" line endings, the file's newline style: "\\r\\n" or
    "\\n"). A leading BOM is kept as a character so it survives a round trip."""
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    return raw.replace("\r\n", "\n"), _style_of(raw)


def write_text_lf(path: Path, text: str, style: str = "\n") -> None:
    """Write `text` (LF endings) using the file's original newline `style`."""
    text = text.replace("\r\n", "\n")
    data = text.replace("\n", style) if style != "\n" else text
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(data)


def existing_newline_style(path: Path) -> str | None:
    """Newline style of an existing text file, or None if it doesn't exist /
    can't be read."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            return _style_of(f.read(_STYLE_SNIFF_BYTES))
    except OSError:
        return None


def adapt_to_style(content: str, style: str | None) -> str:
    """Convert pure-LF `content` to CRLF when the file it is going into is CRLF.
    Content that already carries CRLF (intentional) is left exactly as given."""
    if style == "\r\n" and "\r\n" not in content:
        return content.replace("\n", "\r\n")
    return content


def split_keepends_lf(text: str) -> list[str]:
    """Split on "\\n" ONLY (keeping it), unlike str.splitlines which also splits
    on form feed / \\x1c-\\x1e / \\x85 / \\u2028 / \\u2029 and would misalign with
    `ast` line numbers."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def find_python_block(
    source: str, name: str, kinds: tuple[type, ...]
) -> tuple[int, int] | None:
    """0-based, end-exclusive line range of the first `def`/`class` called
    `name` (in source order), computed from the real syntax tree — or None if
    the file doesn't parse / the symbol isn't found (caller falls back to its
    heuristic). Decorators are not part of the range (same as before)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    nodes = [n for n in ast.walk(tree) if isinstance(n, kinds) and n.name == name]  # type: ignore[attr-defined]
    if not nodes:
        return None
    node = min(nodes, key=lambda n: (n.lineno, n.col_offset))  # type: ignore[attr-defined]
    end = getattr(node, "end_lineno", None)
    if end is None:
        return None
    return node.lineno - 1, int(end)  # type: ignore[attr-defined]


def trim_trailing_blank_lines(lines: list[str], start: int, end: int) -> int:
    """Move `end` back over blank lines so the separator between a replaced
    block and whatever follows it is preserved."""
    while end > start + 1 and lines[end - 1].strip() == "":
        end -= 1
    return end
