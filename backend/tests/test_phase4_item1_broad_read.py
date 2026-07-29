"""Tests for MASTER_AGENT_v2.md Phase 4 Item 1 — "can it read broadly?"

Audit method: checked each candidate agent's REAL primary tool list (the
exact list its run_<agent>() passes to run_agent_graph's tools= — not just
whichever "*_TOOLS"-suffixed variable happened to exist, which produces
false positives when an agent has separate SCAN/APPLY phase lists) for
search_code/get_file_tree/find_references, the 3 tools Phase 4's own text
names. Of the original 12 candidates flagged by a cruder grep, only
`research` was a real gap — the rest either already had these tools via
`READ_ONLY_TOOLS + [...]` inheritance (a literal-string grep for
"find_references" produces a false negative for agents that inherit it via
the shared list object rather than spelling out the name), or have a
deliberately curated, evidence-backed narrow scope (`executive`: no code
interaction by role design; `agent_advisor`/`agent_debugger`/
`agent_performance_reviewer`: narrow audit-diagnosis SCAN tools by design;
`knowledge_curator`: curates memory rows, not code; `quality_auditor`: a
deliberately curated security-pattern-scanning whitelist).
"""

from __future__ import annotations

from app.agents.tools import RESEARCH_TOOLS, make_research_handlers


def test_research_tools_now_includes_get_file_tree_and_find_references() -> None:
    names = {t["name"] for t in RESEARCH_TOOLS}
    assert "get_file_tree" in names
    assert "find_references" in names
    # Kept minimal (TPM-budget comment above the list) — not the whole bundle.
    assert "search_symbols" not in names
    assert "git_log" not in names


def test_research_handlers_actually_implement_both_new_tools() -> None:
    """Not just declared in the schema — a real, callable handler exists for
    each, confirming this was a dead-contract-style schema gap (handler
    already wired via make_read_only_handlers), not a missing capability."""
    handlers = make_research_handlers(".")
    assert callable(handlers.get("get_file_tree"))
    assert callable(handlers.get("find_references"))


def test_all_research_tools_schema_names_have_real_handlers() -> None:
    handlers = make_research_handlers(".")
    for tool in RESEARCH_TOOLS:
        name = tool["name"]
        if name == "record_learning":
            continue  # wired separately per-agent-name at run_research() call time
        assert (
            name in handlers
        ), f"{name} declared in RESEARCH_TOOLS but no handler wired"
