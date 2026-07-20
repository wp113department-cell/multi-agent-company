"""Day 8 — Role Prompt verification.

The plan (docs/FLEET_ENHANCEMENT_PLAN.md, Day 8) originally asked for a 9-section
master template appended to every role file. That was superseded (2026-07-20,
commit b5778bb) by a DRY v2.0 design: a shared `_GLOBAL_STANDARDS.md` constitution
(loaded by `load_role()` and prepended to every agent's system prompt at runtime)
plus 7 role-specific sections per file. This test proves the v2.0 design is a real
superset of the original 9 sections — not just structurally, but by asserting the
actual verbatim/near-verbatim phrasing from the plan's 9 sections is present in
`_GLOBAL_STANDARDS.md` — and that every role file still carries its 7 required
role-specific sections. No prior test covered role-prompt structure at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.base import load_role

_ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
_GLOBAL_STANDARDS_PATH = _ROLES_DIR / "_GLOBAL_STANDARDS.md"

_ROLE_NAMES = sorted(
    p.stem for p in _ROLES_DIR.glob("*.md") if p.stem != "_GLOBAL_STANDARDS"
)

# The plan's original Day 8 9-section master template, expressed as the most
# distinctive substring from each section's required content (docs/FLEET_ENHANCEMENT_PLAN.md
# lines ~760-786). Verified once by manual diff against _GLOBAL_STANDARDS.md 2026-07-20;
# this test keeps that verification durable/automated.
_REQUIRED_GLOBAL_CONCEPTS: dict[str, str] = {
    "Understanding First": "user goal, hidden intent, expected output, constraints, priorities, risks",
    "Instruction Analysis": "split into objectives, map dependencies, list missing information",
    "Smart Planning": "task list, execution order, dependency graph, validation steps, rollback plan",
    "Context Use": "Never ignore active context",
    "Credential Safety": "route to config/env var",
    "Verification": "all requirements covered, output correct, tool results match claims",
    "Honest Errors": "Never hide failures or hallucinate success",
    "Self Review": "Did I solve the real problem? Did I miss anything? Is this production ready?",
    "Production Quality": "maintainability, observability, robustness, modularity, testing",
}

_REQUIRED_ROLE_SPECIFIC_SECTIONS = (
    "Non-Responsibilities",
    "Success Criteria",
    "Failure Conditions",
    "Output Contract",
    "Quality Gates",
    "Edge Cases",
    "Escalation",
)


def test_role_file_count_is_67() -> None:
    assert len(_ROLE_NAMES) == 67, (
        f"expected 67 role files (68 agent_models.json entries minus groq_adapter, "
        f"which has no role file), found {len(_ROLE_NAMES)}"
    )


def test_global_standards_file_exists() -> None:
    assert _GLOBAL_STANDARDS_PATH.exists()


@pytest.mark.parametrize("section_name,required_phrase", _REQUIRED_GLOBAL_CONCEPTS.items())
def test_global_standards_covers_original_9_sections(section_name: str, required_phrase: str) -> None:
    text = _GLOBAL_STANDARDS_PATH.read_text(encoding="utf-8")
    assert required_phrase in text, (
        f"_GLOBAL_STANDARDS.md is missing the plan's required '{section_name}' "
        f"content (expected phrase: {required_phrase!r})"
    )


@pytest.mark.parametrize("role_name", _ROLE_NAMES)
def test_role_file_has_all_role_specific_sections(role_name: str) -> None:
    text = (_ROLES_DIR / f"{role_name}.md").read_text(encoding="utf-8")
    missing = [s for s in _REQUIRED_ROLE_SPECIFIC_SECTIONS if s not in text]
    assert not missing, f"{role_name}.md missing role-specific sections: {missing}"


@pytest.mark.parametrize("role_name", _ROLE_NAMES)
def test_load_role_prepends_global_standards_at_runtime(role_name: str) -> None:
    """Functional check, not just static file presence: the composed system prompt
    actually delivered to the LLM (via load_role()) must contain both the global
    constitution and the role-specific content."""
    composed = load_role(role_name)
    assert "Global Agent Standards" in composed
    assert "Operating Loop" in composed
    for section in _REQUIRED_ROLE_SPECIFIC_SECTIONS:
        assert section in composed
