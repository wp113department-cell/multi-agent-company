"""Tests for MASTER_AGENT_v2.md Phase 2.1 — Editor tier.

Covers `runbook_generator_agent` and `onboarding_agent` (real edit_file
capability, using the already-real handler from make_chat_handlers — no new
handler factory needed, matching the same "handler already existed, only
the schema was missing" pattern Phase 2.3 found). Also covers the one
real correction made while doing this: `localization_agent` was named as
an Editor-tier example in MASTER_AGENT_v2.md's own spec text, but its role
file (roles/localization_agent.md) explicitly and repeatedly declares
itself read-only on code ("Modifying, creating, or deleting any repo file"
is a Failure Condition, "Zero repo files were modified" is a Quality Gate) —
trusting that concrete, deliberate contract over the abstract spec example,
localization_agent stays Analyzer tier and must NOT gain edit_file.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_ROLES_DIR = Path(__file__).parent.parent / "roles"


@pytest.mark.parametrize("module_name", ["runbook_generator_agent", "onboarding_agent"])
def test_editor_tier_agent_has_edit_file(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    assert "edit_file" in mod.AGENT_CONTRACT["allowed_tools"]
    real_tool_names = {t["name"] for t in mod._TOOLS}
    assert "edit_file" in real_tool_names


def test_runbook_generator_agent_has_yaml_validate() -> None:
    from app.agents.runbook_generator_agent import _TOOLS, AGENT_CONTRACT

    assert "yaml_validate" in AGENT_CONTRACT["allowed_tools"]
    assert "yaml_validate" in {t["name"] for t in _TOOLS}


def test_runbook_generator_agent_edit_file_handler_is_real() -> None:
    """edit_file must actually be callable, not just declared — reachable
    via make_chat_handlers, the same base every Tier-B/Editor agent uses."""
    from app.agents.runbook_generator_agent import make_runbook_generator_agent_handlers

    handlers = make_runbook_generator_agent_handlers(".")
    assert callable(handlers["edit_file"])
    assert callable(handlers["yaml_validate"])


def test_onboarding_agent_edit_file_handler_is_real() -> None:
    from app.agents.onboarding_agent import make_onboarding_agent_handlers

    handlers = make_onboarding_agent_handlers(".")
    assert callable(handlers["edit_file"])


def test_localization_agent_stays_read_only_no_edit_file() -> None:
    """The correction: localization_agent's own role file declares itself
    read-only on code (Failure Condition + Quality Gate, not ambiguous) —
    it must not have gained edit_file despite being named as an Editor-tier
    example in the original spec text."""
    from app.agents.localization_agent import _TOOLS, AGENT_CONTRACT

    assert "edit_file" not in AGENT_CONTRACT["allowed_tools"]
    assert "edit_file" not in {t["name"] for t in _TOOLS}


def test_localization_agent_role_file_still_declares_read_only() -> None:
    """Guards against a future edit silently dropping this constraint
    without anyone revisiting the tool-tier decision above."""
    role_text = (_ROLES_DIR / "localization_agent.md").read_text(encoding="utf-8")
    assert "read-only on code" in role_text
    assert "Zero repo files were modified" in role_text
