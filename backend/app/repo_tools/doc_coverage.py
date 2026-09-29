"""#457 (2026-09-25, "Documentation checks (mandatory pre-completion
gate)") — the audit's own IMPLEMENTATION PLAN is explicit that this must
NOT be the existing full repo-wide docs.py agent (an LLM-driven epic-level
README/changelog writer — too slow/expensive to run per subtask): "Build a
new, smaller, scoped-diff doc-check ... that only validates whether docs
exist/are updated for the specific files touched by that subtask's diff."

Purely AST-based (no LLM call), matching code_hygiene.py/reliability_review.py's
own established "free, deterministic gate" shape for this pipeline: checks
only the files a subtask's own diff actually touched, for top-level PUBLIC
(non-underscore-prefixed) functions/classes missing a docstring. Private
helpers, nested/local functions, and non-Python files are deliberately out
of scope — the same "a private git checkout" cousin-limitation this
codebase already accepts elsewhere (see reliability_review.py's own
nested-function boundary) rather than a fragile heuristic guessing at
whether a symbol is "public API".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocCoverageReport:
    undocumented: list[str] = field(default_factory=list)

    @property
    def undocumented_count(self) -> int:
        return len(self.undocumented)


def check_subtask_doc_coverage(
    worktree_path: str, changed_files: list[str]
) -> DocCoverageReport:
    """Scan only `changed_files` (a subtask's own diff, worktree-relative
    paths) for top-level public functions/classes with no docstring.

    Never raises — an unreadable or unparseable file is silently skipped
    (same convention as code_hygiene.py's own broken-import scan), since a
    file this subtask didn't actually finish writing yet is not this gate's
    concern.
    """
    report = DocCoverageReport()
    root = Path(worktree_path)
    for rel_path in changed_files:
        if not rel_path.endswith(".py"):
            continue
        full_path = root / rel_path
        try:
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel_path)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.iter_child_nodes(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            if node.name.startswith("_"):
                continue
            if ast.get_docstring(node) is None:
                report.undocumented.append(f"{rel_path}:{node.lineno}:{node.name}")
    return report
