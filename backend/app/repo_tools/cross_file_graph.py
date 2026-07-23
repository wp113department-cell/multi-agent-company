"""Cross-file, function-level call graph — REPO-FIRST pattern from aider's
repomap.py (repos/aider/aider/repomap.py): resolve cross-file edges by
NAME MATCHING (which files define a symbol vs. which files/functions
reference it) into a networkx.MultiDiGraph, then rank files with a
personalized PageRank.

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): scanner.py's
build_call_graph() is a file-level IMPORT graph mislabeled as a call graph;
ast_engine.py's build_call_graph() is a real function-level call graph but
single-file only. This module reuses scanner.py's existing per-file
RepoIndex/SymbolInfo (definitions) as the base structure (not reinvented),
adds a per-file, per-function call-reference extraction pass (the same
ast.Call-walking technique already proven in ast_engine.py's
_collect_calls()), then layers aider's exact cross-file linking + PageRank
technique on top to resolve and rank the cross-file edges.

Scoped to Python files only (stdlib `ast`, matching ast_engine.py's existing
scope) — scanner.py's tree-sitter JS/TS symbol extraction has no equivalent
reference/call extraction pass in this codebase yet; JS/TS files still
appear in the RepoIndex.files defines but contribute no reference edges.

Differences from aider's repomap.py (deliberate simplifications — see
files/GAPS_ALL_FILES_REPORT.md's implementation plan for the full reasoning):
- No "explicitly mentioned in chat" boost — there's no chat context here;
  `personalization` is still accepted for callers that have one (e.g. a
  future context-builder integration seeding rank toward task-relevant
  files), defaulting to uniform (plain PageRank) otherwise.
- Ranks files (dict[path, score]), not aider's finer (file, definition)
  redistribution — this batch's real deliverables (persisted CallEdge rows,
  a ranked file list for the Architecture Mapper) don't need per-definition
  granularity; adding it would be complexity without a current consumer.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from app.repo_tools.scanner import RepoIndex

logger = logging.getLogger(__name__)

_MODULE_LEVEL_CALLER = "<module>"

# aider's own multipliers (repomap.py) for edge weight, adapted: no
# explicit-mention boost (no chat context available here).
_REAL_NAME_MIN_LEN = 8
_AMBIGUOUS_NAME_FILE_THRESHOLD = 5
_REAL_NAME_MULTIPLIER = 10.0
_PRIVATE_NAME_MULTIPLIER = 0.1
_AMBIGUOUS_NAME_MULTIPLIER = 0.1


def _looks_like_a_real_name(ident: str) -> bool:
    """aider's heuristic for deprioritizing short/generic identifiers (x, run,
    get) in favor of specific, meaningful ones — snake_case/camelCase and
    reasonably long, not just any identifier."""
    if len(ident) >= _REAL_NAME_MIN_LEN:
        return True
    has_underscore = "_" in ident.strip("_")
    has_mixed_case = ident != ident.lower() and ident != ident.upper()
    return has_underscore or has_mixed_case


@dataclass
class CrossFileCallEdge:
    caller_file: str
    caller_symbol: str  # function/method name, or "<module>" for module-level calls
    callee_file: str
    callee_symbol: str


@dataclass
class CrossFileGraphResult:
    call_edges: list[CrossFileCallEdge] = field(default_factory=list)
    file_rank: dict[str, float] = field(default_factory=dict)


def _extract_calls_by_function(abs_path: Path) -> dict[str, set[str]]:
    """{function_name: {called_identifier, ...}} for one .py file. Calls made
    outside any function body are attributed to _MODULE_LEVEL_CALLER. Method
    calls (obj.method()) are recorded by bare method name only — matching
    how symbols are defined/looked-up elsewhere in this module (and in
    ast_engine.py's equivalent single-file tool) — this trades perfect
    precision (no receiver-type resolution) for a simple, real, working
    cross-file signal, consistent with aider's own name-matching approach."""

    def _collect_calls(node: ast.AST) -> set[str]:
        found: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    found.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    found.add(child.func.attr)
        return found

    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(abs_path))
    except (SyntaxError, OSError):
        return {}

    result: dict[str, set[str]] = {}
    module_level_calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = _collect_calls(node)

    # Module-level calls: everything NOT inside a function/class body.
    class _ModuleCallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            pass  # don't descend — already handled above

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            pass

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                module_level_calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                module_level_calls.add(node.func.attr)
            self.generic_visit(node)

    _ModuleCallVisitor().visit(tree)
    if module_level_calls:
        result[_MODULE_LEVEL_CALLER] = module_level_calls
    return result


def build_cross_file_graph(
    index: RepoIndex,
    personalization: dict[str, float] | None = None,
) -> CrossFileGraphResult:
    """Resolve cross-file call edges by identifier-name matching, and rank
    every indexed file by (personalized) PageRank over those edges."""
    base = Path(index.repo_path)

    # ---- defines: symbol name -> set of files that define it ----
    defines: dict[str, set[str]] = {}
    for rel_path, fi in index.files.items():
        for sym in fi.symbols:
            defines.setdefault(sym.name, set()).add(rel_path)

    # ---- references: called identifier -> [(file, calling_function), ...] ----
    references: dict[str, list[tuple[str, str]]] = {}
    for rel_path, fi in index.files.items():
        if fi.language != "py":
            continue
        calls_by_fn = _extract_calls_by_function(base / rel_path)
        for caller_symbol, called_idents in calls_by_fn.items():
            for ident in called_idents:
                references.setdefault(ident, []).append((rel_path, caller_symbol))

    # ---- resolve cross-file edges + build the file-level ranking graph ----
    call_edges: list[CrossFileCallEdge] = []
    graph = nx.MultiDiGraph()
    for rel_path in index.files:
        graph.add_node(rel_path)  # every indexed file gets ranked, even isolated ones

    for ident, refs in references.items():
        defining_files = defines.get(ident)
        if not defining_files:
            continue  # referenced but not defined anywhere we indexed (stdlib/3rd-party)

        mul = 1.0
        if _looks_like_a_real_name(ident):
            mul *= _REAL_NAME_MULTIPLIER
        if ident.startswith("_"):
            mul *= _PRIVATE_NAME_MULTIPLIER
        if len(defining_files) > _AMBIGUOUS_NAME_FILE_THRESHOLD:
            mul *= _AMBIGUOUS_NAME_MULTIPLIER

        for ref_file, ref_symbol in refs:
            for def_file in defining_files:
                if ref_file == def_file:
                    continue  # same-file calls aren't cross-file edges
                call_edges.append(
                    CrossFileCallEdge(
                        caller_file=ref_file,
                        caller_symbol=ref_symbol,
                        callee_file=def_file,
                        callee_symbol=ident,
                    )
                )
                graph.add_edge(ref_file, def_file, weight=mul, ident=ident)

    if graph.number_of_edges() == 0:
        # nx.pagerank requires at least one edge to converge meaningfully;
        # with none, every file is equally (un)ranked.
        n = graph.number_of_nodes() or 1
        return CrossFileGraphResult(
            call_edges=call_edges,
            file_rank={node: 1.0 / n for node in graph.nodes},
        )

    try:
        file_rank: dict[str, float] = nx.pagerank(
            graph,
            weight="weight",
            personalization=personalization,
            dangling=personalization,
        )
    except nx.PowerIterationFailedConvergence:
        logger.warning(
            "Cross-file graph PageRank did not converge — using uniform rank"
        )
        n = graph.number_of_nodes() or 1
        file_rank = {node: 1.0 / n for node in graph.nodes}

    return CrossFileGraphResult(call_edges=call_edges, file_rank=file_rank)
