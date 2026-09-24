"""Reliability detector — T2-B9 (2026-09-24, GRIDIRON_PARTIAL #149
"Reliability Engineering / Maintainability (beyond lint gates)").

Stdlib only, matching app.repo_tools.ast_engine/code_hygiene's own "zero
extra dependencies" convention — a sibling module, not a replacement.

Scope, deliberately narrow (matching this codebase's own established
"don't fabricate a fragile heuristic" discipline — see #297's own
IMPLEMENTATION PLAN for the precedent this follows): flags a real,
low-false-positive class of finding — a call to a recognized external-I/O
operation (HTTP, subprocess, a raw DB `.execute()`, the Anthropic client)
with NO enclosing `try`/`except` anywhere in its own function body. This
is exactly "missing error handling around external calls" from the audit
item's own wording.

"Missing retry/circuit-breaker coverage" (the item's OTHER half) is
deliberately NOT built as a second detector here: a real retry/circuit-
breaker guarantee can live one or more call-frames above the call site
(an outer decorator, a queue-level retry, this codebase's own
`app.fleet.circuit_breaker`), which a single-function AST scan cannot see
— a naive "no retry loop in this function = missing retry" check would
be exactly the class of unreliable, non-regex-backed heuristic this
codebase's own precedent (#297) explicitly declines to ship. If a
concrete, checkable retry/circuit-breaker convention is ever formalized
(e.g. "every module-level `_call_*` wrapper for an external service must
be registered with a named circuit breaker"), that would be a real,
addable second detector — not fabricated here.

Real, honest limitations (stated up front, same posture as code_hygiene.py):
  - Call recognition is by dotted-name TAIL match (e.g. `self.session.get`
    matches the `session.get` pattern) — a real, deliberate choice so this
    doesn't need real type inference to catch `requests.get` called
    through an aliased or attribute-wrapped reference, at the cost of a
    real, small false-positive risk for an unrelated `.get(...)` method
    that happens to share a tail name with a flagged pattern (e.g. a
    plain dict's `.get()`) — mitigated by requiring at least a 2-segment
    dotted tail match (`requests.get`, not bare `get`), never a 1-segment
    bare name.
  - A `try` guarding the call via a DIFFERENT function one or more frames
    up the call stack (the call site itself has no local try, but every
    real caller wraps it) is invisible to a per-function static scan —
    same class of limitation as `code_hygiene.py`'s own broken-import
    detector explicitly documents for its own reach.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

_EXCLUDED_DIR_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules"}

# Dotted-name TAILS considered a real external-I/O operation. A call
# matches if its own full dotted chain ends with one of these (see
# _matches_external's own 2-segment-minimum rule).
_EXTERNAL_CALL_PATTERNS = (
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "requests.patch",
    "requests.request",
    "httpx.get",
    "httpx.post",
    "httpx.put",
    "httpx.delete",
    "httpx.request",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "urllib.request.urlopen",
    "request.urlopen",
    "messages.create",  # anthropic client.messages.create
    "session.execute",  # raw SQLAlchemy execute — a real DB round trip
    "db.execute",
)


@dataclass
class UnguardedCallFinding:
    file: str
    function: str
    line: int
    call: str  # the matched pattern, e.g. "requests.get"


@dataclass
class ReliabilityReport:
    findings: list[UnguardedCallFinding] = field(default_factory=list)
    files_scanned: int = 0


def _call_dotted_name(node: ast.Call) -> str | None:
    """Reconstructs the dotted attribute chain of a call's callee, e.g.
    `self.session.get(...)` -> "self.session.get". Returns None for a
    call whose callee isn't a plain Name/Attribute chain (a subscript, a
    call result, a lambda, etc. — nothing this detector can meaningfully
    name)."""
    parts: list[str] = []
    func: ast.expr = node.func
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    elif parts:
        # An attribute chain rooted in something other than a bare name
        # (e.g. `foo().get(...)`) — still nameable via its attribute
        # tail, which is all _matches_external needs.
        pass
    else:
        return None
    parts.reverse()
    return ".".join(parts)


def _matches_external(dotted: str) -> str | None:
    segments = dotted.split(".")
    for pattern in _EXTERNAL_CALL_PATTERNS:
        pattern_segments = pattern.split(".")
        if len(segments) >= len(pattern_segments) and segments[-len(pattern_segments):] == pattern_segments:
            return pattern
    return None


def _direct_children_no_nested_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Yields every descendant of `node`, EXCLUDING anything inside a
    nested function/lambda definition — each function's own error
    handling is evaluated independently, so a call inside a nested def
    must not be attributed to (or considered guarded by a try in) its
    enclosing function."""
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from _direct_children_no_nested_scope(child)


def _protected_node_ids(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """Every node id that lives inside the PROTECTED body of some `try`
    within `func` (the `try:` block itself — NOT its except/else/finally
    clauses, which run only after the try body has already exited)."""
    protected: set[int] = set()
    for node in _direct_children_no_nested_scope(func):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                protected.add(id(stmt))
                for sub in _direct_children_no_nested_scope(stmt):
                    protected.add(id(sub))
    return protected


def _iter_functions(
    tree: ast.AST,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def find_unguarded_external_calls(directory: str) -> ReliabilityReport:
    """Real computation: scans every real .py file under `directory` for
    a call to a recognized external-I/O operation with no enclosing
    `try` anywhere in its own function. Never a fabricated finding — a
    guarded call (even via a broad `except Exception:`) is never
    flagged, matching this codebase's own "a caught exception is a
    handled exception" convention elsewhere (e.g. code_hygiene.py's
    optional-import guard detection)."""
    report = ReliabilityReport()
    d = Path(directory)
    if not d.exists():
        return report

    for fp in d.rglob("*.py"):
        if any(part in _EXCLUDED_DIR_PARTS for part in fp.parts):
            continue
        try:
            source = fp.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(fp))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        report.files_scanned += 1
        rel = fp.relative_to(d).as_posix()

        for func in _iter_functions(tree):
            protected_ids = _protected_node_ids(func)
            for node in _direct_children_no_nested_scope(func):
                if not isinstance(node, ast.Call):
                    continue
                dotted = _call_dotted_name(node)
                if dotted is None:
                    continue
                matched = _matches_external(dotted)
                if matched and id(node) not in protected_ids:
                    report.findings.append(
                        UnguardedCallFinding(
                            file=rel,
                            function=func.name,
                            line=node.lineno,
                            call=matched,
                        )
                    )

    return report


def format_reliability_report(report: ReliabilityReport) -> str:
    if not report.findings:
        return f"✅ No unguarded external calls found ({report.files_scanned} file(s) scanned)."
    lines = [
        f"⚠️  {len(report.findings)} unguarded external call(s) across "
        f"{report.files_scanned} file(s) scanned:"
    ]
    for f in report.findings[:50]:
        lines.append(f"  {f.file}:{f.line}  {f.function}()  ->  {f.call}(...)")
    if len(report.findings) > 50:
        lines.append(f"  ... and {len(report.findings) - 50} more")
    return "\n".join(lines)
