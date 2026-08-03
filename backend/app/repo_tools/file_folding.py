"""File folding — Stage 2 Days 45-47 (Context compression beyond Stage-1
basics, answers.md's own flagged gap: "understand 9,000+ line files:
PARTIAL — read_file does p.read_text() with no offset/limit/chunking or
size cap... no truncation/chunking safeguard").

Repo-first pattern (CLAUDE.md's own lookup table names roo-code's
src/core/condense/ for this exact problem): read
repos/roo-code/src/core/condense/foldedFileContext.ts before writing this —
its real technique is to replace a large file's full body with a
signature-only structural view (function/class names + line ranges) via
tree-sitter, rather than either loading the whole file unconditionally or
dropping it. Adapted here to reuse this project's own real tree-sitter
symbol extraction (app/repo_tools/scanner.py::parse_single_file) instead of
a second, duplicate tree-sitter integration.
"""

from __future__ import annotations

from pathlib import Path

from app.repo_tools.scanner import parse_single_file


def fold_file_content(path: Path, max_chars: int) -> str | None:
    """Returns a signature-only structural view of a source file (one line
    per function/class/method: line range, kind, name, base classes), or
    None when the file's extension isn't tree-sitter-parseable — the caller
    should fall back to a plain bounded truncation for those (a .md/.json/
    .txt file has no "symbols" to fold to).

    Truncates the *symbol list itself* at max_chars, same fallback shape
    roo-code's own reference implementation uses when even the folded
    (already much smaller) representation would still be too large.
    """
    parsed = parse_single_file(path)
    if parsed is None:
        return None
    symbols, _imports = parsed
    if not symbols:
        return None

    header = f"## Folded file structure: {path.name} ({len(symbols)} symbols)"
    lines = [header]
    total_chars = len(header)
    for sym in symbols:
        bases = f"({', '.join(sym.bases)})" if sym.bases else ""
        line = f"{sym.line_start}-{sym.line_end} | {sym.kind} {sym.name}{bases}"
        if total_chars + len(line) + 1 > max_chars:
            lines.append("... (truncated — folding budget exceeded)")
            break
        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines)
