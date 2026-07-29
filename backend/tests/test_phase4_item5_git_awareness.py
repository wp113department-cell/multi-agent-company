"""Tests for MASTER_AGENT_v2.md Phase 4 Item 5 — "does it have real workspace
awareness (git) where relevant?"

Audit method: checked each agent's REAL constructed tool lists (every
list-valued module attribute, since git tools are usually inherited via
`READ_ONLY_TOOLS + [...]` rather than spelled out literally — a naive grep
for '"git_log"' etc. in the agent's own file produces false negatives here,
the same blind spot already found and corrected for find_references and
record_learning earlier in this Phase 4 pass). Real finding: only 2 of 70
agents have zero git tools, and both are confirmed legitimate exceptions,
not gaps — everyone else already has real git awareness (mostly via
READ_ONLY_TOOLS inheritance, which includes git_log/git_status/git_show/
git_blame).
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_EXCLUDE = {
    "__init__.py",
    "base.py",
    "base_graph.py",
    "agent_result.py",
    "groq_adapter.py",
    "tools.py",
    "chat_agent.py",
    "manager.py",
}


def _all_agent_module_names() -> list[str]:
    names = []
    for f in sorted(pathlib.Path("app/agents").glob("*.py")):
        if f.name in _EXCLUDE:
            continue
        if "AGENT_CONTRACT" not in f.read_text(encoding="utf-8"):
            continue
        names.append(f.stem)
    return names


def _has_any_git_tool(module_name: str) -> bool:
    mod = importlib.import_module(f"app.agents.{module_name}")
    for attr in dir(mod):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            for t in val:
                if isinstance(t, dict) and str(t.get("name", "")).startswith("git_"):
                    return True
    return False


def test_only_two_agents_lack_git_tools_and_both_are_confirmed_exceptions() -> None:
    no_git = [n for n in _all_agent_module_names() if not _has_any_git_tool(n)]
    assert set(no_git) == {"executive", "research"}, (
        f"git-tool coverage changed: {no_git} — if this is a NEW agent lacking "
        f"git tools, judge whether its role genuinely needs them (don't just "
        f"update this set)"
    )


def test_executive_exception_is_the_confirmed_zero_tools_architecture() -> None:
    src = pathlib.Path("app/agents/executive.py").read_text(encoding="utf-8")
    assert "tools=[]" in src.replace(" ", "")


def test_research_exception_is_a_documented_deliberate_minimal_toolset() -> None:
    """research.py's own comment explains the minimal toolset is a deliberate
    TPM-budget choice (Phase 4 Item 1 gap-closure earlier already added
    get_file_tree/find_references to it for the same reason it's tested
    here); its role file doesn't explicitly promise git-history analysis the
    way version_manager_agent's does, so this stays a legitimate exception."""
    src = pathlib.Path("app/agents/tools.py").read_text(encoding="utf-8")
    assert "Kept small to stay within free-tier TPM limits" in src


@pytest.mark.parametrize(
    "module_name,expected_tools",
    [("version_manager_agent", {"git_log", "git_blame"})],
)
def test_version_history_dependent_agent_has_real_git_tools(
    module_name: str, expected_tools: set[str]
) -> None:
    """version_manager_agent's own role file explicitly promises 'the
    correct semantic version bump from actual git history and diffs' — a
    real, checkable claim this test holds it to."""
    mod = importlib.import_module(f"app.agents.{module_name}")
    names: set[str] = set()
    for attr in dir(mod):
        val = getattr(mod, attr, None)
        if isinstance(val, list):
            for t in val:
                if isinstance(t, dict):
                    names.add(t.get("name", ""))
    assert expected_tools <= names
