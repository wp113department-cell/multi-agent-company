"""Repository scanner — walks repo, parses files with tree-sitter, extracts symbols and imports."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
import threading
import time
from collections.abc import Iterator
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
    # Every indexable path index_repository() saw on disk during its walk,
    # whether it was (re)parsed or skipped as unchanged. merge_indexes() needs it
    # to tell "unchanged" from "deleted" — an incremental index only carries the
    # CHANGED files, so a deleted file simply never appeared and its stale entry
    # lived in the merged index forever. Empty for hand-built indexes (no pruning).
    seen_paths: set[str] = field(default_factory=set)


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


def rename_in_js_source(source: str, old_name: str, new_name: str) -> tuple[str, int]:
    """T2-B8 (2026-09-24, GRIDIRON_PARTIAL #259 "Repository-wide
    refactoring (AST-aware, all languages)") — the JS/TS counterpart to
    app/repo_tools/ast_engine.py::_rename_in_python_source, reusing the
    SAME real tree-sitter JS grammar (`_JS_LANG`) this module already
    parses TS/JS files with for symbol extraction (there's still no
    separate TypeScript grammar in use — `.ts`/`.tsx` are parsed with the
    JS grammar here exactly as _extract_js_symbols already does, so
    TS-specific syntax like type annotations is tolerated, not truly
    type-aware).

    Walks every real `identifier` node (not `property_identifier` —
    deliberately does NOT rename `obj.old_name`-style member/property
    access, only standalone identifier references: variable names,
    function/class names, parameters) whose text matches `old_name`,
    grouped by line, then replaces each matched span in reverse column
    order exactly like `_rename_in_python_source` does — an identifier
    never spans multiple lines in this grammar, so per-line grouping is
    exact, not an approximation.

    Same honest, documented limitation as the Python tokenize-based
    version: no scope analysis, so a same-named identifier in an unrelated
    scope (a different function's own local variable, e.g.) is renamed
    too — this is a text-level, AST-shape-aware rename (skips string/
    comment content, which pure regex cannot), not a semantically scoped
    one. Raises nothing: a source tree-sitter still recovers a partial
    parse from (its error-recovery grammar rarely raises outright) is
    walked as-is; a completely unparseable input just yields zero
    `identifier` matches, returned as (source, 0) — tree-sitter's own
    error-recovery grammar means there is no SyntaxError-style exception
    for rename_symbol()'s caller to catch here by design; a source this
    can't meaningfully parse just yields a real, honest 0-count result
    rather than a fallback to plain regex."""
    parser = Parser(_JS_LANG)
    tree = parser.parse(source.encode("utf-8"))

    by_line: dict[int, list[tuple[int, int]]] = {}
    count = 0

    def walk(node: Node) -> None:
        nonlocal count
        if node.type == "identifier" and node.text and node.text.decode() == old_name:
            row = node.start_point[0]
            by_line.setdefault(row, []).append((node.start_point[1], node.end_point[1]))
            count += 1
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    if not count:
        return source, 0

    from app.tools.filesystem._textio import split_keepends_lf

    lines = split_keepends_lf(source)
    for row, spans in by_line.items():
        line = lines[row]
        for col_start, col_end in sorted(spans, reverse=True):
            line = line[:col_start] + new_name + line[col_end:]
        lines[row] = line
    return "".join(lines), count


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


def _git_visible_files(base: Path) -> list[str] | None:
    """Files git would consider part of the project: tracked plus untracked
    but NOT ignored (`git ls-files --cached --others --exclude-standard`).
    None when `base` is not a git work tree (or git fails) — callers then
    fall back to the plain directory walk.

    Production audit 2026-09-29 (PERF): the plain walk ignored .gitignore, so
    a workspace holding cloned repos under repos/ was indexed as 14,631 files
    instead of its 1,842 tracked ones — ~75 s on every agent run, because
    base_graph's memory_hook_node indexes the target repo per run."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=base,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [p for p in result.stdout.decode("utf-8", "replace").split("\0") if p]


def _candidate_files(base: Path) -> Iterator[Path]:
    """Every file index_repository should consider, honouring _IGNORE_DIRS in
    both modes (git-visible listing when available, else os.walk)."""
    visible = _git_visible_files(base)
    if visible is not None:
        for rel in visible:
            if any(part in _IGNORE_DIRS for part in Path(rel).parts[:-1]):
                continue
            path = base / rel
            if path.is_file():
                yield path
        return
    for root, dirs, files in os.walk(base):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for fname in files:
            yield Path(root) / fname


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

    for abs_path in _candidate_files(base):
        fname = abs_path.name
        if any(fnmatch.fnmatch(fname, p) for p in _IGNORE_PATTERNS):
            continue
        ext = Path(fname).suffix.lower()
        lang = _LANG_MAP.get(ext)
        if lang is None:
            continue

        rel_path = str(abs_path.relative_to(base))
        index.seen_paths.add(rel_path)

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
    if new_index.seen_paths:
        # Files that were indexed before but are no longer on disk: drop them
        # (proved live: a deleted file stayed in the merged index forever, so
        # symbol search / call graph / context kept pointing at phantom files).
        for gone in [p for p in merged.files if p not in new_index.seen_paths]:
            del merged.files[gone]
        merged.seen_paths = set(new_index.seen_paths)
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


# ---------------------------------------------------------------------------
# Warm repo-index cache (2026-09-29). base_graph's memory_hook_node indexes the
# target repo at the start of EVERY agent run just to add a short "relevant
# files" hint; that is ~2.8 s of parsing per run for an unchanged repo. The
# cache key is the repo's git state (HEAD + a hash of `git status`), so any
# commit or edit rebuilds it; non-git directories expire after 60 s.
# ---------------------------------------------------------------------------

_INDEX_CACHE: dict[str, tuple[str, float, RepoIndex]] = {}
_INDEX_CACHE_LOCK = threading.Lock()
_NON_GIT_TTL_SECONDS = 60.0


def _git_state_key(base: Path) -> str | None:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base, capture_output=True, timeout=10
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=base,
            capture_output=True,
            timeout=30,
        )
        digest = hashlib.sha256(status.stdout).hexdigest()[:16]
        return f"{head.stdout.decode().strip()}:{digest}"
    except (OSError, subprocess.SubprocessError):
        return None


def index_repository_cached(repo_path: str) -> RepoIndex:
    """index_repository(), reused while the repo's git state is unchanged."""
    base = Path(repo_path)
    key = _git_state_key(base)
    now = time.monotonic()
    with _INDEX_CACHE_LOCK:
        hit = _INDEX_CACHE.get(repo_path)
    if hit is not None:
        hit_key, stamp, idx = hit
        if key is not None and hit_key == key:
            return idx
        if key is None and now - stamp < _NON_GIT_TTL_SECONDS:
            return idx
    idx = index_repository(repo_path)
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[repo_path] = (key or "", now, idx)
    return idx
