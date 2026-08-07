"""AUDIT_Q_BATCH08 §66 "Transaction safety — PARTIAL": app/db/repository.py
relies entirely on SQLAlchemy's implicit autobegin plus a single
`await db.commit()` per handler, with no explicit `async with db.begin():`
transaction blocks anywhere. That convention is correct as long as every
handler follows it — the audit's own concrete complaint is that nothing
structurally enforces it, "so a future handler with two separate commit()
calls wouldn't be caught by anything."

This is that enforcement: a static AST check, not a runtime wrapper —
proportionate to the actual risk (every function in this file already
follows the convention correctly; the gap was a missing regression guard,
not a live bug) and zero runtime overhead. A future function that
accidentally commits twice within its own scope (splitting one logical
write into two implicitly-separate transactions, where a crash between them
would leave inconsistent state) now fails CI instead of shipping silently.

Deliberately scoped to app/db/repository.py — the module this finding named
— not every `.commit()` call in the codebase; app/api/*.py handlers that
call a single repository function per request already inherit that
function's own single-commit guarantee.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPOSITORY_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "db" / "repository.py"
)


def _direct_commit_call_count(func: ast.AsyncFunctionDef | ast.FunctionDef) -> int:
    """Counts `.commit()` calls directly within this function's own body —
    deliberately NOT descending into a nested function definition (this
    file's sync-bridge functions each define their own inner `async def
    _run(): ...`, which is a separate transactional scope, checked
    independently as its own function node by the caller below)."""
    count = 0

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return  # nested def — separate scope, don't descend

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return  # nested def — separate scope, don't descend

        def visit_Call(self, node: ast.Call) -> None:
            nonlocal count
            if isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
                count += 1
            self.generic_visit(node)

    visitor = _Visitor()
    for stmt in func.body:
        visitor.visit(stmt)
    return count


def _all_function_defs(tree: ast.Module) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    """Every function definition at any nesting level (module-level async
    handlers, and the inner `async def _run()` closures the sync bridges
    define) — ast.walk() finds nested defs regardless of depth."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def test_no_repository_function_commits_more_than_once_in_its_own_scope() -> None:
    source = _REPOSITORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_REPOSITORY_PATH))

    offenders: list[str] = []
    for func in _all_function_defs(tree):
        commits = _direct_commit_call_count(func)
        if commits > 1:
            offenders.append(f"{func.name} (line {func.lineno}): {commits} commit() calls")

    assert not offenders, (
        "app/db/repository.py function(s) with more than one commit() call "
        "in their own scope — this violates the 'one handler = one "
        "transaction' convention every existing function follows (see "
        "AUDIT_Q_BATCH08 §66 'Transaction safety'). If this is genuinely "
        "intentional, wrap the whole function body in "
        "`async with db.begin():` instead of multiple bare commit() calls "
        "so the transaction boundary is explicit, not implicit:\n"
        + "\n".join(offenders)
    )


def test_repository_module_actually_has_functions_to_check() -> None:
    """Guards the guard: if repository.py's shape changes enough that the
    AST walk above finds zero functions, that's this test silently doing
    nothing rather than passing meaningfully."""
    source = _REPOSITORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_REPOSITORY_PATH))
    assert len(_all_function_defs(tree)) >= 20
