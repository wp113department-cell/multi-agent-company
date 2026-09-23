"""Code hygiene detectors — T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396
"Broken imports / unused files / duplicate functions detection").

Task 1's own verification of this item found dead code (a duplicated def
name is silently overwritten, reported once — app.repo_tools.ast_engine's
own `_find_dead_code` dict is keyed by name only), unused imports
(ruff F401, via app.tools.execution.find_unused_imports) and circular
imports (app.repo_tools.ast_engine's own `_find_circular_import_cycles`)
already real — but NO detector existed for broken/unresolvable imports,
unused files, or duplicate/cloned functions (as opposed to duplicated
NAMES, which _find_dead_code's dict-overwrite already silently masks
rather than detects). These three are that missing capability.

Stdlib only, matching app.repo_tools.ast_engine's own "zero extra
dependencies" convention — this module is a sibling to it, not a
replacement.

Real, honest limitations (stated up front):
  - Broken-import resolution can only see what THIS interpreter's sys.path
    (plus the scanned directory itself, prepended temporarily) can resolve
    — a module genuinely available only via some runtime sys.path
    manipulation invisible to a static scan is a real false-positive risk,
    same class of limitation any static import checker has. An import
    inside a `try: ... except (ImportError, ModuleNotFoundError):` block
    is deliberately never flagged — that is the standard, correct Python
    idiom for an optional dependency, not a bug.
  - Unused-file detection is import-graph-based: a file that's only ever
    invoked as a script (`python foo.py`), loaded via a plugin/entry-point
    mechanism, or is itself a test file (pytest discovers and runs these,
    it doesn't import them from other test files) is deliberately excluded
    from candidacy — flagging those would be a real false-positive class,
    not a genuine finding.
  - Duplicate-function detection compares each function's AST body
    structure with names/literals normalized away — a real structural
    clone detector, not a byte-for-byte diff — but it only catches clones
    within the SAME scanned tree in one pass; it is not a cross-repo or
    incremental index.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_EXCLUDED_DIR_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def _iter_py_files(root: Path) -> list[Path]:
    return [
        fp
        for fp in root.rglob("*.py")
        if not (_EXCLUDED_DIR_PARTS & set(fp.parts))
    ]


def _is_guarded_by_import_error_handler(tree: ast.AST, target: ast.stmt) -> bool:
    """True if `target` (an Import/ImportFrom node) sits inside a
    `try: ... except (ImportError, ModuleNotFoundError, ...):` block — the
    standard idiom for an optional dependency, never a real broken import."""

    def handles_import_error(handler: ast.ExceptHandler) -> bool:
        if handler.type is None:
            return True  # bare except also legitimately guards this
        names = (
            [n.id for n in handler.type.elts if isinstance(n, ast.Name)]
            if isinstance(handler.type, ast.Tuple)
            else [handler.type.id] if isinstance(handler.type, ast.Name) else []
        )
        # Exception/BaseException are real superclasses of ImportError —
        # `except Exception:` genuinely catches it too, not just the
        # narrower ImportError/ModuleNotFoundError spelling.
        return bool(
            {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"} & set(names)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            target is stmt or (hasattr(stmt, "body") and target in ast.walk(stmt))
            for stmt in node.body
        ):
            if any(handles_import_error(h) for h in node.handlers):
                return True
    return False


@dataclass
class BrokenImport:
    file: str
    line: int
    module: str


def find_broken_imports(directory: str) -> list[BrokenImport] | None:
    """Real, resolvable-or-not check for every top-level import in
    `directory`'s .py files — not a claim of the LLM's own memory of
    whether a package exists. Returns None for "nothing to scan" (matches
    _find_dead_code's own convention); [] means scanned, zero found."""
    root = Path(directory)
    if not root.exists():
        return None
    py_files = _iter_py_files(root)
    if not py_files:
        return None

    root_str = str(root.resolve())
    sys.path.insert(0, root_str)
    try:
        broken: list[BrokenImport] = []
        for fp in py_files:
            try:
                source = fp.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(fp))
            except SyntaxError:
                continue
            rel = str(fp.relative_to(root))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_level = alias.name.split(".")[0]
                        if not _resolves(top_level) and not _is_guarded_by_import_error_handler(
                            tree, node
                        ):
                            broken.append(BrokenImport(rel, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        # Relative import — resolved by real file existence,
                        # not sys.path (package context for an arbitrary
                        # scanned tree isn't reliably computable otherwise).
                        if node.module is None:
                            continue  # "from . import x" — the package itself; skip, too ambiguous to check per-name reliably
                        if not _relative_import_resolves(fp, node.level, node.module):
                            if not _is_guarded_by_import_error_handler(tree, node):
                                broken.append(
                                    BrokenImport(rel, node.lineno, "." * node.level + node.module)
                                )
                        continue
                    if node.module is None:
                        continue
                    top_level = node.module.split(".")[0]
                    if not _resolves(top_level) and not _is_guarded_by_import_error_handler(
                        tree, node
                    ):
                        broken.append(BrokenImport(rel, node.lineno, node.module))
        return broken
    finally:
        try:
            sys.path.remove(root_str)
        except ValueError:
            pass


def _resolves(top_level_module: str) -> bool:
    try:
        return importlib.util.find_spec(top_level_module) is not None
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False


def _relative_import_resolves(from_file: Path, level: int, module: str) -> bool:
    base = from_file.parent
    for _ in range(level - 1):
        base = base.parent
    target = base
    for part in module.split("."):
        target = target / part
    return (target.with_suffix(".py")).exists() or (target / "__init__.py").exists()


_ENTRY_POINT_STEMS = {"main", "manage", "wsgi", "asgi", "conftest", "setup"}


def find_unused_files(directory: str) -> list[str] | None:
    """Files never referenced by any import anywhere else in `directory`'s
    own tree. Deliberately excludes __init__.py (package marker, not
    meant to be individually imported by name), conventional entry-point
    filenames (main.py, manage.py, conftest.py, ...), and test_*.py/
    *_test.py (pytest discovers and runs these directly — it doesn't
    import them from other application code, so "never imported" is
    expected, not a finding)."""
    root = Path(directory)
    if not root.exists():
        return None
    py_files = _iter_py_files(root)
    if not py_files:
        return None

    module_to_file: dict[str, Path] = {}
    for fp in py_files:
        rel = fp.relative_to(root)
        if fp.name == "__init__.py":
            dotted = ".".join(rel.parent.parts)
        else:
            dotted = ".".join(rel.with_suffix("").parts)
        if dotted:
            module_to_file[dotted] = fp

    referenced: set[Path] = set()
    for fp in py_files:
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"), filename=str(fp))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _mark_referenced(alias.name, module_to_file, referenced)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    # Real relative-import resolution: base_dir is the
                    # directory `level` steps up from this file's own
                    # location (level=1 == this file's own containing
                    # directory, Python's real semantics for both a plain
                    # module and an __init__.py alike).
                    base_dir = fp.parent
                    for _ in range(node.level - 1):
                        base_dir = base_dir.parent
                    if node.module:
                        # "from .c import thing" -> base_dir/c
                        target = base_dir
                        for part in node.module.split("."):
                            target = target / part
                        rel_dotted = _dotted_from_path(target, root)
                        if rel_dotted:
                            _mark_referenced(rel_dotted, module_to_file, referenced)
                    else:
                        # "from . import b, c" -> base_dir/b, base_dir/c
                        for alias in node.names:
                            rel_dotted = _dotted_from_path(base_dir / alias.name, root)
                            if rel_dotted:
                                _mark_referenced(rel_dotted, module_to_file, referenced)
                elif node.module:
                    _mark_referenced(node.module, module_to_file, referenced)
                    # "from mypkg import helper" — `helper` may itself be a
                    # real submodule (mypkg/helper.py), not just an
                    # attribute of mypkg/__init__.py; check both, same
                    # ambiguity the relative "from . import b" case above
                    # already resolves by checking the real filesystem.
                    for alias in node.names:
                        _mark_referenced(
                            f"{node.module}.{alias.name}", module_to_file, referenced
                        )

    unused: list[str] = []
    for dotted, fp in module_to_file.items():
        if fp in referenced:
            continue
        if fp.name == "__init__.py":
            continue
        stem = fp.stem
        if stem in _ENTRY_POINT_STEMS or stem.startswith("test_") or stem.endswith("_test"):
            continue
        unused.append(str(fp.relative_to(root)))
    return sorted(unused)


def _dotted_from_path(path_no_suffix: Path, root: Path) -> str | None:
    """Best-effort dotted module path for `path_no_suffix` (no .py suffix
    yet) relative to `root` — None if it resolves outside the scanned tree
    (e.g. a relative import that walks above the scan root)."""
    try:
        return ".".join(path_no_suffix.relative_to(root).parts)
    except ValueError:
        return None


def _mark_referenced(
    dotted_import: str, module_to_file: dict[str, Path], referenced: set[Path]
) -> None:
    # Match the import against every real local module, longest-prefix
    # first ("from a.b.c import d" referencing local package "a.b" as well
    # as "a.b.c" if both exist) — real dotted-path containment, not a
    # fuzzy string match.
    parts = dotted_import.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in module_to_file:
            referenced.add(module_to_file[candidate])


@dataclass
class DuplicateFunctionGroup:
    locations: list[str] = field(default_factory=list)


_MIN_DUPLICATE_STATEMENTS = 3  # skip trivial 1-2 line stubs — real noise, not a finding


def find_duplicate_functions(directory: str) -> list[DuplicateFunctionGroup] | None:
    """Real structural clone detection: functions/methods whose AST body
    is identical once names/literals are normalized away — catches a
    copy-pasted-and-renamed function, not just an identical-name
    definition (which _find_dead_code's dict already silently masks
    rather than surfaces as a finding)."""
    root = Path(directory)
    if not root.exists():
        return None
    py_files = _iter_py_files(root)
    if not py_files:
        return None

    groups: dict[str, list[str]] = defaultdict(list)
    for fp in py_files:
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"), filename=str(fp))
        except SyntaxError:
            continue
        rel = fp.relative_to(root)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if len(node.body) < _MIN_DUPLICATE_STATEMENTS:
                continue
            signature = _normalized_body_signature(node)
            groups[signature].append(f"{rel}:{node.lineno} ({node.name})")

    return [
        DuplicateFunctionGroup(locations=sorted(locs))
        for locs in groups.values()
        if len(locs) > 1
    ]


class _Normalizer(ast.NodeTransformer):
    """Strips names/literals/docstrings so two structurally-identical
    bodies compare equal even when variables were renamed — a real clone
    check, not requiring byte-for-byte identical source."""

    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = "_"
        node.annotation = None
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.copy_location(ast.Constant(value="_"), node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "_"
        node.decorator_list = []
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "_"
        node.decorator_list = []
        self.generic_visit(node)
        return node


def _normalized_body_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    import copy

    clone = copy.deepcopy(node)
    normalized = _Normalizer().visit(clone)
    return ast.dump(normalized, annotate_fields=False)
