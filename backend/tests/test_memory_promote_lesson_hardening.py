"""memory_promote_lesson tool #226 — tool_enhance.md productionization
pass (2026-09-17).

Real finding: `lesson_id = str(inp["lesson_id"])` used bare dict
indexing before the function's own try/except guards. Proved live:
memory_promote_lesson({}) raised an uncaught KeyError: 'lesson_id'.
Fixed by using `.get("lesson_id")` with an explicit presence check for
a clean "[ERROR] lesson_id is required" message.

No duplicate-isolated-engine-helper finding here (unlike sibling tools
#223/#224/#225) — this tool delegates entirely to
app.fleet.versioned_memory's own promote() method, which manages its
own DB access internally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents.tools import CHAT_TOOLS, memory_promote_lesson
from app.tools.agents.memory_promote_lesson import (
    MEMORY_PROMOTE_LESSON_TOOL,
    memory_promote_lesson_handler,
)


def test_schema() -> None:
    assert MEMORY_PROMOTE_LESSON_TOOL["name"] == "memory_promote_lesson"
    assert MEMORY_PROMOTE_LESSON_TOOL["input_schema"]["required"] == ["lesson_id"]  # type: ignore[index]


def test_not_in_chat_tools() -> None:
    assert "memory_promote_lesson" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: missing `lesson_id` no longer crashes
# ---------------------------------------------------------------------------


def test_missing_lesson_id_key_returns_clean_error_not_uncaught_keyerror() -> None:
    result = memory_promote_lesson_handler({})
    assert result == "[ERROR] lesson_id is required"


def test_empty_dict_and_no_other_keys_still_clean() -> None:
    result = memory_promote_lesson_handler({"unrelated": "field"})
    assert result == "[ERROR] lesson_id is required"


# ---------------------------------------------------------------------------
# Legitimate-usage regression — mocked store (same pattern already
# established in tests/test_phase_gap6_memory_promote_lesson.py)
# ---------------------------------------------------------------------------


def test_delegates_to_the_store_on_success() -> None:
    fake_record = MagicMock(id=42)
    with patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_get_store.return_value.promote.return_value = fake_record
        result = memory_promote_lesson_handler({"lesson_id": "lesson-abc"})

    mock_get_store.return_value.promote.assert_called_once_with(
        "lesson-abc", agent_name="knowledge_curator"
    )
    assert "lesson-abc" in result
    assert "promoted" in result


def test_missing_draft_surfaces_as_a_real_clean_error() -> None:
    with patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_get_store.return_value.promote.side_effect = ValueError(
            "No draft version to promote for lesson_id='nope'"
        )
        result = memory_promote_lesson_handler({"lesson_id": "nope"})

    assert result.startswith("[ERROR]")
    assert "No draft version to promote" in result


def test_real_nonexistent_lesson_returns_clean_error_against_real_store() -> None:
    """Real, unmocked call against the real versioned_memory store —
    proves the whole path (not just the tool's own guard clauses)
    handles a genuinely nonexistent lesson_id cleanly."""
    result = memory_promote_lesson_handler(
        {"lesson_id": "definitely-not-a-real-lesson-id-xyz-123"}
    )
    assert result.startswith("[ERROR]")


# ---------------------------------------------------------------------------
# Backward-compatible re-export from app.agents.tools
# ---------------------------------------------------------------------------


def test_tools_module_reexports_same_handler_by_identity() -> None:
    from app.agents.tools import _MEMORY_PROMOTE_LESSON_TOOL

    assert memory_promote_lesson is memory_promote_lesson_handler
    assert _MEMORY_PROMOTE_LESSON_TOOL is MEMORY_PROMOTE_LESSON_TOOL


def test_knowledge_curator_imports_the_shared_handler() -> None:
    from app.agents import knowledge_curator as mod

    assert mod.memory_promote_lesson is memory_promote_lesson_handler
