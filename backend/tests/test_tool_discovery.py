"""Day 10 — tool_discovery.py: a thin index over tool_manifest + capability_registry.

Uses a fresh ToolDiscovery instance per test (not the process singleton) so
tests don't depend on which agent modules happen to have been imported
already, and don't leak overlay-registered tools into other tests.
"""
from __future__ import annotations

from app.fleet.capability_registry import AgentCapability, get_capability_registry
from app.fleet.tool_discovery import ToolDiscovery, ToolSpec, get_tool_discovery
from app.fleet.tool_manifest import TOOL_MANIFEST, is_high_risk


def _register_test_agent(name: str, tools: list[str], capabilities: list[str], risk_level: str = "low") -> None:
    get_capability_registry().register(
        AgentCapability(
            name=name,
            description="test agent",
            tools=tools,
            input_types=["text"],
            output_types=["text"],
            capabilities=capabilities,
            risk_level=risk_level,
        )
    )


def test_discover_tools_unions_across_agents_sharing_a_capability_tag() -> None:
    _register_test_agent("td_agent_a", tools=["read_file", "bash"], capabilities=["td_test_cap"])
    _register_test_agent("td_agent_b", tools=["bash", "write_file"], capabilities=["td_test_cap"])
    _register_test_agent("td_agent_c", tools=["search_code"], capabilities=["td_other_cap"])

    d = ToolDiscovery()
    specs = d.discover_tools("td_test_cap")
    names = {s.name for s in specs}

    assert names == {"read_file", "bash", "write_file"}
    assert "search_code" not in names


def test_discover_tools_resolves_real_manifest_data() -> None:
    _register_test_agent("td_agent_bash_user", tools=["bash"], capabilities=["td_bash_cap"])

    d = ToolDiscovery()
    specs = d.discover_tools("td_bash_cap")
    assert len(specs) == 1
    spec = specs[0]
    manifest_entry = TOOL_MANIFEST["bash"]

    assert spec.name == "bash"
    assert spec.description == manifest_entry.purpose
    assert spec.permission_level == manifest_entry.risk_level == "high"
    assert spec.permissions == list(manifest_entry.permissions)


def test_discover_tools_unknown_tool_gets_unknown_permission_level() -> None:
    _register_test_agent("td_agent_unknown_tool", tools=["td_totally_undocumented_tool"], capabilities=["td_unknown_cap"])

    d = ToolDiscovery()
    specs = d.discover_tools("td_unknown_cap")
    assert len(specs) == 1
    assert specs[0].permission_level == "unknown"
    assert specs[0].description == ""


def test_check_compatibility_true_when_tool_declared_on_agent() -> None:
    _register_test_agent("td_agent_declared", tools=["read_file", "write_file"], capabilities=["td_cap"])

    d = ToolDiscovery()
    assert d.check_compatibility("read_file", "td_agent_declared") is True
    assert d.check_compatibility("write_file", "td_agent_declared") is True


def test_check_compatibility_false_when_tool_not_declared() -> None:
    _register_test_agent("td_agent_undeclared", tools=["read_file"], capabilities=["td_cap"])

    d = ToolDiscovery()
    assert d.check_compatibility("bash", "td_agent_undeclared") is False


def test_check_compatibility_false_for_unknown_agent() -> None:
    d = ToolDiscovery()
    assert d.check_compatibility("read_file", "td_nonexistent_agent_xyz") is False


def test_check_availability_true_for_manifest_tool() -> None:
    d = ToolDiscovery()
    assert d.check_availability("bash") is True


def test_check_availability_true_for_top_level_tools_py_function() -> None:
    d = ToolDiscovery()
    assert d.check_availability("web_search") is True


def test_check_availability_false_for_unknown_tool() -> None:
    d = ToolDiscovery()
    assert d.check_availability("td_totally_made_up_tool_name") is False


def test_register_tool_adds_to_overlay_without_mutating_manifest() -> None:
    d = ToolDiscovery()
    manifest_size_before = len(TOOL_MANIFEST)

    assert d.check_availability("td_runtime_registered_tool") is False
    d.register_tool(ToolSpec(name="td_runtime_registered_tool", description="new tool", permission_level="medium"))

    assert d.check_availability("td_runtime_registered_tool") is True
    assert len(TOOL_MANIFEST) == manifest_size_before
    assert "td_runtime_registered_tool" not in TOOL_MANIFEST


def test_register_tool_overlay_is_used_by_discover_tools() -> None:
    _register_test_agent("td_agent_overlay_user", tools=["td_overlay_tool"], capabilities=["td_overlay_cap"])

    d = ToolDiscovery()
    d.register_tool(ToolSpec(name="td_overlay_tool", description="overlay-provided", permission_level="medium", permissions=["fs:write"]))

    specs = d.discover_tools("td_overlay_cap")
    assert len(specs) == 1
    assert specs[0].description == "overlay-provided"
    assert specs[0].permission_level == "medium"
    assert specs[0].permissions == ["fs:write"]


def test_is_high_risk_matches_tool_manifest_for_known_tools() -> None:
    d = ToolDiscovery()
    assert d.is_high_risk("bash") is True
    assert d.is_high_risk("bash") == is_high_risk("bash")
    assert d.is_high_risk("read_file") is False


def test_is_high_risk_uses_overlay_permission_level_when_registered() -> None:
    d = ToolDiscovery()
    d.register_tool(ToolSpec(name="td_high_risk_overlay_tool", description="", permission_level="high"))
    assert d.is_high_risk("td_high_risk_overlay_tool") is True


def test_module_level_singleton_helpers_delegate_to_get_tool_discovery() -> None:
    from app.fleet import tool_discovery as td_module

    singleton = get_tool_discovery()
    assert singleton is get_tool_discovery()

    _register_test_agent("td_agent_singleton_check", tools=["bash"], capabilities=["td_singleton_cap"])
    specs = td_module.discover_tools("td_singleton_cap")
    assert any(s.name == "bash" for s in specs)
