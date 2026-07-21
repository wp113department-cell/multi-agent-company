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
