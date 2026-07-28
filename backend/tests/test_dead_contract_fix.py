"""Tests for MASTER_AGENT_v2.md Phase 2.3 — the dead-contract bug fix.

Confirmed by the original audit: ~24 Tier-B agents declared "parse_ast"/
"list_functions" in AGENT_CONTRACT["allowed_tools"] while the real tools=
schema passed to run_agent_graph never included them — since the Anthropic
API only allows a model to call tools declared in that request's own tools=
list, these agents could never actually call parse_ast/list_functions no
matter what their published contract claimed. The handlers themselves were
already real (reachable via make_chat_handlers, which every one of these
agents already calls as their base handler dict) — only the tool *schema*
was missing from _TOOLS. This proves both halves are now true together: the
contract claim and the real, callable schema.
"""

from __future__ import annotations

import importlib

import pytest

from app.agents.tools import make_chat_handlers

# module_name -> the code-intelligence tools its AGENT_CONTRACT actually
# declares (re-derive with `grep -oE '"(parse_ast|list_functions)"'
# app/agents/<name>.py` if this list ever needs to be refreshed).
AGENTS_WITH_CODE_INTEL_TOOLS: dict[str, list[str]] = {
    "accessibility_agent": ["parse_ast"],
    "api_designer_agent": ["list_functions", "parse_ast"],
    "code_explainer_agent": ["list_functions", "parse_ast"],
    "code_quality_agent": ["list_functions", "parse_ast"],
    "cost_estimator_agent": ["list_functions", "parse_ast"],
    "data_pipeline_agent": ["list_functions", "parse_ast"],
    "debugger_agent": ["list_functions", "parse_ast"],
    "dependency_security_agent": ["list_functions", "parse_ast"],
    "devex_agent": ["list_functions", "parse_ast"],
    "env_checker_agent": ["list_functions", "parse_ast"],
    "feature_flag_agent": ["list_functions", "parse_ast"],
    "incident_responder_agent": ["list_functions", "parse_ast"],
    "infra_agent": ["list_functions", "parse_ast"],
    "load_test_agent": ["list_functions", "parse_ast"],
    "localization_agent": ["list_functions", "parse_ast"],
    "onboarding_agent": ["list_functions", "parse_ast"],
    "pair_programmer_agent": ["list_functions", "parse_ast"],
    "rollback_agent": ["list_functions", "parse_ast"],
    "runbook_generator_agent": ["list_functions", "parse_ast"],
    "slo_agent": ["list_functions", "parse_ast"],
    "spike_agent": ["list_functions", "parse_ast"],
    "test_coverage_agent": ["list_functions", "parse_ast"],
    "test_writer_agent": ["list_functions", "parse_ast"],
    "version_manager_agent": ["list_functions", "parse_ast"],
}


@pytest.mark.parametrize("module_name", sorted(AGENTS_WITH_CODE_INTEL_TOOLS))
def test_declared_code_intel_tools_are_in_real_tools_schema(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    declared = AGENTS_WITH_CODE_INTEL_TOOLS[module_name]
    real_tool_names = {t["name"] for t in mod._TOOLS}

    for tool_name in declared:
        assert (
            tool_name in mod.AGENT_CONTRACT["allowed_tools"]
        ), f"{module_name}: {tool_name!r} expected in AGENT_CONTRACT (test data stale?)"
        assert tool_name in real_tool_names, (
            f"{module_name}: {tool_name!r} is declared in AGENT_CONTRACT but still "
            f"missing from the real _TOOLS schema — dead-contract bug not fixed"
        )


@pytest.mark.parametrize("module_name", sorted(AGENTS_WITH_CODE_INTEL_TOOLS))
def test_agent_contract_declares_no_tool_missing_a_real_handler(
    module_name: str,
) -> None:
    """Every tool in AGENT_CONTRACT["allowed_tools"] (minus the agent's own
    submit_* tool, which isn't in make_chat_handlers' base dict) must have a
    real, callable handler reachable from make_chat_handlers — the same
    "contract vs. reality" check, from the handler side instead of the
    schema side."""
    mod = importlib.import_module(f"app.agents.{module_name}")
    base_handlers = make_chat_handlers(".")

    for tool_name in mod.AGENT_CONTRACT["allowed_tools"]:
        if tool_name.startswith("submit_") or tool_name == "record_learning":
            continue  # agent-specific / Phase 1.4 tool, not from make_chat_handlers
        assert tool_name in base_handlers, (
            f"{module_name}: {tool_name!r} declared in AGENT_CONTRACT has no "
            f"real handler in make_chat_handlers()"
        )
        assert callable(base_handlers[tool_name])


def test_parse_ast_and_list_functions_handlers_actually_work() -> None:
    """Sanity: the handlers these 24 agents now have real schema access to
    are not stubs — they return real analysis, not a placeholder string."""
    handlers = make_chat_handlers(".")

    result = handlers["list_functions"]({"path": "app/agents/tools.py"})
    assert "make_chat_handlers" in result or "def " in result.lower()

    result = handlers["parse_ast"]({"path": "app/agents/agent_result.py"})
    assert "AgentResult" in result or "class" in result.lower()
