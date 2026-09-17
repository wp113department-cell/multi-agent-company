"""submit_changelog tool #236 — tool_enhance.md productionization pass
(2026-09-17).

Real finding: neither `submit_changelog_h` nor `run_changelog_agent`'s
own near-identical post-processing validated `sections` at all before
aggregating it. Proved live:

  {"sections": {"added": "not-a-number"}}  → uncaught TypeError from sum(sections.values())
  {"sections": ["not", "a", "dict"]}       → uncaught AttributeError from .values()

Fixed with one shared, defensive `_sum_section_counts()` helper used
by both call sites — non-dict `sections` becomes a safe empty dict,
and non-numeric per-section values are skipped rather than crashing
the whole aggregation.

Also confirmed via role-file/AGENT_CONTRACT reading: this agent's
`write_file` is intentionally NOT restricted to .md/docs/** (unlike
tools #231/#232) — AGENT_CONTRACT explicitly claims
permissions=["read_repo", "write_repo"] (not "write_docs"), and the
role file's Non-Responsibilities only excludes "editing code or
release artifacts" as a design guideline, never an absolute
file-system lockout. This agent's whole job is writing CHANGELOG.md
at whatever real path the project uses — no contradiction to fix here.
"""

from __future__ import annotations

from app.agents.changelog_agent import (
    _SUBMIT_CHANGELOG_TOOL,
    _sum_section_counts,
    make_changelog_handlers,
)
from app.agents.tools import CHAT_TOOLS


def test_schema() -> None:
    assert _SUBMIT_CHANGELOG_TOOL["name"] == "submit_changelog"
    assert _SUBMIT_CHANGELOG_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "version",
        "content",
    ]


def test_not_in_chat_tools() -> None:
    assert "submit_changelog" not in {t["name"] for t in CHAT_TOOLS}


# ---------------------------------------------------------------------------
# The real finding: malformed `sections` no longer crashes
# ---------------------------------------------------------------------------


def test_non_numeric_section_value_does_not_crash() -> None:
    handlers = make_changelog_handlers("/tmp")
    result = handlers["submit_changelog"](
        {"version": "1.0.0", "content": "x", "sections": {"added": "not-a-number"}}
    )
    assert "submitted" in result
    assert "0 entries" in result


def test_non_dict_sections_does_not_crash() -> None:
    handlers = make_changelog_handlers("/tmp")
    result = handlers["submit_changelog"](
        {"version": "1.0.0", "content": "x", "sections": ["not", "a", "dict"]}
    )
    assert "0 entries across 0 sections" in result


def test_sum_section_counts_direct_none_input() -> None:
    total, sections = _sum_section_counts(None)
    assert total == 0
    assert sections == {}


def test_sum_section_counts_direct_mixed_valid_and_invalid() -> None:
    total, sections = _sum_section_counts({"added": 3, "fixed": "2", "bad": "x"})
    assert total == 5  # 3 + int("2") = 5, "bad": "x" skipped
    assert sections == {"added": 3, "fixed": "2", "bad": "x"}


# ---------------------------------------------------------------------------
# Legitimate-usage regression — matches the pre-existing behavior exactly
# ---------------------------------------------------------------------------


def test_legitimate_well_formed_sections_still_counts_correctly() -> None:
    handlers = make_changelog_handlers("/tmp")
    result = handlers["submit_changelog"](
        {
            "version": "1.0.0",
            "content": "x",
            "sections": {"added": 3, "fixed": 2},
        }
    )
    assert "5 entries across 2 sections" in result


def test_write_file_is_intentionally_unrestricted_for_this_agent() -> None:
    """Unlike accessibility_agent/agentic_ai_architect, this agent's
    own contract (permissions=["read_repo", "write_repo"]) and role
    file legitimately expect broader write access — confirmed this is
    not the same finding class, not assumed."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        handlers = make_changelog_handlers(tmp)
        result = handlers["write_file"](
            {"path": "CHANGELOG.md", "content": "# Changelog\n"}
        )
        assert result.startswith("Written")
        assert (Path(tmp) / "CHANGELOG.md").read_text() == "# Changelog\n"
