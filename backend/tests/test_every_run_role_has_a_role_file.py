"""Every role the code actually runs has a role file.

Qoder cross-check H-3 (2026-10-02): bhaskar_agent was run by bhaskar_tool (the
fallback offered to 83 agents) but roles/bhaskar_agent.md never existed, so
load_role() raised on every call and the tool always returned ok=false. The
same "caller but no role file" bug had happened before (see
test_day8_role_prompts.py). This checks the call sites, not a count.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ROLES = Path(__file__).resolve().parents[1] / "roles"


def _literal_role_names() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in (
                "run_agent_graph",
                "build_agent_graph",
                "load_role",
                "run_agent",
            ):
                continue
            for kw in node.keywords:
                if kw.arg == "role_name" and isinstance(kw.value, ast.Constant):
                    found[str(kw.value.value)] = (
                        f"{path.relative_to(APP.parent)}:{node.lineno}"
                    )
            if (
                name == "load_role"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found[str(node.args[0].value)] = (
                    f"{path.relative_to(APP.parent)}:{node.lineno}"
                )
    return found


def test_every_literal_role_name_has_a_role_file() -> None:
    names = _literal_role_names()
    assert "bhaskar_agent" in names, "scanner no longer sees the known call site"
    missing = {
        n: where for n, where in names.items() if not (ROLES / f"{n}.md").exists()
    }
    assert not missing, f"role run without a roles/<name>.md file: {missing}"
