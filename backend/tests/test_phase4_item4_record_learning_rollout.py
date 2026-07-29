"""Tests for MASTER_AGENT_v2.md Phase 4 Item 4 — "does it benefit from and
contribute to fleet memory?" (record_learning) for the 31 agents Step 1/1.4's
original 38-agent rollout didn't reach (32 candidates found by grep, minus
`executive`, which genuinely takes zero tools by architecture — a single
LLM call with tools=[] — and can't be given one without a structural change
out of this item's scope).

Unlike test_record_learning_rollout.py's 25 Tier-B agents (all sharing one
uniform `_TOOLS`/`make_{name}_handlers` naming convention), these 31 agents
have real per-agent variation: some tool lists live in the agent's own file
(`_CHANGELOG_TOOLS`), some centrally in tools.py (`AI_ENGINEER_TOOLS`), some
split into SCAN_TOOLS/APPLY_TOOLS phases, and handler factory names vary
too. So this file discovers each agent's real tools=/handlers= call site
from its own source (same signal the rollout script used), rather than
assuming a naming convention that doesn't hold here.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO = str(Path(__file__).parent.parent.parent)

AGENTS = [
    "agent_advisor",
    "agent_debugger",
    "agent_performance_reviewer",
    "ai_engineer",
    "api_docs_agent",
    "architecture_reviewer",
    "business_analyst",
    "changelog_agent",
    "cicd_agent",
    "cleanup_agent",
    "database_architect",
    "dependency_agent",
    "docker_agent",
    "evaluation_agent",
    "knowledge_curator",
    "migration_agent",
    "monitoring_agent",
    "performance_reviewer",
    "quality_auditor",
    "rag_engineer_agent",
    "readme_agent",
    "refactor_agent",
    "release_notes_agent",
    "schema_agent",
    "security_architect",
    "security_reviewer",
    "sprint_planner",
    "sql_agent",
    "style_reviewer",
    "tech_debt_agent",
    "user_story_generator",
]


def _real_tools_lists(module_name: str) -> list[list[dict[str, Any]]]:
    """Every distinct `tools=<expr>` passed to a real run_agent_graph call in
    this agent's own file (excludes the unrelated AGENT_CONTRACT["allowed_tools"]
    usage inside _register())."""
    src = Path(f"app/agents/{module_name}.py").read_text(encoding="utf-8")
    mod = importlib.import_module(f"app.agents.{module_name}")
    names = re.findall(r"tools=([A-Za-z_][A-Za-z0-9_]*(?:\s*\+\s*\[[^\]]*\])?),", src)
    lists = []
    for expr in names:
        if "AGENT_CONTRACT" in expr:
            continue
        lists.append(eval(expr, vars(mod)))  # noqa: S307 - controlled, repo-local exprs
    return lists


@pytest.mark.parametrize("module_name", AGENTS)
def test_record_learning_declared_in_contract(module_name: str) -> None:
    mod = importlib.import_module(f"app.agents.{module_name}")
    assert (
        "record_learning" in mod.AGENT_CONTRACT["allowed_tools"]
    ), f"{module_name}: record_learning missing from AGENT_CONTRACT['allowed_tools']"


@pytest.mark.parametrize("module_name", AGENTS)
def test_record_learning_present_in_every_real_tools_schema(module_name: str) -> None:
    tool_lists = _real_tools_lists(module_name)
    assert tool_lists, f"{module_name}: no real tools= call site found"
    for tools in tool_lists:
        names = {t["name"] for t in tools}
        assert "record_learning" in names, (
            f"{module_name}: record_learning declared in contract but missing "
            f"from a real tools= list ({sorted(names)})"
        )


@pytest.mark.parametrize("module_name", AGENTS)
def test_record_learning_handler_wired_with_correct_agent_attribution(
    module_name: str,
) -> None:
    """Source-level check that make_record_learning_handler is actually
    called with THIS agent's own name (not copy-pasted from another agent,
    the exact attribution bug this tool exists to avoid), and that its
    result is assigned to the real handlers dict key the graph looks up.
    Not a dynamic call-the-factory check: several of these agents wire
    record_learning in the calling run_<agent>() function's own body, after
    a shared/central factory call returns, not inside the factory itself —
    calling the factory in isolation would miss that follow-up statement,
    so source inspection is the accurate signal here, not execution."""
    src = Path(f"app/agents/{module_name}.py").read_text(encoding="utf-8")
    # black may line-wrap a long call, so match across whitespace/newlines
    # rather than requiring one exact single-line string.
    pattern = (
        r'handlers\["record_learning"\]\s*=\s*make_record_learning_handler\(\s*'
        rf'"{re.escape(module_name)}"'
    )
    assert re.search(pattern, src), (
        f"{module_name}: no handlers['record_learning'] = "
        f"make_record_learning_handler({module_name!r}) call found — either "
        f"missing entirely or attributed to the wrong agent name"
    )


def test_record_learning_handler_itself_is_real_and_callable() -> None:
    """One real, dynamic proof that make_record_learning_handler produces a
    genuinely working callable with correct attribution — the mechanism
    every one of the 31 source-level checks above relies on being real."""
    from app.agents.tools import make_record_learning_handler

    handler = make_record_learning_handler("some_agent")
    assert callable(handler)
    with patch(
        "app.memory.store.embed_learning_signal_sync", return_value=True
    ) as mock_sync:
        result = handler({"finding": "a non-obvious finding"})
    assert result == "Recorded."
    mock_sync.assert_called_once_with(
        agent_name="some_agent",
        description="a non-obvious finding",
        outcome_summary="recorded during task execution",
    )


def test_all_31_agents_are_covered() -> None:
    """Documents the exact count so a future omission is visible, not silent."""
    assert len(AGENTS) == 31


def test_executive_is_a_confirmed_deliberate_exception_not_an_oversight() -> None:
    """executive.py uses tools=[] by architecture (a single LLM call, no tool
    use at all) — confirmed here so this exclusion can't silently rot into a
    real gap if that architecture ever changes."""
    src = Path("app/agents/executive.py").read_text(encoding="utf-8")
    assert "tools=[]" in src.replace(" ", "")
