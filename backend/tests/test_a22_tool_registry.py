"""Sol A22 (2026-10-09): one authoritative tool registry, failing closed.

67 tools agents declare had no manifest entry (no risk, permissions or
timeout), and a tool with no entry counted as "not high risk", so contract
checks never applied to it — git_commit_change, memory_curate_write,
memory_promote_lesson and resolve_merge_conflict among them. Now every tool
an agent declares or defines has an entry (agents' own submit_* result tools
share one), an unknown tool is treated as high risk, and this file is the CI
consistency check that keeps it that way.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import pytest

from app.fleet.tool_manifest import (
    TOOL_MANIFEST,
    get_manifest,
    is_high_risk,
)

PERMISSIONS = {
    "read_repo",
    "write_repo",
    "read_db",
    "write_db",
    "read_memory",
    "write_memory",
    "read_env",
    "network",
    "execute",
    "docker",
    "browser",
    "write_remote",
    "write_pipeline_state",
}


def _agent_tool_names() -> dict[str, set[str]]:
    """Every tool name an agent module declares in its contract or defines in
    a module-level tool list, with where it was found."""
    import app.agents as agents_pkg

    found: dict[str, set[str]] = {}

    def visit(obj: Any, where: str) -> None:
        if isinstance(obj, (list, tuple)):
            for item in obj:
                visit(item, where)
        elif (
            isinstance(obj, dict)
            and isinstance(obj.get("name"), str)
            and "input_schema" in obj
        ):
            found.setdefault(obj["name"], set()).add(where)

    for info in pkgutil.iter_modules(agents_pkg.__path__):
        module = importlib.import_module(f"app.agents.{info.name}")
        for attr, value in vars(module).items():
            if isinstance(value, (list, tuple, dict)):
                visit(value, f"{info.name}.{attr}")
        contract = getattr(module, "AGENT_CONTRACT", None)
        if isinstance(contract, dict):
            for name in contract.get("allowed_tools", []):
                found.setdefault(name, set()).add(f"{info.name}.AGENT_CONTRACT")
    return found


def test_every_agent_tool_has_a_manifest_entry() -> None:
    tools = _agent_tool_names()
    assert len(tools) > 250
    missing = {
        name: sorted(w) for name, w in tools.items() if get_manifest(name) is None
    }
    assert not missing, f"add these to app/fleet/tool_manifest.py: {missing}"


def test_every_entry_is_well_formed() -> None:
    for name, entry in TOOL_MANIFEST.items():
        assert entry.risk_level in {"low", "medium", "high"}, name
        assert entry.retry_policy in {"none", "once", "backoff"}, name
        assert set(entry.permissions) <= PERMISSIONS, (name, entry.permissions)
        assert entry.timeout_s > 0, name
        if {"write_repo", "write_remote", "write_db"} & set(entry.permissions):
            assert entry.risk_level != "low" or name in _LOW_RISK_WRITERS, name


# Small, contained writes inside the worktree that were already rated low.
_LOW_RISK_WRITERS = {
    "copy_file",
    "format_file",
    "organize_imports",
    "create_directory",
    "zip_files",
    "unzip_files",
    "decision_log_append",
    "known_issues_write",
}


@pytest.mark.parametrize(
    ("name", "risk", "permission"),
    [
        ("git_commit_change", "medium", "write_repo"),
        ("memory_curate_write", "medium", "write_memory"),
        ("memory_promote_lesson", "medium", "write_memory"),
        ("resolve_merge_conflict", "medium", "write_repo"),
        ("repeat_previous_task", "medium", "write_db"),
        ("run_sandboxed_script", "medium", "execute"),
    ],
)
def test_the_side_effect_tools_the_audit_named_are_governed(
    name: str, risk: str, permission: str
) -> None:
    entry = get_manifest(name)
    assert entry is not None
    assert entry.risk_level == risk and permission in entry.permissions


def test_submit_tools_share_the_result_entry() -> None:
    entry = get_manifest("submit_some_new_agent")
    assert entry is not None and entry.risk_level == "low" and not entry.permissions


def test_an_unknown_tool_fails_closed() -> None:
    assert is_high_risk("totally_new_tool_nobody_registered")
    assert not is_high_risk("read_file")
    assert is_high_risk("git_push")


def test_an_unknown_undeclared_tool_is_not_offered_to_an_agent() -> None:
    from app.fleet.tool_discovery import ToolDiscovery

    def handler(_: dict[str, Any]) -> str:
        return "ok"

    tools = [
        {"name": "read_file", "description": "", "input_schema": {}},
        {"name": "sneaky_new_writer", "description": "", "input_schema": {}},
    ]
    handlers = {"read_file": handler, "sneaky_new_writer": handler}
    kept = ToolDiscovery().filter_runtime_tools("backend_dev", tools, handlers)
    assert [t["name"] for t in kept] == ["read_file"]
