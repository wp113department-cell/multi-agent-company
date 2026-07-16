"""Tests for Fleet OS capability_registry.py — Phase F1."""
from __future__ import annotations

import pytest

from app.fleet.capability_registry import (
    AgentCapability,
    CapabilityRegistry,
    get_capability_registry,
    register,
)


def test_get_capability_registry_returns_singleton() -> None:
    r1 = get_capability_registry()
    r2 = get_capability_registry()
    assert r1 is r2


def test_register_and_get() -> None:
    r = CapabilityRegistry()
    cap = AgentCapability(
        name="test_agent",
        description="Test",
        tools=["read_file"],
        input_types=["task_id"],
        output_types=["AgentResult"],
        capabilities=["testing"],
    )
    r.register(cap)
    assert r.get("test_agent") is cap


def test_get_missing_returns_none() -> None:
    r = CapabilityRegistry()
    assert r.get("nonexistent") is None


def test_find_by_capability() -> None:
    r = CapabilityRegistry()
    r.register(AgentCapability(
        name="a1", description="", tools=[], input_types=[], output_types=[],
        capabilities=["bug_fix", "code_edit"],
    ))
    r.register(AgentCapability(
        name="a2", description="", tools=[], input_types=[], output_types=[],
        capabilities=["qa_verification"],
    ))
    bug_fixers = r.find_by_capability("bug_fix")
    assert len(bug_fixers) == 1
    assert bug_fixers[0].name == "a1"
    qa = r.find_by_capability("qa_verification")
    assert qa[0].name == "a2"


def test_find_by_capability_returns_empty_for_unknown() -> None:
    r = CapabilityRegistry()
    assert r.find_by_capability("no_such_capability") == []


def test_all_returns_all_entries() -> None:
    r = CapabilityRegistry()
    for i in range(3):
        r.register(AgentCapability(
            name=f"agent_{i}", description="", tools=[], input_types=[], output_types=[],
            capabilities=[],
        ))
    assert r.count() == 3


def test_register_updates_existing() -> None:
    r = CapabilityRegistry()
    r.register(AgentCapability(
        name="same", description="v1", tools=[], input_types=[], output_types=[],
        capabilities=[],
    ))
    r.register(AgentCapability(
        name="same", description="v2", tools=[], input_types=[], output_types=[],
        capabilities=[],
    ))
    assert r.count() == 1
    assert r.get("same").description == "v2"


# ---- Reference agent registrations (Day 0 contract) ----

def test_reference_agents_registered_at_import() -> None:
    r = get_capability_registry()
    for name in ("pm", "bug_fix", "qa"):
        cap = r.get(name)
        assert cap is not None, f"Reference agent {name!r} not registered"
        assert cap.name == name
        assert len(cap.tools) > 0
        assert len(cap.capabilities) > 0


def test_pm_contract_fields() -> None:
    cap = get_capability_registry().get("pm")
    assert cap is not None
    assert "planning" in cap.capabilities
    assert cap.risk_level == "low"
    assert cap.requires_worktree is False


def test_bug_fix_contract_fields() -> None:
    cap = get_capability_registry().get("bug_fix")
    assert cap is not None
    assert "bug_fix" in cap.capabilities
    assert "edit_file" in cap.tools
    assert cap.requires_worktree is True
    assert cap.risk_level == "medium"


def test_qa_contract_no_write_tools() -> None:
    cap = get_capability_registry().get("qa")
    assert cap is not None
    assert "write_file" not in cap.tools
    assert "edit_file" not in cap.tools
    assert "qa_verification" in cap.capabilities
