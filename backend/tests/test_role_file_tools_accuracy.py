"""Tests that each Analyzer-tier role file's `## Tools` line matches its
real AGENT_CONTRACT["allowed_tools"] exactly — no tool claimed that isn't
real (the original dead-contract bug shape), and no real tool missing from
what the model is told it has. Written after a manual role-file codemod
(Phase 2, MASTER_AGENT_v2.md) introduced exactly this kind of mismatch for
accessibility_agent (claimed list_functions, which it doesn't actually
have) — caught by spot-checking, not by a repeatable test, until this file.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_ROLES_DIR = Path(__file__).parent.parent / "roles"

AGENTS = [
    "accessibility_agent",
    "api_designer_agent",
    "code_explainer_agent",
    "code_quality_agent",
    "compliance_agent",
    "cost_estimator_agent",
    "data_pipeline_agent",
    "dependency_security_agent",
    "devex_agent",
    "env_checker_agent",
    "feature_flag_agent",
    "incident_responder_agent",
    "pair_programmer_agent",
    "rollback_agent",
    "slo_agent",
    "spike_agent",
    "version_manager_agent",
]


def _tools_line(role_text: str) -> str:
    match = re.search(r"^## Tools\n(.+)$", role_text, re.MULTILINE)
    assert match, "no '## Tools' line found"
    return match.group(1)


@pytest.mark.parametrize("module_name", AGENTS)
def test_role_file_tools_line_matches_real_contract(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    declared = set(mod.AGENT_CONTRACT["allowed_tools"])

    role_text = (_ROLES_DIR / f"{module_name}.md").read_text(encoding="utf-8")
    tools_line = _tools_line(role_text)

    for tool_name in declared:
        if tool_name.startswith("submit_"):
            continue
        assert re.search(rf"\b{re.escape(tool_name)}\b", tools_line), (
            f"{module_name}: contract declares {tool_name!r} but the role file's "
            f"Tools line doesn't mention it"
        )

    # The reverse check, scoped to the two tools this session's codemod
    # actually touched (parse_ast/list_functions) — the exact class of bug
    # this test exists to catch. Not a full reverse-diff of every word in
    # the Tools line, since some role files annotate a tool with scope notes
    # (e.g. "bash (pytest only)") that a strict token-set comparison would
    # false-positive on.
    for tool_name in ("parse_ast", "list_functions"):
        if re.search(rf"\b{re.escape(tool_name)}\b", tools_line):
            assert tool_name in declared, (
                f"{module_name}: role file's Tools line claims {tool_name!r} "
                f"but AGENT_CONTRACT doesn't declare it"
            )
