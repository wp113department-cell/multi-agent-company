"""submit_sql_report tool — tool_enhance.md productionization pass,
tool #199 (2026-09-16).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_sql_report
Old path: app/agents/tools.py (`_SUBMIT_SQL_REPORT_TOOL` schema dict,
    `sq_submit` inside `make_sql_agent_handlers()` — the one real
    implementation).
New path: app/tools/agents/submit_sql_report.py (this file) —
    `SUBMIT_SQL_REPORT_TOOL`, `submit_sql_report_handler`.
Affected agents: exactly 1 per tool_inventory.json — `sql_agent`
    (`app/agents/sql_agent.py`). Deliberately NOT in `CHAT_TOOLS` —
    confirmed via `CHAT_TOOLS` membership check — same correct-and-
    intentional absence already established for sibling tools
    #66/#180-#186/#188-#192/#194/#196-#198.
Affected modules: app/agents/tools.py (`sq_submit` delegates to the
    shared handler; the local `sql_result` dict accumulator and
    `handlers["_sql_result"]` export are removed — see finding).
    `make_sql_agent_handlers()`'s other handlers (`run_sql`,
    `inspect_schema`, `find_sql`, `explain_query`, `edit_file`,
    `write_file`) are each their own separately-productionized concern
    (`inspect_schema`/`find_sql`/`explain_query` already GREEN_FLAGGED
    as tools #96/#91/#98; `run_sql`'s own `sq_run_sql` was explicitly
    noted as never accepting `params` and never exposed to tool #15's
    SQL-injection finding, deliberately left untouched there too) —
    deliberately untouched here, out of scope for this tool's turn.
Affected registries: none — app/fleet/tool_manifest.py's
    "submit_sql_report" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: `tests/test_day2_agents.py::TestSqlAgentHandlers`
    asserted directly on the now-removed `h["_sql_result"]` dict (an
    internal implementation detail, not real production behavior —
    see finding). Updated to assert on the handler's real return value
    instead, preserving the test's actual intent (verify a real
    submission succeeds) without relying on dead internal state. New
    tests added: see tests/test_submit_sql_report_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_sql_report.md.
---------------------------------------------------------------------------

Audit: no filesystem path, network destination, or subprocess/SQL
target anywhere in this tool's input schema (`action`, `result`,
`files_written` are all free-form strings/structured data — any real
SQL execution or file write already happened via the agent's own
separately gated `run_sql`/`write_file` handlers before this tool is
ever called) — no injection surface.

One real finding, same class and shape as sibling tools
#180-#186/#188-#192/#196-#198: **dead-code accumulator, never actually
read.** `sq_submit`'s original body did `sql_result.update(inp)`, and
the factory separately exported `handlers["_sql_result"] = sql_result`
— but grepping the entire production codebase found zero real
readers. The tool's real, functioning result-capture mechanism lives
entirely in `app/agents/base_graph.py`'s generic tool-execution node
(`tool_name.startswith("submit_")` → captures `dict(tu_input)`
directly into `state["result"]`), confirmed by reading
`sql_agent.py`'s own `raw = final_state["result"]` line, which is
what real production code actually consumes.

Fixed by removing the dead `sql_result` dict and `_sql_result` export
entirely — `submit_sql_report_handler()` now does exactly what the
real, functioning mechanism actually needs: return the same
confirmation string as before (`"SQL report submitted"`), with zero
behavior change to the tool's real end-to-end effect.
"""

from __future__ import annotations

from typing import Any

SUBMIT_SQL_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_sql_report",
    "description": "Submit SQL agent output: query results or migration summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "result": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "result"],
    },
}


def submit_sql_report_handler(inp: dict[str, Any]) -> str:
    """The real, functioning result-capture mechanism for this tool
    lives entirely in app.agents.base_graph.run_agent_graph's generic
    submit_* handling (reads the tool call's own arguments directly
    into state["result"]) — this handler's only real job is to return
    the confirmation text shown back to the LLM. `inp` is intentionally
    unused (kept in the signature to match the tool_handlers[name]
    calling convention every other handler in this codebase follows)."""
    return "SQL report submitted"
