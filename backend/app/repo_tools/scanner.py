"""Repository scanner — walks repo, parses files with tree-sitter, extracts symbols and imports."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs

_PY_LANG = Language(tspython.language())
_JS_LANG = Language(tsjs.language())

_LANG_MAP: dict[str, Language] = {
    ".py": _PY_LANG,
    ".js": _JS_LANG,
    ".ts": _JS_LANG,
    ".tsx": _JS_LANG,
    ".jsx": _JS_LANG,
}

_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    "TX",
    ".pytest_cache",
    "migrations",
}

_IGNORE_PATTERNS = ["*.min.js", "*.map", "*.lock", "pnpm-lock.yaml"]


@dataclass
class SymbolInfo:
    name: str
    kind: str  # function | class | method
    line_start: int
    line_end: int
    # Base-class names for kind="class" symbols (Phase 6.4) — bare identifier
    # or the last dotted component (e.g. "Base" from "pkg.Base", matching how
    # cross_file_graph.py already resolves method calls by bare name).
    # Always empty for function/method symbols.
    bases: list[str] = field(default_factory=list)


@dataclass
class FileIndex:
    path: str  # relative to repo root
    language: str
    content_hash: str
    symbols: list[SymbolInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # imported module paths


@dataclass
class RepoIndex:
    repo_path: str
    files: dict[str, FileIndex] = field(default_factory=dict)


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _extract_base_class_names(node: Node) -> list[str]:
    """class_definition's `superclasses` field is an argument_list —
    identifier children are plain base names, attribute children are dotted
    (e.g. `pkg.Base`, reduced to `Base` — the same bare-name convention
    cross_file_graph.py already uses for method calls); keyword_argument
    children (e.g. `metaclass=Meta`) are never base classes and are skipped.
    """
    superclasses = node.child_by_field_name("superclasses")
    if superclasses is None:
        return []
    bases: list[str] = []
    for child in superclasses.children:
        if child.type == "identifier" and child.text:
            bases.append(child.text.decode())
        elif child.type == "attribute":
            attr_node = child.child_by_field_name("attribute")
            if attr_node and attr_node.text:
                bases.append(attr_node.text.decode())
    return bases


def _extract_python_symbols(root: Node) -> list[SymbolInfo]:
    symbols: list[SymbolInfo] = []

    def walk(node: Node, class_name: str | None = None) -> None:
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode() if name_node.text else "?"
                symbols.append(
                    SymbolInfo(
                        name=name,
                        kind="class",
                        line_start=node.start_point[0],
                        line_end=node.end_point[0],
                        bases=_extract_base_class_names(node),
                    )
                )
                for child in node.children:
                    walk(child, class_name=name)
            return
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode() if name_node.text else "?"
                kind = "method" if class_name else "function"
                symbols.append(
                    SymbolInfo(
                        name=name,
                        kind=kind,
                        line_start=node.start_point[0],
                        line_end=node.end_point[0],
                    )
                )
            return
        for child in node.children:
            walk(child, class_name)

    walk(root)
    return symbols


def _extract_python_imports(root: Node, content: bytes) -> list[str]:
    imports: list[str] = []
    for node in root.children:
        if node.type in ("import_statement", "import_from_statement"):
            imports.append(
                content[node.start_byte : node.end_byte].decode(errors="replace")
            )
    return imports


def _extract_js_symbols(root: Node) -> list[SymbolInfo]:
    symbols: list[SymbolInfo] = []

    def walk(node: Node) -> None:
        if node.type in ("function_declaration", "function"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode() if name_node.text else "?"
                symbols.append(
                    SymbolInfo(
                        name=name,
                        kind="function",
                        line_start=node.start_point[0],
                        line_end=node.end_point[0],
                    )
                )
        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode() if name_node.text else "?"
                symbols.append(
                    SymbolInfo(
                        name=name,
                        kind="class",
                        line_start=node.start_point[0],
                        line_end=node.end_point[0],
                    )
                )
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _parse_file(
    path: Path, lang: Language, ext: str
) -> tuple[list[SymbolInfo], list[str]]:
    content = path.read_bytes()
    parser = Parser(lang)
    tree = parser.parse(content)

    if ext == ".py":
        symbols = _extract_python_symbols(tree.root_node)
        imports = _extract_python_imports(tree.root_node, content)
    else:
        symbols = _extract_js_symbols(tree.root_node)
        imports = []
    return symbols, imports


def parse_single_file(path: Path) -> tuple[list[SymbolInfo], list[str]] | None:
    """Gap-closure Days 45-47 (Stage 2) — public entry point for callers
    (app/repo_tools/file_folding.py) that need one arbitrary file's real
    symbols without running a full repository scan. Returns None for a
    tree-sitter-unsupported extension or any parse failure — never raises,
    matching this module's own index_repository() per-file error handling."""
    ext = path.suffix.lower()
    lang = _LANG_MAP.get(ext)
    if lang is None:
        return None
    try:
        return _parse_file(path, lang, ext)
    except Exception:
        return None


def index_repository(
    repo_path: str,
    known_hashes: dict[str, str] | None = None,
) -> RepoIndex:
    """
    Walk repo_path, parse supported files, return RepoIndex.

    known_hashes: optional {rel_path: content_hash} from a previous index run.
    Files whose hash hasn't changed are skipped (incremental re-index).
    Returns a full RepoIndex merging unchanged entries with newly parsed ones.
    """
    from app.config import get_settings

    max_bytes = get_settings().scanner_max_indexable_file_bytes

    base = Path(repo_path)
    index = RepoIndex(repo_path=repo_path)

    for root, dirs, files in os.walk(base):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]

        for fname in files:
            if any(fnmatch.fnmatch(fname, p) for p in _IGNORE_PATTERNS):
                continue
            ext = Path(fname).suffix.lower()
            lang = _LANG_MAP.get(ext)
            if lang is None:
                continue

            abs_path = Path(root) / fname
            rel_path = str(abs_path.relative_to(base))

            # Blocker (audit_v1.md 4.2 #3 / 4.8 #12): a cheap os.stat() size
            # check BEFORE ever reading file bytes — the previous code read
            # full file contents for every file on every walk (even an
            # "incremental" reindex only skipped the parse afterward, not
            # this read), with no size cap at all.
            try:
                if abs_path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue

            try:
                content = abs_path.read_bytes()
                chash = _content_hash(content)
            except Exception:
                continue

            # Incremental: skip re-parsing if hash matches previous index
            if known_hashes and known_hashes.get(rel_path) == chash:
                continue

            try:
                symbols, imports = _parse_file(abs_path, lang, ext)
            except Exception:
                continue

            index.files[rel_path] = FileIndex(
                path=rel_path,
                language=ext.lstrip("."),
                content_hash=chash,
                symbols=symbols,
                imports=imports,
            )

    return index


def merge_indexes(base_index: RepoIndex, new_index: RepoIndex) -> RepoIndex:
    """
    Merge a partial new_index (only changed files) into base_index.
    Returns a new RepoIndex with all files from base_index updated by new_index.
    """
    merged = RepoIndex(repo_path=base_index.repo_path, files=dict(base_index.files))
    merged.files.update(new_index.files)
    return merged


def build_call_graph(index: RepoIndex) -> dict[str, list[str]]:
    """
    Build a simple import-based call graph.
    Returns {caller_file: [callee_file, ...]} based on import statements.
    """
    # Map symbol names to file paths
    symbol_to_file: dict[str, str] = {}
    for rel_path, fi in index.files.items():
        for sym in fi.symbols:
            symbol_to_file[sym.name] = rel_path

    edges: dict[str, list[str]] = {}
    for rel_path, fi in index.files.items():
        callees: list[str] = []
        for import_line in fi.imports:
            # Match "from .module import X" or "import X"
            for other_path, other_fi in index.files.items():
                if other_path == rel_path:
                    continue
                stem = Path(other_path).stem
                if stem in import_line:
                    callees.append(other_path)
                    break
        if callees:
            edges[rel_path] = callees

    return edges


@dataclass
class PackageEdge:
    caller_package: str  # directory containing the importing file ("." for repo root)
    callee_package: str
    weight: int  # number of file-level import edges aggregated into this edge


def _package_of(rel_path: str) -> str:
    parent = str(Path(rel_path).parent)
    return "." if parent == "." else parent.replace("\\", "/")


def build_package_graph(import_edges: dict[str, list[str]]) -> list[PackageEdge]:
    """Aggregate scanner.build_call_graph()'s existing file-level import
    edges up to directory/package granularity (Phase 6.4) — a pure
    aggregation over already-collected data, no new AST walking. Same-
    package edges are dropped: this is a *cross*-package dependency graph."""
    counts: dict[tuple[str, str], int] = {}
    for caller_file, callees in import_edges.items():
        caller_pkg = _package_of(caller_file)
        for callee_file in callees:
            callee_pkg = _package_of(callee_file)
            if caller_pkg == callee_pkg:
                continue
            key = (caller_pkg, callee_pkg)
            counts[key] = counts.get(key, 0) + 1
    return [
        PackageEdge(caller_package=c, callee_package=e, weight=w)
        for (c, e), w in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
