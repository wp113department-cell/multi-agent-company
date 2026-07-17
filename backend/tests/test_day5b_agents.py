"""Tests for Day 5B agents: AGENT_CONTRACT, handler structure, role files, and fleet registration."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).parent.parent
_ROLES_DIR = _BACKEND.parent / "backend" / "roles"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAY5B_MODULES = [
    "app.agents.code_explainer_agent",
    "app.agents.code_quality_agent",
    "app.agents.accessibility_agent",
    "app.agents.api_designer_agent",
    "app.agents.compliance_agent",
    "app.agents.cost_estimator_agent",
    "app.agents.data_pipeline_agent",
    "app.agents.debugger_agent",
]

_REQUIRED_CONTRACT_KEYS = [
    "name", "description", "allowed_tools", "input_types", "output_types",
    "side_effects", "permissions", "risk_level", "expected_verification", "dependencies",
]


def _load(module_name: str) -> Any:
    if module_name in sys.modules:
        return sys.modules[module_name]
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Parametrised: AGENT_CONTRACT presence and shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_agent_contract_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "AGENT_CONTRACT"), f"{module_name} missing AGENT_CONTRACT"
    contract = mod.AGENT_CONTRACT
    assert isinstance(contract, dict), f"{module_name} AGENT_CONTRACT must be a dict"
    for key in _REQUIRED_CONTRACT_KEYS:
        assert key in contract, f"{module_name} AGENT_CONTRACT missing key '{key}'"


@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_agent_contract_non_empty_lists(module_name: str) -> None:
    mod = _load(module_name)
    contract = mod.AGENT_CONTRACT
    assert len(contract["allowed_tools"]) > 0, f"{module_name}: allowed_tools must not be empty"
    assert len(contract["input_types"]) > 0, f"{module_name}: input_types must not be empty"
    assert len(contract["output_types"]) > 0, f"{module_name}: output_types must not be empty"


@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_agent_contract_name_matches_module(module_name: str) -> None:
    mod = _load(module_name)
    short_name = module_name.split(".")[-1]
    assert mod.AGENT_CONTRACT["name"] == short_name, (
        f"{module_name}: contract name '{mod.AGENT_CONTRACT['name']}' != module name '{short_name}'"
    )


# ---------------------------------------------------------------------------
# Parametrised: VerificationConfig enforce_in_result non-empty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_verification_config_enforce_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    cfg = getattr(mod, "_CFG", None)
    assert cfg is not None, f"{module_name} missing _CFG"
    assert hasattr(cfg, "enforce_in_result"), f"{module_name} _CFG missing enforce_in_result"
    assert cfg.enforce_in_result, (
        f"{module_name} _CFG.enforce_in_result must not be empty (was {{}})"
    )


@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_verification_config_set_by_non_empty(module_name: str) -> None:
    mod = _load(module_name)
    cfg = mod._CFG
    assert cfg.set_by, f"{module_name} _CFG.set_by must not be empty"


# ---------------------------------------------------------------------------
# Parametrised: role file exists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_role_file_exists(module_name: str) -> None:
    short_name = module_name.split(".")[-1]
    role_file = _BACKEND.parent / "backend" / "roles" / f"{short_name}.md"
    assert role_file.exists(), f"Role file missing: {role_file}"
    assert role_file.stat().st_size > 100, f"Role file too small (stub?): {role_file}"


# ---------------------------------------------------------------------------
# Parametrised: submit tool in _TOOLS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_submit_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tools = getattr(mod, "_TOOLS", [])
    assert tools, f"{module_name} missing _TOOLS"
    tool_names = {t["name"] for t in tools}
    short_name = module_name.split(".")[-1]
    expected = f"submit_{short_name}"
    assert expected in tool_names, (
        f"{module_name}: expected submit tool '{expected}' in _TOOLS, found: {tool_names}"
    )


@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_write_file_tool_in_tools_list(module_name: str) -> None:
    mod = _load(module_name)
    tools = getattr(mod, "_TOOLS", [])
    tool_names = {t["name"] for t in tools}
    assert "write_file" in tool_names, f"{module_name}: write_file must be in _TOOLS"


# ---------------------------------------------------------------------------
# Parametrised: handler factory returns dict with _result and submit key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name,factory_fn", [
    ("app.agents.code_explainer_agent", "make_code_explainer_agent_handlers"),
    ("app.agents.code_quality_agent", "make_code_quality_agent_handlers"),
    ("app.agents.accessibility_agent", "make_accessibility_agent_handlers"),
    ("app.agents.api_designer_agent", "make_api_designer_agent_handlers"),
    ("app.agents.compliance_agent", "make_compliance_agent_handlers"),
    ("app.agents.cost_estimator_agent", "make_cost_estimator_agent_handlers"),
    ("app.agents.data_pipeline_agent", "make_data_pipeline_agent_handlers"),
    ("app.agents.debugger_agent", "make_debugger_agent_handlers"),
])
def test_handler_factory_returns_dict(module_name: str, factory_fn: str) -> None:
    mod = _load(module_name)
    factory = getattr(mod, factory_fn, None)
    assert factory is not None, f"{module_name} missing {factory_fn}"
    handlers = factory("/tmp/fake_repo")
    assert isinstance(handlers, dict), f"{module_name} {factory_fn} must return dict"
    assert "_result" in handlers, f"{module_name} handlers must contain '_result' key"


@pytest.mark.parametrize("module_name,factory_fn,submit_key", [
    ("app.agents.code_explainer_agent", "make_code_explainer_agent_handlers", "submit_code_explainer_agent"),
    ("app.agents.code_quality_agent", "make_code_quality_agent_handlers", "submit_code_quality_agent"),
    ("app.agents.accessibility_agent", "make_accessibility_agent_handlers", "submit_accessibility_agent"),
    ("app.agents.api_designer_agent", "make_api_designer_agent_handlers", "submit_api_designer_agent"),
    ("app.agents.compliance_agent", "make_compliance_agent_handlers", "submit_compliance_agent"),
    ("app.agents.cost_estimator_agent", "make_cost_estimator_agent_handlers", "submit_cost_estimator_agent"),
    ("app.agents.data_pipeline_agent", "make_data_pipeline_agent_handlers", "submit_data_pipeline_agent"),
    ("app.agents.debugger_agent", "make_debugger_agent_handlers", "submit_debugger_agent"),
])
def test_submit_handler_callable_and_updates_result(
    module_name: str, factory_fn: str, submit_key: str
) -> None:
    mod = _load(module_name)
    factory = getattr(mod, factory_fn)
    handlers = factory("/tmp/fake_repo")
    submit = handlers[submit_key]
    assert callable(submit), f"{module_name}: {submit_key} must be callable"
    ret = submit({"summary": "test summary", "findings": ["finding1"]})
    assert ret == "Submitted."
    result = handlers["_result"]
    assert result.get("summary") == "test summary"
    assert result.get("findings") == ["finding1"]


# ---------------------------------------------------------------------------
# Parametrised: run_<agent> returns AgentResult when run_agent_graph is mocked
# ---------------------------------------------------------------------------

def _make_fake_state(**kwargs: Any) -> dict[str, Any]:
    return {
        "result": {"summary": "mocked", "findings": []},
        "verification": {"read": True},
        "submitted": True,
        "tokens_in": 10,
        "tokens_out": 20,
        **kwargs,
    }


@pytest.mark.parametrize("module_name,run_fn", [
    ("app.agents.code_explainer_agent", "run_code_explainer_agent"),
    ("app.agents.code_quality_agent", "run_code_quality_agent"),
    ("app.agents.accessibility_agent", "run_accessibility_agent"),
    ("app.agents.api_designer_agent", "run_api_designer_agent"),
    ("app.agents.compliance_agent", "run_compliance_agent"),
    ("app.agents.cost_estimator_agent", "run_cost_estimator_agent"),
    ("app.agents.data_pipeline_agent", "run_data_pipeline_agent"),
    ("app.agents.debugger_agent", "run_debugger_agent"),
])
def test_run_fn_returns_agent_result(module_name: str, run_fn: str) -> None:
    from app.agents.agent_result import AgentResult

    mod = _load(module_name)
    fn = getattr(mod, run_fn, None)
    assert fn is not None, f"{module_name} missing {run_fn}"

    # Patch in each agent module's namespace (they do `from base_graph import run_agent_graph`)
    patch_target = f"{module_name}.run_agent_graph"
    with patch(patch_target, return_value=_make_fake_state()):
        result = fn(task_id=1, description="test task", repo_path="/tmp/fake_repo")

    assert isinstance(result, AgentResult), (
        f"{module_name} {run_fn} must return AgentResult, got {type(result)}"
    )
    assert result.status in ("completed", "blocked")
    assert isinstance(result.tokens_in, int)
    assert isinstance(result.tokens_out, int)


# ---------------------------------------------------------------------------
# Parametrised: capability tags are unique across all 8 agents
# ---------------------------------------------------------------------------

def test_capability_tags_unique_across_day5b() -> None:
    from app.fleet.capability_registry import get_capability_registry

    reg = get_capability_registry()
    seen_caps: dict[str, str] = {}
    for module_name in _DAY5B_MODULES:
        short = module_name.split(".")[-1]
        entry = reg.get(short)
        if entry is None:
            continue
        for cap in entry.capabilities:
            if cap in seen_caps:
                pytest.fail(
                    f"Duplicate capability tag '{cap}' found in both "
                    f"'{seen_caps[cap]}' and '{short}'"
                )
            seen_caps[cap] = short


# ---------------------------------------------------------------------------
# Parametrised: _register() function exists and is callable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", _DAY5B_MODULES)
def test_register_function_exists(module_name: str) -> None:
    mod = _load(module_name)
    assert hasattr(mod, "_register"), f"{module_name} missing _register function"
    assert callable(mod._register), f"{module_name} _register must be callable"
