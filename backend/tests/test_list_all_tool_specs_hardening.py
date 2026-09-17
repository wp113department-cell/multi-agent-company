"""list_all_tool_specs tool #219 — tool_enhance.md productionization
pass (2026-09-17).

Real finding: this function's own description claims "Real
introspection of every distinct tool schema defined in this codebase
... not a guess" — but the implementation only ever scanned
`app.agents.tools`, its own module. Proved live via a direct set-
difference check before the fix: 2 real tool schemas were completely
invisible to it —

  - `submit_fix` (tool #214's shared schema/handler, unified across 4
    agent files but never re-exported into app.agents.tools, unlike
    every other similarly-unified submit_* tool)
  - `score_tech_options` (tech_advisor_agent.py-local, pre-existing,
    unrelated to any change made in this initiative)

Both are exactly the kind of thing this tool exists to surface: its
sole real caller, `tool_catalog_doc_agent`, uses this output as the
"real, complete, deduplicated" source of truth for writing the tool
catalog doc — silently missing real tools there is a genuine
functional defect matching this initiative's evidence-based standard,
not a hypothetical edge case.

Fixed by also scanning every other module directly under app/agents/
for the same tool-schema shape (module-level dict or list containing
dicts with "name" + "input_schema" keys) — closes the root cause so
any future agent-local-only tool schema is covered automatically,
rather than special-casing just these 2 known instances.
"""

from __future__ import annotations

import json

from app.agents.tools import CHAT_TOOLS, list_all_tool_specs


def test_not_in_chat_tools() -> None:
    assert "list_all_tool_specs" not in {t["name"] for t in CHAT_TOOLS}


def test_still_deduplicated_and_includes_pre_existing_tools() -> None:
    data = json.loads(list_all_tool_specs({}))
    names = [t["name"] for t in data]
    assert len(names) == len(set(names))
    assert "write_file" in names
    assert "list_registered_agents" in names


# ---------------------------------------------------------------------------
# The real finding: agent-local-only tool schemas are no longer invisible
# ---------------------------------------------------------------------------


def test_submit_fix_is_now_discovered() -> None:
    """submit_fix (tool #214) is a real, shared tool used by 4 real
    agents (agent_performance_reviewer, knowledge_curator,
    agent_debugger, quality_auditor) but was never re-exported into
    app.agents.tools — previously invisible to this introspection tool."""
    data = json.loads(list_all_tool_specs({}))
    names = {t["name"] for t in data}
    assert "submit_fix" in names


def test_score_tech_options_is_now_discovered() -> None:
    """score_tech_options (tech_advisor_agent.py-local) — a real,
    pre-existing tool, unrelated to any change made in this
    initiative, that was also silently invisible before this fix."""
    data = json.loads(list_all_tool_specs({}))
    names = {t["name"] for t in data}
    assert "score_tech_options" in names


def test_result_grew_after_scanning_all_agent_modules() -> None:
    """Sanity check that the fix genuinely broadened coverage, not just
    the 2 specifically-named cases above — many other agent-local
    schemas exist across app/agents/*.py that were equally invisible
    before."""
    data = json.loads(list_all_tool_specs({}))
    assert len(data) > 250


def test_tool_catalog_doc_agent_still_wires_the_same_function() -> None:
    from app.agents.tool_catalog_doc_agent import make_tool_catalog_doc_handlers

    handlers = make_tool_catalog_doc_handlers("/tmp")
    assert handlers["list_all_tool_specs"] is list_all_tool_specs
