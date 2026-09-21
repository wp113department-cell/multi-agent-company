"""Tests for AUDIT_Q_BATCH15 §37 gap-closure — CapabilityRegistry.update_success_rate
and agent_registry.compute_live_success_rate, the two real pieces
main.py's _fleet_success_rate_sync_loop wires together so
FleetManager.select()'s routing score reflects real AgentRun outcomes
instead of a static registration-time constant.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.fleet.agent_registry import compute_live_success_rate
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry


def _make_capability(name: str, success_rate: float = 0.95) -> AgentCapability:
    return AgentCapability(
        name=name,
        description="test",
        tools=[],
        input_types=[],
        output_types=[],
        capabilities=["x"],
        success_rate=success_rate,
    )


def test_update_success_rate_mutates_registered_entry_in_place() -> None:
    registry = CapabilityRegistry()
    registry.register(_make_capability("td_agent_1", success_rate=0.95))

    updated = registry.update_success_rate("td_agent_1", 0.42)

    assert updated is True
    assert registry.get("td_agent_1").success_rate == 0.42


def test_update_success_rate_returns_false_for_unregistered_name() -> None:
    registry = CapabilityRegistry()
    assert registry.update_success_rate("does_not_exist", 0.5) is False


def test_update_success_rate_visible_via_every_existing_reference() -> None:
    """A `cap = registry.get(name)` reference taken BEFORE the update must
    see the new value too — proves this is a real in-place mutation, not a
    registry-internal-only change (fleet_manager.select() holds exactly
    this kind of reference during scoring)."""
    registry = CapabilityRegistry()
    registry.register(_make_capability("td_agent_2", success_rate=0.95))
    held_ref = registry.get("td_agent_2")

    registry.update_success_rate("td_agent_2", 0.1)

    assert held_ref.success_rate == 0.1


# UPDATED (verification batch B4, #400): the two tests that used to live here mocked
# db.execute().scalars().all() — the ORM boundary itself — so they could not notice the
# query loading every AgentRun row, or counting in-flight runs as failures. The real-DB
# versions are in tests/test_b4_memory_categories.py.
