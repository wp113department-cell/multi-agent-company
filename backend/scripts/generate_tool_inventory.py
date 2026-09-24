"""Generate tool_inventory.json — tool_enhance.md §16 (190-Tool
Productionization Master Prompt).

"DO NOT MANUALLY COUNT TOOLS. All tool counts must be generated
programmatically from the repository and inventory." This script is that
generator. It never guesses: every field is derived by parsing real source
files (via `ast`, never regex-as-structural-parser, per the master
prompt's own rule 6) or the real, already-imported TOOL_MANIFEST/
capability_registry objects.

What it does:
1. Walks every .py file under app/ via `ast` and collects every dict
   literal anywhere in the module that has both "name" and "input_schema"
   string keys — the one tool-spec shape used consistently across this
   whole codebase (confirmed by direct inspection before writing this).
2. Cross-references app.fleet.tool_manifest.TOOL_MANIFEST (already-real
   structured metadata: purpose/permissions/timeout_s/retry_policy/
   risk_level) for each discovered tool name.
3. Cross-references every agent module's real AGENT_CONTRACT["allowed_
   tools"] list (imported live, not grepped) to build the authoritative
   tool -> [agent_name, ...] mapping.
4. Greps tests/ (a real, if coarse, signal — refined per-tool during the
   actual audit pass, not treated as final here) for files that reference
   each tool name as a string literal, as a first-pass "has some test
   coverage" signal.
5. Writes tool_inventory.json at the repo root with per-tool fields plus
   a programmatically-generated summary (never hand-counted).
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
TESTS_DIR = REPO_ROOT / "tests"
AGENTS_DIR = APP_DIR / "agents"


def _extract_tool_specs_from_file(path: Path) -> dict[str, dict[str, Any]]:
    """Every dict literal anywhere in `path` with "name" (str) and
    "input_schema" keys -> {tool_name: {"line": int, "source_file": str}}.
    Uses ast.walk so it finds specs regardless of how they're assigned
    (module-level constant, inline list element, nested inside another
    list) — the actual shape varies across this codebase's ~50 agent
    files plus the shared app/agents/tools.py.
    """
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return {}

    specs: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
        if "name" not in keys or "input_schema" not in keys:
            continue
        name_idx = keys.index("name")
        name_val_node = node.values[name_idx]
        if not (
            isinstance(name_val_node, ast.Constant)
            and isinstance(name_val_node.value, str)
        ):
            continue
        tool_name = name_val_node.value
        if tool_name not in specs:
            specs[tool_name] = {
                "line": node.lineno,
                "source_file": str(path.relative_to(REPO_ROOT)),
            }
    return specs


def collect_all_tool_specs() -> dict[str, dict[str, Any]]:
    all_specs: dict[str, dict[str, Any]] = {}
    for py_file in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        file_specs = _extract_tool_specs_from_file(py_file)
        for name, meta in file_specs.items():
            # First occurrence wins for source_file/line — a tool defined
            # once and re-exported/appended elsewhere (e.g. BUG_FIX_TOOLS.
            # append(_DELEGATE_TO_AGENT_TOOL)) should report its real
            # definition site, not every place it's referenced.
            all_specs.setdefault(name, meta)
    return all_specs


def collect_agent_tool_mappings() -> dict[str, list[str]]:
    """tool_name -> sorted list of agent module names whose real,
    imported AGENT_CONTRACT["allowed_tools"] declares it. Imports every
    agent module live (not grepped) so this reflects actual Python state,
    not text pattern-matching."""
    sys.path.insert(0, str(REPO_ROOT))
    mapping: dict[str, set[str]] = {}
    errors: list[str] = []
    for py_file in sorted(AGENTS_DIR.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue
        mod_name = f"app.agents.{py_file.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 — this is an audit tool
            errors.append(f"{mod_name}: {exc}")
            continue
        contract = getattr(mod, "AGENT_CONTRACT", None)
        if not isinstance(contract, dict):
            continue
        allowed = contract.get("allowed_tools") or []
        agent_name = contract.get("name", py_file.stem)
        for tool_name in allowed:
            mapping.setdefault(tool_name, set()).add(agent_name)
    if errors:
        print(
            f"[warn] {len(errors)} agent module(s) failed to import:", file=sys.stderr
        )
        for e in errors[:20]:
            print(f"  {e}", file=sys.stderr)
    return {k: sorted(v) for k, v in mapping.items()}


def collect_test_references() -> Callable[[str], list[str]]:
    """Returns a function name -> sorted list of test files whose source
    text contains that exact quoted string. Coarse (a name could appear in
    an unrelated context) — a real per-tool test-quality audit happens
    later; this is only the initial-pass signal tool_enhance.md's own §28
    planning phase asks for."""
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    contents: dict[Path, str] = {}
    for f in test_files:
        try:
            contents[f] = f.read_text()
        except UnicodeDecodeError:
            continue

    def files_mentioning(name: str) -> list[str]:
        needle = f'"{name}"'
        needle2 = f"'{name}'"
        return sorted(
            str(f.relative_to(REPO_ROOT))
            for f, text in contents.items()
            if needle in text or needle2 in text
        )

    return files_mentioning


def main() -> None:
    specs = collect_all_tool_specs()
    agent_mapping = collect_agent_tool_mappings()

    from app.fleet.tool_manifest import TOOL_MANIFEST

    files_mentioning = collect_test_references()

    tools: list[dict[str, Any]] = []
    for name in sorted(specs):
        meta = specs[name]
        manifest_entry = TOOL_MANIFEST.get(name)
        agents = agent_mapping.get(name, [])
        test_files = files_mentioning(name)
        tools.append(
            {
                "name": name,
                "source_file": meta["source_file"],
                "line": meta["line"],
                "has_manifest_entry": manifest_entry is not None,
                "manifest": (
                    {
                        "purpose": manifest_entry.purpose,
                        "permissions": manifest_entry.permissions,
                        "timeout_s": manifest_entry.timeout_s,
                        "retry_policy": manifest_entry.retry_policy,
                        "verification_required": manifest_entry.verification_required,
                        "risk_level": manifest_entry.risk_level,
                        "notes": manifest_entry.notes,
                    }
                    if manifest_entry is not None
                    else None
                ),
                "agents": agents,
                "agent_count": len(agents),
                "test_files": test_files,
                "test_file_count": len(test_files),
                "registered": name in TOOL_MANIFEST,
                "reachable_by_any_agent": len(agents) > 0,
            }
        )

    # Manifest entries with no discovered spec dict — either a real stale
    # entry (tool removed but manifest not cleaned up) or a spec this
    # script's AST pattern doesn't catch (e.g. built dynamically) — a real
    # gap either way, surfaced explicitly rather than silently dropped.
    manifest_only = sorted(set(TOOL_MANIFEST) - set(specs))

    summary = {
        "total_tools_with_spec": len(tools),
        "total_manifest_entries": len(TOOL_MANIFEST),
        "manifest_entries_with_no_discovered_spec": manifest_only,
        "tools_with_manifest_entry": sum(1 for t in tools if t["has_manifest_entry"]),
        "tools_without_manifest_entry": sum(
            1 for t in tools if not t["has_manifest_entry"]
        ),
        "tools_with_zero_agents": sum(1 for t in tools if t["agent_count"] == 0),
        "tools_with_zero_test_files": sum(
            1 for t in tools if t["test_file_count"] == 0
        ),
        "risk_level_breakdown": {
            level: sum(
                1
                for t in tools
                if t["manifest"] is not None and t["manifest"]["risk_level"] == level
            )
            for level in ("low", "medium", "high")
        },
    }

    output = {"summary": summary, "tools": tools}
    out_path = REPO_ROOT / "tool_inventory.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(
        f"Wrote {out_path} — {summary['total_tools_with_spec']} tool specs discovered"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
