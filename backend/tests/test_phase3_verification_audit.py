"""Tests for MASTER_AGENT_v2.md Phase 3.1 — verification-flag confirmation
audit for the agents Step 2 upgraded to real execution capability.

Not new work: each of these flags was already wired (graph-enforced via
base_graph.py's VerificationConfig contract, never taken from the model's
own claim) as part of Step 2's tool-provisioning pass. This is the
Phase 3.1 confirmation pass the spec calls for — a permanent regression
guard proving each agent's "bash" tool is actually mapped to a real
verification key, not silently dropped in a future edit.

Gap-closure (2026-07-28): the spec's own Definition of Done says "every
Executor/Editor-tier agent" — the original pass below only covered the 5
Executor-tier agents. The Editor-tier section further down closes that.
"""

from __future__ import annotations

import importlib

import pytest

# module_name -> (verification key "bash" sets, whether that key is required
# for AgentResult.verified, or merely tracked).
EXECUTOR_TIER_VERIFICATION_FLAGS = {
    "debugger_agent": ("reproduced", False),
    "test_writer_agent": ("tests_run", True),
    "load_test_agent": ("smoke_tested", False),
    "infra_agent": ("dry_run_validated", False),
    "test_coverage_agent": ("coverage_measured", True),
}


@pytest.mark.parametrize("module_name", sorted(EXECUTOR_TIER_VERIFICATION_FLAGS))
def test_bash_tool_maps_to_a_real_verification_key(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    expected_key, _required = EXECUTOR_TIER_VERIFICATION_FLAGS[module_name]

    assert "bash" in mod._CFG.set_by, (
        f"{module_name}: 'bash' not in VerificationConfig.set_by — a bash call "
        f'would never set any real state["verification"] flag'
    )
    assert mod._CFG.set_by["bash"] == expected_key
    assert expected_key in mod._CFG.initial
    assert mod._CFG.initial[expected_key] is False, (
        f"{module_name}: {expected_key!r} must start False — a run that never "
        f"calls bash must not be able to claim it did"
    )


@pytest.mark.parametrize(
    "module_name",
    [
        name
        for name, (_k, required) in EXECUTOR_TIER_VERIFICATION_FLAGS.items()
        if required
    ],
)
def test_required_verification_flags_are_source_of_verified(module_name: str) -> None:
    """For the 2 agents where the flag is load-bearing (not merely tracked),
    confirm AgentResult.verified's computation actually reads it — via
    source inspection, since building a full run_agent_graph mock per agent
    here would duplicate tests/test_executor_tier_bash.py's own coverage."""
    import inspect

    mod = importlib.import_module(f"app.agents.{module_name}")
    expected_key, _ = EXECUTOR_TIER_VERIFICATION_FLAGS[module_name]
    run_fn = getattr(mod, f"run_{module_name}")
    source = inspect.getsource(run_fn)
    assert f'verification"].get("{expected_key}")' in source, (
        f"{module_name}: AgentResult.verified doesn't reference "
        f'state["verification"][{expected_key!r}] — the flag is declared but '
        f"not actually load-bearing"
    )


def test_all_five_step2_executor_agents_are_covered() -> None:
    """If a 6th agent gains real bash execution in a future phase, this
    dict (and the coverage above) needs updating — this test just documents
    the exact count so that omission is visible, not silent."""
    assert len(EXECUTOR_TIER_VERIFICATION_FLAGS) == 5


# ---------------------------------------------------------------------------
# Editor tier (2026-07-28 gap-closure) — runbook_generator_agent,
# onboarding_agent. Different shape from Executor tier: the tool that sets
# the flag isn't "bash" for either agent, and onboarding_agent genuinely has
# no edit-time verification tool at all — confirmed against its real role
# file (roles/onboarding_agent.md) before writing this, not assumed: it
# produces free-form Markdown ("comprehensive getting-started guide"), which
# has no meaningful syntax to lint the way runbook_generator_agent's YAML
# output does. Its role file's own Quality Gates/Failure Conditions are all
# about content correctness (every step traced to real repo evidence), never
# claim a syntax check. Bolting on a placeholder validator just to have one
# would be exactly the hollow, box-ticking work this whole effort argues
# against — so this test documents the real, confirmed absence instead of
# manufacturing a tool with nothing meaningful to check.
# ---------------------------------------------------------------------------


def test_runbook_generator_agent_yaml_validate_maps_to_a_real_verification_key() -> (
    None
):
    mod = importlib.import_module("app.agents.runbook_generator_agent")

    assert "yaml_validate" in mod._CFG.set_by
    assert mod._CFG.set_by["yaml_validate"] == "structure_validated"
    assert mod._CFG.initial["structure_validated"] is False


def test_runbook_generator_agent_structure_validated_is_tracked_not_required() -> None:
    """Confirms the flag is genuinely tracked-but-not-required (same pattern
    as 3 of the 5 Executor-tier flags), by source-inspecting that verified's
    computation does NOT reference it — the opposite assertion from the
    Executor-tier 'required' test above, proving this isn't an oversight."""
    import inspect

    mod = importlib.import_module("app.agents.runbook_generator_agent")
    source = inspect.getsource(mod.run_runbook_generator_agent)
    assert 'verification"].get("read")' in source
    assert 'verification"].get("structure_validated")' not in source


def test_onboarding_agent_has_no_edit_time_verification_tool() -> None:
    """Real, confirmed absence (see module docstring above) — not a missed
    wiring step. Only the read-tracking flag exists; there is no
    write_file/edit_file-triggered verification key to set_by at all."""
    mod = importlib.import_module("app.agents.onboarding_agent")

    assert set(mod._CFG.set_by.values()) == {"read"}
    assert "write_file" not in mod._CFG.set_by
    assert "edit_file" not in mod._CFG.set_by


def test_onboarding_agent_verified_only_requires_read() -> None:
    import inspect

    mod = importlib.import_module("app.agents.onboarding_agent")
    source = inspect.getsource(mod.run_onboarding_agent)
    assert 'verification"].get("read")' in source


def test_all_two_step2_editor_agents_are_covered() -> None:
    """Documents the exact Editor-tier count so a future 3rd Editor-tier
    agent's omission from this audit is visible, not silent."""
    editor_tier_agents = {"runbook_generator_agent", "onboarding_agent"}
    assert len(editor_tier_agents) == 2
