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
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": [a.arg for a in node.args.args],
                "decorators": [ast.unparse(d) for d in node.decorator_list],
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
        elif isinstance(node, ast.ClassDef):
            methods: list[str] = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": [ast.unparse(b) for b in node.bases],
                "methods": methods,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports_list.append({
                    "type": "import",
                    "module": alias.name,
                    "alias": alias.asname,
                })
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports_list.append({
                    "type": "from",
                    "module": mod,
                    "name": alias.name,
                    "alias": alias.asname,
                })

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
                        found.append(f"{ast.unparse(child.func.value)}.{child.func.attr}")
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
        fp for fp in d.rglob("*.py")
        if ".git" not in fp.parts and "__pycache__" not in fp.parts and ".venv" not in fp.parts
    ]
    if not py_files:
        return "(no .py files found)"

    defined: dict[str, str] = {}   # name → "file:line"
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
    lines = [f"⚠️  {len(dead)} potentially unused public function(s) — may have callers outside this directory:"]
    for name, loc in sorted(dead.items()):
        lines.append(f"  {name}  ← {loc}")
    return "\n".join(lines)


def detect_circular_imports(directory: str) -> str:
    """Detect circular local import chains in a Python package."""
    d = Path(directory)
    if not d.exists():
        return f"[ERROR] Directory not found: {directory}"

    py_files = [
        fp for fp in d.rglob("*.py")
        if ".git" not in fp.parts and "__pycache__" not in fp.parts and ".venv" not in fp.parts
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


def rename_symbol(old_name: str, new_name: str, directory: str, file_pattern: str = "*.py") -> str:
    """Word-boundary rename old_name → new_name across files matching file_pattern in directory."""
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
    changed: list[str] = []

    for fp in d.rglob(file_pattern):
        if any(part in (".git", "__pycache__", ".venv", "node_modules") for part in fp.parts):
            continue
        try:
            original = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count = len(pattern.findall(original))
        if count == 0:
            continue
        modified = pattern.sub(new_name, original)
        fp.write_text(modified, encoding="utf-8")
        changed.append(f"  {fp.relative_to(d)}  ({count} replacement(s))")

    if not changed:
        return f"(no occurrences of '{old_name}' found in {file_pattern!r} files under {directory!r})"
    return (
        f"Renamed '{old_name}' → '{new_name}' across {len(changed)} file(s):\n"
        + "\n".join(changed)
    )
