"""Python AST analysis utilities — stdlib only, zero extra dependencies."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any


def parse_file_ast(path: str) -> str:
    """Parse a .py file and return JSON with functions, classes, and imports."""
    p = Path(path)
    if not p.exists():
        return f"[ERROR] File not found: {path}"
    if p.suffix != ".py":
        return f"[ERROR] parse_ast only supports .py files (got {p.suffix!r})"
    try:
        source = p.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(p))
    except SyntaxError as e:
        return f"[ERROR] Syntax error in {path}: {e}"

    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    imports_list: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "decorators": [ast.unparse(d) for d in node.decorator_list],
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
        elif isinstance(node, ast.ClassDef):
            methods: list[str] = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports_list.append(
                    {
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports_list.append(
                    {
                        "type": "from",
                        "module": mod,
                        "name": alias.name,
                        "alias": alias.asname,
                    }
                )

    result: dict[str, Any] = {
        "file": str(p),
        "total_lines": len(source.splitlines()),
        "functions": functions,
        "classes": classes,
        "imports": imports_list,
    }
    return json.dumps(result, indent=2)


def build_import_graph(path: str) -> str:
    """Return all imports from a .py file as a structured text report."""
    p = Path(path)
    if not p.exists():
        return f"[ERROR] File not found: {path}"
    if p.suffix != ".py":
        return f"[ERROR] import_graph only supports .py files (got {p.suffix!r})"
    try:
        source = p.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(p))
    except SyntaxError as e:
        return f"[ERROR] Syntax error in {path}: {e}"

    modules: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.setdefault(alias.name, [])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or "<relative>"
            names = [alias.name for alias in node.names]
            modules.setdefault(mod, []).extend(names)

    if not modules:
        return f"(no imports found in {p.name})"
    lines = [f"Import graph for {p.name} — {len(modules)} module(s):"]
    for mod, symbols in sorted(modules.items()):
        if symbols:
            lines.append(f"  {mod}:  {', '.join(symbols)}")
        else:
            lines.append(f"  {mod}")
    return "\n".join(lines)


def build_call_graph(path: str, function_name: str = "") -> str:
    """Return what each function calls in a .py file. Optionally limit to one function."""
    p = Path(path)
    if not p.exists():
        return f"[ERROR] File not found: {path}"
    if p.suffix != ".py":
        return "[ERROR] call_graph only supports .py files"
    try:
        source = p.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(p))
    except SyntaxError as e:
        return f"[ERROR] Syntax error in {path}: {e}"

    def _collect_calls(node: ast.AST) -> list[str]:
        found: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    found.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    try:
                        found.append(
                            f"{ast.unparse(child.func.value)}.{child.func.attr}"
                        )
                    except Exception:
                        found.append(f"<expr>.{child.func.attr}")
        return found

    results: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if function_name and node.name != function_name:
                continue
            calls = sorted(set(_collect_calls(node)))
            async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            results.append(
                f"  {async_prefix}{node.name} (L{node.lineno}): "
                + (", ".join(calls) if calls else "(no calls)")
            )

    if not results:
        if function_name:
            return f"[ERROR] Function '{function_name}' not found in {path}"
        return f"(no functions in {p.name})"

    header = f"Call graph — {p.name}" + (f" / {function_name}" if function_name else "")
    return header + "\n" + "\n".join(results)


def detect_dead_code(directory: str) -> str:
    """Heuristically find public Python functions that are never called in the directory."""
    d = Path(directory)
    if not d.exists():
        return f"[ERROR] Directory not found: {directory}"

    py_files = [
        fp
        for fp in d.rglob("*.py")
        if ".git" not in fp.parts
        and "__pycache__" not in fp.parts
        and ".venv" not in fp.parts
    ]
    if not py_files:
        return "(no .py files found)"

    defined: dict[str, str] = {}  # name → "file:line"
    called: set[str] = set()

    for fp in py_files:
        try:
            source = fp.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(fp))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private helpers and dunder methods
                if not (node.name.startswith("_") and not node.name.startswith("__")):
                    defined[node.name] = f"{fp.relative_to(d)}:{node.lineno}"
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

    dead = {name: loc for name, loc in defined.items() if name not in called}
    if not dead:
        return "✅ No obviously dead functions detected (heuristic scan)."
    lines = [
        f"⚠️  {len(dead)} potentially unused public function(s) — may have callers outside this directory:"
    ]
    for name, loc in sorted(dead.items()):
        lines.append(f"  {name}  ← {loc}")
    return "\n".join(lines)


def detect_circular_imports(directory: str) -> str:
    """Detect circular local import chains in a Python package."""
    d = Path(directory)
    if not d.exists():
        return f"[ERROR] Directory not found: {directory}"

    py_files = [
        fp
        for fp in d.rglob("*.py")
        if ".git" not in fp.parts
        and "__pycache__" not in fp.parts
        and ".venv" not in fp.parts
    ]
    if not py_files:
        return "(no .py files found)"

    # module name → set of local module deps
    graph: dict[str, set[str]] = {}
    local_roots = {d.name, "app"}

    for fp in py_files:
        rel = fp.relative_to(d)
        mod = str(rel).replace("/", ".").removesuffix(".py")
        try:
            source = fp.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(fp))
        except SyntaxError:
            graph[mod] = set()
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] in local_roots or node.level > 0:
                    deps.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] in local_roots:
                        deps.add(alias.name)
        graph[mod] = deps

    cycles: list[str] = []
    visited: set[str] = set()
    path_set: set[str] = set()
    path_list: list[str] = []

    def _dfs(node: str) -> None:
        if node in path_set:
            idx = path_list.index(node)
            cycles.append(" → ".join(path_list[idx:] + [node]))
            return
        if node in visited:
            return
        visited.add(node)
        path_set.add(node)
        path_list.append(node)
        for dep in graph.get(node, set()):
            _dfs(dep)
        path_list.pop()
        path_set.discard(node)

    for mod in graph:
        _dfs(mod)

    unique_cycles = list(dict.fromkeys(cycles))
    if not unique_cycles:
        return "✅ No circular imports detected."
    lines = [f"⚠️  {len(unique_cycles)} circular import chain(s):"]
    for c in unique_cycles[:20]:
        lines.append(f"  {c}")
    return "\n".join(lines)


def _rename_in_python_source(
    source: str, old_name: str, new_name: str
) -> tuple[str, int]:
    """Token-based rename for Python source (AUDIT_Q_BATCH01 §18 "Refactor
    projects" — the previous whole-file regex substitution matched
    old_name's text inside string literals and comments too, not just real
    identifier references). Only NAME tokens exactly equal to old_name are
    replaced, at their exact (line, column) span in the ORIGINAL text — no
    full untokenize() reconstruction, so every other character (including
    all whitespace/formatting) is left byte-identical, the same guarantee
    the regex path already had, just now identifier-aware.

    Raises tokenize.TokenizeError/IndentationError/SyntaxError on genuinely
    unparseable source — callers catch this and fall back to the regex path
    for that one file, rather than the whole rename_symbol call failing.
    """
    import io
    import tokenize as _tokenize

    tokens = list(_tokenize.generate_tokens(io.StringIO(source).readline))
    by_line: dict[int, list[tuple[int, int]]] = {}
    count = 0
    for tok in tokens:
        if tok.type == _tokenize.NAME and tok.string == old_name:
            by_line.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
            count += 1
    if count == 0:
        return source, 0

    lines = source.splitlines(keepends=True)
    for lineno, spans in by_line.items():
        line = lines[lineno - 1]
        for col_start, col_end in sorted(spans, reverse=True):
            line = line[:col_start] + new_name + line[col_end:]
        lines[lineno - 1] = line
    return "".join(lines), count


def rename_symbol(
    old_name: str,
    new_name: str,
    directory: str,
    file_pattern: str = "*.py",
    confirm_large_batch: bool = False,
) -> str:
    """Rename old_name → new_name across files matching file_pattern in
    directory. .py files (when file_pattern selects them) use a token-based
    rename that skips string/comment content; other file patterns (e.g.
    "*.ts") use the original word-boundary regex substitution, since a
    stdlib-only, zero-extra-dependency tool has no non-Python tokenizer
    available — a documented, honest limitation, not a silent gap.

    AUDIT_Q_BATCH01 §59 "Edit hundreds of files safely" — a match count
    over Settings.rename_symbol_max_files returns a dry-run preview (lists
    affected files, writes nothing) instead of rewriting an unbounded
    number of files in one call, unless confirm_large_batch=True. This is
    the safety valve the previous unconditional-write version had none of.
    """
    d = Path(directory)
    if not d.exists():
        return f"[ERROR] Directory not found: {directory}"
    if not old_name or not new_name:
        return "[ERROR] old_name and new_name must be non-empty"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", old_name):
        return f"[ERROR] old_name must be a valid identifier: {old_name!r}"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
        return f"[ERROR] new_name must be a valid identifier: {new_name!r}"

    pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")
    candidates: list[Path] = [
        fp
        for fp in d.rglob(file_pattern)
        if not any(
            part in (".git", "__pycache__", ".venv", "node_modules")
            for part in fp.parts
        )
    ]

    # First pass: count matches per file without writing anything, so a
    # dry-run preview never has to do the rewrite work twice.
    planned: list[tuple[Path, str, int]] = []  # (path, new_content, count)
    for fp in candidates:
        try:
            original = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        modified: str
        count: int
        if fp.suffix == ".py":
            try:
                modified, count = _rename_in_python_source(
                    original, old_name, new_name
                )
            except (SyntaxError, IndentationError, ValueError, OSError):
                count = len(pattern.findall(original))
                modified = pattern.sub(new_name, original) if count else original
        else:
            count = len(pattern.findall(original))
            modified = pattern.sub(new_name, original) if count else original
        if count:
            planned.append((fp, modified, count))

    if not planned:
        return f"(no occurrences of '{old_name}' found in {file_pattern!r} files under {directory!r})"

    from app.config import get_settings

    max_files = get_settings().rename_symbol_max_files
    if len(planned) > max_files and not confirm_large_batch:
        preview = "\n".join(
            f"  {fp.relative_to(d)}  ({count} occurrence(s))"
            for fp, _modified, count in planned[:50]
        )
        more = f"\n  ... and {len(planned) - 50} more file(s)" if len(planned) > 50 else ""
        return (
            f"[DRY RUN] '{old_name}' → '{new_name}' would touch {len(planned)} "
            f"file(s), above the safety threshold of {max_files}. No files "
            f"were written. Preview:\n{preview}{more}\n"
            "Re-run with confirm_large_batch=true to actually apply this rename."
        )

    changed: list[str] = []
    for fp, modified, count in planned:
        fp.write_text(modified, encoding="utf-8")
        changed.append(f"  {fp.relative_to(d)}  ({count} replacement(s))")

    result = (
        f"Renamed '{old_name}' → '{new_name}' across {len(changed)} file(s):\n"
        + "\n".join(changed)
    )

    # AUDIT_Q_BATCH01 §59 "Preserve architecture consistency" — a batch
    # rename is exactly the kind of multi-file mechanical edit that can
    # silently introduce a circular import (e.g. renaming a module-level
    # name into one already used by a sibling module it imports from). Only
    # worth the extra AST pass for a real multi-file batch, not a
    # single-file rename.
    if len(changed) > 1:
        py_files_changed = any(fp.suffix == ".py" for fp, _m, _c in planned)
        if py_files_changed:
            consistency = detect_circular_imports(str(d))
            if "No circular imports detected" not in consistency:
                result += f"\n\n[ARCHITECTURE CHECK] {consistency}"

    return result
