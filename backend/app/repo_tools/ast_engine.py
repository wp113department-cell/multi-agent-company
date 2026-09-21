"""Python AST analysis utilities — stdlib only, zero extra dependencies."""

from __future__ import annotations

import ast
import json
import os
import re
import tokenize
from pathlib import Path
from typing import Any

from app.tools.filesystem._textio import (
    read_text_lf,
    split_keepends_lf,
    write_text_lf,
)


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


def get_call_edges(path: str, function_name: str = "") -> list[dict[str, Any]] | str:
    """Structured core of build_call_graph() below — extracted (AUDIT_Q_
    BATCH14 §99 gap-closure, 2026-08-12) so real caller/callee data is
    available to generate_diagram_h (app/agents/tools.py) without
    re-implementing this AST walk or fragile-parsing build_call_graph()'s
    own formatted text output, matching this module's own
    _find_dead_code()/detect_dead_code() extraction precedent above.
    build_call_graph()'s formatted text is unchanged by this extraction.
    Returns a `[ERROR] ...` string (not a list) on the same failure cases
    build_call_graph() already special-cases, so callers can check
    `isinstance(result, str)` the same way."""
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

    edges: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if function_name and node.name != function_name:
                continue
            edges.append(
                {
                    "caller": node.name,
                    "line": node.lineno,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "calls": sorted(set(_collect_calls(node))),
                }
            )

    if not edges and function_name:
        return f"[ERROR] Function '{function_name}' not found in {path}"
    return edges


def build_call_graph(path: str, function_name: str = "") -> str:
    """Return what each function calls in a .py file. Optionally limit to one function."""
    p = Path(path)
    edges = get_call_edges(path, function_name)
    if isinstance(edges, str):
        return edges
    if not edges:
        return f"(no functions in {p.name})"

    results: list[str] = []
    for edge in edges:
        async_prefix = "async " if edge["is_async"] else ""
        calls = edge["calls"]
        results.append(
            f"  {async_prefix}{edge['caller']} (L{edge['line']}): "
            + (", ".join(calls) if calls else "(no calls)")
        )

    header = f"Call graph — {p.name}" + (f" / {function_name}" if function_name else "")
    return header + "\n" + "\n".join(results)


def _find_dead_code(directory: str) -> dict[str, str] | None:
    """Structured core of detect_dead_code() below — extracted (AUDIT_Q_
    BATCH16 §91 gap-closure, 2026-08-11) so a real count is available to
    app/fleet/architecture_drift.py without re-implementing this AST walk
    or fragile-parsing detect_dead_code()'s own rendered text. Returns None
    when the directory doesn't exist or has no .py files (the same two
    "nothing to report" cases detect_dead_code() already special-cases);
    an empty dict means "scanned, zero found" — a real, different signal
    from None. detect_dead_code()'s own text output is unchanged by this
    extraction — verified by this module's existing tests, which assert on
    detect_dead_code()'s literal text."""
    d = Path(directory)
    if not d.exists():
        return None

    py_files = [
        fp
        for fp in d.rglob("*.py")
        if ".git" not in fp.parts
        and "__pycache__" not in fp.parts
        and ".venv" not in fp.parts
    ]
    if not py_files:
        return None

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

    return {name: loc for name, loc in defined.items() if name not in called}


def detect_dead_code(directory: str) -> str:
    """Heuristically find public Python functions that are never called in the directory."""
    if not Path(directory).exists():
        return f"[ERROR] Directory not found: {directory}"

    dead = _find_dead_code(directory)
    if dead is None:
        return "(no .py files found)"
    if not dead:
        return "✅ No obviously dead functions detected (heuristic scan)."
    lines = [
        f"⚠️  {len(dead)} potentially unused public function(s) — may have callers outside this directory:"
    ]
    for name, loc in sorted(dead.items()):
        lines.append(f"  {name}  ← {loc}")
    return "\n".join(lines)


def _import_time_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Imports that execute when the module is imported: module level (through if/try/with and
    class bodies), NOT inside function bodies (deferred — the standard way to break a cycle, and
    used all over this codebase) and NOT under `if TYPE_CHECKING:`."""
    found: list[ast.Import | ast.ImportFrom] = []

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            elif isinstance(node, ast.If):
                test = ast.unparse(node.test)
                if "TYPE_CHECKING" not in test:
                    visit(node.body)
                visit(node.orelse)
            else:
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    visit(handler.body)

    visit(getattr(tree, "body", []))
    return found


def _find_circular_import_cycles(
    directory: str,
) -> tuple[list[str], int] | None:
    """Structured core of detect_circular_imports() below — extracted
    (AUDIT_Q_BATCH16 §91 gap-closure, 2026-08-11), same rationale as
    _find_dead_code() above. Returns (unique_cycles, total_import_edges) or
    None when there's nothing to scan. total_import_edges is the sum of
    each module's real local-import dependency count — a real, cheap
    "how big is the import graph right now" signal architecture_drift.py
    also tracks, alongside the cycle count."""
    d = Path(directory)
    if not d.exists():
        return None

    py_files = [
        fp
        for fp in d.rglob("*.py")
        if ".git" not in fp.parts
        and "__pycache__" not in fp.parts
        and ".venv" not in fp.parts
    ]
    if not py_files:
        return None

    # module name → set of local module deps.
    #
    # B8 verification — the old builder only treated an import as local when its first
    # component was the scanned directory's own name (or "app"), recorded `from pkg import
    # mod` as a dependency on `pkg` (never on pkg.mod), left relative imports unresolved, and
    # named modules relative to the scanned directory: `from pkg import b` / `from . import b`
    # cycles between sibling modules — the usual way cycles happen — were never seen, and
    # scanning `app/` itself found nothing because nodes were `agents.x` while imports said
    # `app.agents.x`. Imports are now resolved against the modules that actually exist.
    modules: dict[str, Path] = {}
    for fp in py_files:
        parts = list(fp.relative_to(d).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        if parts:
            modules[".".join(parts)] = fp
    known = set(modules)

    def _resolve(name: str) -> str | None:
        """Map an absolute dotted import onto an existing module node, tolerating that the scan
        root may be inside the import root (drop leading components until one matches).
        """
        parts = name.split(".")
        for start in range(len(parts)):
            candidate = ".".join(parts[start:])
            if candidate in known:
                return candidate
        return None

    graph: dict[str, set[str]] = {}
    for mod, fp in modules.items():
        try:
            source = fp.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(fp))
        except SyntaxError:
            graph[mod] = set()
            continue
        package = mod if fp.name == "__init__.py" else mod.rpartition(".")[0]
        deps: set[str] = set()
        for node in _import_time_imports(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = package.split(".") if package else []
                    keep = len(base_parts) - (node.level - 1)
                    if keep < 0:
                        continue
                    base = ".".join(base_parts[:keep])
                    if node.module:
                        base = f"{base}.{node.module}" if base else node.module
                    absolute = True
                else:
                    base = node.module or ""
                    absolute = False
                targets = [
                    f"{base}.{alias.name}" if base else alias.name
                    for alias in node.names
                ]
                for target in targets:
                    hit = (
                        known & {target} if absolute else ({_resolve(target)} - {None})
                    )
                    if not hit and base:
                        hit = (
                            (known & {base})
                            if absolute
                            else ({_resolve(base)} - {None})
                        )
                    deps.update(h for h in hit if h)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    hit = _resolve(alias.name)
                    if hit:
                        deps.add(hit)
        deps.discard(mod)
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
    total_edges = sum(len(deps) for deps in graph.values())
    return unique_cycles, total_edges


def detect_circular_imports(directory: str) -> str:
    """Detect circular local import chains in a Python package."""
    if not Path(directory).exists():
        return f"[ERROR] Directory not found: {directory}"

    found = _find_circular_import_cycles(directory)
    if found is None:
        return "(no .py files found)"
    unique_cycles, _total_edges = found
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

    # Split on "\n" only — the way `tokenize` counts lines. str.splitlines also
    # splits on form feed / \x1c-\x1e / \x85 / \u2028 / \u2029, which put every
    # later edit on the wrong line and corrupted the file (proved live).
    lines = split_keepends_lf(source)
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

    from app.policy.engine import check_path

    pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")
    root_real = os.path.realpath(d)
    candidates: list[Path] = []
    skipped: list[str] = []
    for fp in d.rglob(file_pattern):
        if not fp.is_file() or any(
            part in (".git", "__pycache__", ".venv", "node_modules")
            for part in fp.parts
        ):
            continue
        rel = fp.relative_to(d).as_posix()
        # Never write through a symlink that leaves the tree (proved live: a
        # symlinked file pointing OUTSIDE the repo was rewritten), and never
        # touch a path the write tools' own policy protects (.env*, secrets/,
        # .github/workflows/, keys, .git/) — a rename with file_pattern="*"
        # used to rewrite all of them.
        real = os.path.realpath(fp)
        if not (
            real == root_real or real.startswith(root_real.rstrip(os.sep) + os.sep)
        ):
            skipped.append(f"{rel} (symlink leaves the directory)")
            continue
        if not check_path(rel).allowed:
            skipped.append(f"{rel} (protected path)")
            continue
        candidates.append(fp)

    # First pass: count matches per file without writing anything, so a
    # dry-run preview never has to do the rewrite work twice.
    planned: list[tuple[Path, str, int]] = []  # (path, new_content, count)
    styles: dict[Path, str] = {}
    for fp in candidates:
        try:
            original, styles[fp] = read_text_lf(fp)
        except (OSError, UnicodeDecodeError):
            continue
        modified: str
        count: int
        if fp.suffix == ".py":
            try:
                modified, count = _rename_in_python_source(original, old_name, new_name)
            except (
                SyntaxError,
                IndentationError,
                ValueError,
                OSError,
                tokenize.TokenError,  # unbalanced brackets / unterminated string
            ):
                count = len(pattern.findall(original))
                modified = pattern.sub(new_name, original) if count else original
        else:
            count = len(pattern.findall(original))
            modified = pattern.sub(new_name, original) if count else original
        if count:
            planned.append((fp, modified, count))

    skipped_note = (
        "\n[SKIPPED] " + "; ".join(skipped[:20]) + (" ..." if len(skipped) > 20 else "")
        if skipped
        else ""
    )
    if not planned:
        return (
            f"(no occurrences of '{old_name}' found in {file_pattern!r} files under "
            f"{directory!r})" + skipped_note
        )

    from app.config import get_settings

    max_files = get_settings().rename_symbol_max_files
    if len(planned) > max_files and not confirm_large_batch:
        preview = "\n".join(
            f"  {fp.relative_to(d)}  ({count} occurrence(s))"
            for fp, _modified, count in planned[:50]
        )
        more = (
            f"\n  ... and {len(planned) - 50} more file(s)" if len(planned) > 50 else ""
        )
        return (
            f"[DRY RUN] '{old_name}' → '{new_name}' would touch {len(planned)} "
            f"file(s), above the safety threshold of {max_files}. No files "
            f"were written. Preview:\n{preview}{more}\n"
            "Re-run with confirm_large_batch=true to actually apply this rename."
        )

    # All-or-nothing: refuse up front if any file cannot be written, and roll
    # back already-written files if a write still fails part-way. Before this a
    # single PermissionError escaped as an uncaught exception and left the
    # project half-renamed (a.py renamed, b.py not) with nothing to undo it.
    unwritable = [
        fp.relative_to(d).as_posix()
        for fp, _m, _c in planned
        if not os.access(fp, os.W_OK)
    ]
    if unwritable:
        return (
            f"[ERROR] rename_symbol aborted before writing anything: "
            f"{len(unwritable)} file(s) are not writable: {', '.join(unwritable[:20])}"
            + skipped_note
        )
    changed: list[str] = []
    written: list[tuple[Path, bytes]] = []
    try:
        for fp, modified, count in planned:
            before = fp.read_bytes()
            write_text_lf(fp, modified, styles[fp])
            written.append((fp, before))
            changed.append(f"  {fp.relative_to(d)}  ({count} replacement(s))")
    except OSError as exc:
        failed_restore: list[str] = []
        for wfp, before in reversed(written):
            try:
                wfp.write_bytes(before)
            except OSError:
                failed_restore.append(wfp.relative_to(d).as_posix())
        msg = (
            f"[ERROR] rename_symbol aborted: {exc}. "
            f"{len(written) - len(failed_restore)} already-written file(s) were rolled back"
        )
        if failed_restore:
            msg += f"; COULD NOT restore: {', '.join(failed_restore)}"
        return msg

    result = (
        f"Renamed '{old_name}' → '{new_name}' across {len(changed)} file(s):\n"
        + "\n".join(changed)
        + skipped_note
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
