"""Gap-closure Day 6 (root cause 3, answers.md Q75/Q93) — wiring proof that
`memory_promote_lesson` (the tool a human-approved knowledge_curator APPLY
run actually calls) is real, correctly delegates to
VersionedMemoryStore.promote(), and is fully declared/wired for
knowledge_curator: in AGENT_CONTRACT, in both SCAN_TOOLS (memory_list_draft_
lessons, for discovery) and APPLY_TOOLS (memory_promote_lesson, for the
gated action), and bound to a real handler in make_apply_handlers/
make_scan_handlers — the same "declared in contract, present in the real
tools= schema, wired to a real callable handler" discipline
test_record_learning_rollout.py already established for this codebase.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents import knowledge_curator
from app.agents.tools import memory_promote_lesson


def test_memory_promote_lesson_tool_delegates_to_the_store() -> None:
    fake_record = MagicMock(id=7)
    with patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_get_store.return_value.promote.return_value = fake_record
        result = memory_promote_lesson({"lesson_id": "lesson-xyz"})

    mock_get_store.return_value.promote.assert_called_once_with(
        "lesson-xyz", agent_name="knowledge_curator"
    )
    assert "lesson-xyz" in result
    assert "promoted" in result


def test_memory_promote_lesson_tool_surfaces_a_missing_draft_as_a_real_error() -> None:
    with patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_get_store.return_value.promote.side_effect = ValueError(
            "No draft version to promote for lesson_id='nope'"
        )
        result = memory_promote_lesson({"lesson_id": "nope"})

    assert result.startswith("[ERROR]")
    assert "No draft version to promote" in result


def test_memory_promote_lesson_declared_in_knowledge_curator_contract() -> None:
    assert "memory_promote_lesson" in knowledge_curator.AGENT_CONTRACT["allowed_tools"]
    assert (
        "memory_list_draft_lessons" in knowledge_curator.AGENT_CONTRACT["allowed_tools"]
    )


def test_memory_promote_lesson_present_in_apply_tools_schema() -> None:
    names = {t["name"] for t in knowledge_curator.APPLY_TOOLS}
    assert "memory_promote_lesson" in names


def test_memory_list_draft_lessons_present_in_scan_tools_schema() -> None:
    names = {t["name"] for t in knowledge_curator.SCAN_TOOLS}
    assert "memory_list_draft_lessons" in names


def test_memory_promote_lesson_wired_to_a_real_handler_in_apply_mode() -> None:
    handlers = knowledge_curator.make_apply_handlers("/tmp/fake-repo")
    assert handlers["memory_promote_lesson"] is memory_promote_lesson


def test_memory_list_draft_lessons_wired_to_a_real_handler_in_scan_mode() -> None:
    from app.agents.tools import memory_list_draft_lessons

    handlers = knowledge_curator.make_scan_handlers("/tmp/fake-repo")
    assert handlers["memory_list_draft_lessons"] is memory_list_draft_lessons


def test_apply_verification_config_treats_promotion_as_real_curation() -> None:
    """memory_promote_lesson must satisfy the same 'curated' verification
    flag memory_curate_write does — a promotion-only APPLY run must not be
    blocked as unverified just because it didn't also call
    memory_curate_write."""
    assert knowledge_curator._APPLY_CFG.set_by.get("memory_promote_lesson") == "curated"
