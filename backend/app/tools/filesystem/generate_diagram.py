"""generate_diagram tool — tool_enhance.md productionization pass,
tool #146 (2026-09-14).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: generate_diagram
Old path: app/agents/tools.py (`_GENERATE_DIAGRAM_TOOL` schema dict,
    `generate_diagram_h` + its private helpers `_real_class_diagram` /
    `_real_call_flowchart` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/generate_diagram.py (this file) —
    `GENERATE_DIAGRAM_TOOL`, `generate_diagram_handler`. The AST-derivation
    helpers moved here too, now operating on an already-validated path.
Affected agents: per tool_inventory.json, agents declaring
    `generate_diagram` in `allowed_tools` (plus interactive chat,
    newly — see finding #2).
Affected modules: app/agents/tools.py (`generate_diagram_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "generate_diagram" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_generate_diagram_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/generate_diagram.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a genuine CLASS/METHOD/FUNCTION-NAME
   disclosure oracle.** `_real_class_diagram`/`_real_call_flowchart`
   built `root / file_path` without ever validating it stayed inside
   the worktree — the same `pathlib`-silently-discards-`root`-for-an-
   absolute-right-operand class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144
   this initiative. Proved live: `generate_diagram({"description": "x",
   "kind": "classDiagram", "path": "/tmp/<outside file>"})` genuinely
   disclosed a real class's name AND its method names from a file
   entirely outside the intended worktree; the `kind="flowchart"` mode
   likewise disclosed real function names and call edges from the same
   outside file — a real structure-disclosure primitive, even though
   it is not full raw file content.

2. **Advertised but never dispatched on the interactive chat agent,
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144.**
   `generate_diagram` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
   `_execute_tool()` had no dispatch branch — every real
   interactive-chat call fell through to `"[ERROR] Unknown tool:
   generate_diagram"`.

Fixed via a shared `generate_diagram_handler()`: when `path` is given,
it is validated with `check_path_in_worktree()` before either AST
helper ever touches the filesystem, closing finding #1 — an
out-of-worktree path now returns `[POLICY DENIED] ...` instead of a
real diagram derived from outside code. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #2.

When no `path` is given (or the derivation legitimately finds nothing,
e.g. no classes/functions), behavior is unchanged: the existing
labeled starter template is returned, exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.policy.engine import check_path_in_worktree

GENERATE_DIAGRAM_TOOL: dict[str, Any] = {
    "name": "generate_diagram",
    "description": (
        "Generate a Mermaid diagram. For kind='classDiagram' or 'flowchart', pass "
        "`path` (a real .py file relative to repo root) to get a diagram built from "
        "that file's actual classes/bases (classDiagram) or function call edges "
        "(flowchart) via AST analysis — not a placeholder. Without `path` (or for "
        "kind='sequence'/'erDiagram', which aren't derivable from static analysis "
        "alone), returns a labeled starter template instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "What to diagram — components, flow, or relationships",
            },
            "kind": {
                "type": "string",
                "enum": ["flowchart", "sequence", "erDiagram", "classDiagram"],
                "description": "Diagram type (default: flowchart)",
            },
            "path": {
                "type": "string",
                "description": (
                    "Real .py file (relative to repo root) to derive the diagram "
                    "from via AST analysis. Only used by classDiagram/flowchart."
                ),
            },
        },
        "required": ["description"],
    },
}


def _real_class_diagram(root: Path, file_path: str) -> str | None:
    """AUDIT_Q_BATCH14 §99 gap-closure — real classes/bases from
    parse_file_ast (app/repo_tools/ast_engine.py), not a fake
    MyClass/method() skeleton. Returns None (never a guess) when the
    file can't be parsed or declares no classes, so the caller falls
    back to the labeled template instead of fabricating content."""
    from app.repo_tools.ast_engine import parse_file_ast

    raw = parse_file_ast(str(root / file_path))
    if raw.startswith("[ERROR]"):
        return None
    classes = json.loads(raw).get("classes", [])
    if not classes:
        return None

    lines = ["classDiagram"]
    for cls in classes:
        name = cls["name"]
        for method in cls["methods"][:15]:
            lines.append(f"    {name} : +{method}()")
        for base in cls["bases"]:
            # Mermaid inheritance arrow: subclass --|> superclass.
            # ast.unparse() can return a dotted expr (e.g. "abc.ABC") —
            # Mermaid class names can't contain '.', so the last
            # component is used, matching build_class_graph's own
            # identifier-name-matching convention (cross_file_graph.py).
            base_name = base.rsplit(".", 1)[-1]
            lines.append(f"    {base_name} <|-- {name}")
    return "\n".join(lines)


def _real_call_flowchart(root: Path, file_path: str, description: str) -> str | None:
    """AUDIT_Q_BATCH14 §99 gap-closure — real function call edges from
    get_call_edges (app/repo_tools/ast_engine.py), not a fake
    Start/Process/Decision/End skeleton. Returns None when the file has
    no functions or can't be parsed."""
    from app.repo_tools.ast_engine import get_call_edges

    edges = get_call_edges(str(root / file_path))
    if isinstance(edges, str) or not edges:
        return None

    known_functions = {e["caller"] for e in edges}
    lines = [f"flowchart TD\n    %% {description}"]
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        caller = edge["caller"]
        # Only draw edges to functions actually defined in this same
        # file — an edge to an unknown external call would be a real
        # name but a misleading, unverifiable diagram node.
        for callee in edge["calls"]:
            target = callee.rsplit(".", 1)[-1]
            if target in known_functions and (caller, target) not in seen_edges:
                lines.append(f"    {caller} --> {target}")
                seen_edges.add((caller, target))
    if len(lines) == 1:
        return None
    return "\n".join(lines)


def generate_diagram_handler(
    root: Path, worktree_path: str, inp: dict[str, Any]
) -> str:
    """Core generate_diagram logic — the one real implementation,
    reused unchanged in behavior except for the worktree-boundary
    check now applied to `path` before either AST helper runs."""
    description = str(inp["description"])
    kind = str(inp.get("kind", "flowchart"))
    path_in = inp.get("path")

    if path_in:
        policy = check_path_in_worktree(str(path_in), worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"

        real: str | None = None
        if kind == "classDiagram":
            real = _real_class_diagram(root, str(path_in))
        elif kind == "flowchart":
            real = _real_call_flowchart(root, str(path_in), description)
        if real is not None:
            return f"```mermaid\n{real}\n```"

    templates = {
        "flowchart": f"flowchart TD\n    %% {description}\n    A[Start] --> B[Process]\n    B --> C{{Decision}}\n    C -->|Yes| D[End]\n    C -->|No| B",
        "sequence": f"sequenceDiagram\n    %% {description}\n    participant A\n    participant B\n    A->>B: Request\n    B-->>A: Response",
        "erDiagram": f"erDiagram\n    %% {description}\n    ENTITY1 {{string id}}\n    ENTITY2 {{string id}}\n    ENTITY1 ||--o{{ ENTITY2 : has",
        "classDiagram": f"classDiagram\n    %% {description}\n    class MyClass {{\n        +String name\n        +method()\n    }}",
    }
    mermaid = templates.get(kind, templates["flowchart"])
    note = (
        f"Note: pass `path` (a real .py file) with kind='{kind}' to derive this "
        f"from actual code instead."
        if kind in ("classDiagram", "flowchart")
        else f"Note: customize the template above to match your actual {kind} structure "
        "— sequence/ER diagrams aren't derivable from static analysis alone."
    )
    return f"```mermaid\n{mermaid}\n```\n\n{note}"
