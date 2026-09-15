"""record_preference tool — tool_enhance.md productionization pass,
tool #178 (2026-09-15).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: record_preference
Old path: app/agents/tools.py (`RECORD_PREFERENCE_TOOL` schema dict
    and `make_record_preference_handler()` factory — the one real
    call site, inside `make_chat_handlers()`).
New path: app/tools/agents/record_preference.py (this file) — same
    names, moved verbatim.
Affected agents: `record_preference` is CHAT_TOOLS-only (confirmed:
    the ONLY real caller of `make_record_preference_handler()` is
    `make_chat_handlers()` itself — unlike sibling tool #66's
    `record_learning`, which ~80 one-shot agents call directly, no
    other agent module references this factory at all). Interactive
    chat gains a real dispatch it never had — see finding.
Affected modules: app/agents/tools.py (re-exports both names for its
    own `make_chat_handlers()` call site), app/agents/chat_agent.py
    (gains a real dispatch branch it never had).
Affected registries: none — app/fleet/tool_manifest.py's
    "record_preference" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — every existing real test
    accesses this tool via `make_record_preference_handler(...)`. New
    tests added: see tests/test_record_preference_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/record_preference.md.
---------------------------------------------------------------------------

Audited for the finding classes established this initiative (shell
injection, flag/program injection, worktree-boundary escape,
unbounded timeout, advertised-but-not-dispatched) — same audit shape
as sibling tool #66's `record_learning`. `preference`/`scope` reach
`embed_preference_sync()` as plain string content, inserted through
the ORM (`MemoryEmbedding`), never string-interpolated into raw SQL or
a shell command; there is no filesystem path or network destination
anywhere in this tool's input schema, so there is no worktree-escape
or SSRF surface. Proved live: a real `preference` was genuinely
persisted (`"Recorded."`) and an empty `preference` was cleanly
rejected (`"[ERROR] preference is required."`), both against the real
DB. The sync/async bridge (`embed_preference_sync` in
`app/memory/store.py`) already uses `new_isolated_async_engine()` +
its own `asyncio.run()`, matching this initiative's own established
"never `asyncio.run()` against the shared `app.db.session` engine
from sync code" rule — already correct, not a violation.

One real finding: **advertised but never dispatched on the
interactive chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#176/#177.**
`record_preference` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: record_preference"`. This is a real functional gap —
`record_preference`'s own module docstring in `tools.py` explicitly
states chat is "the direct human-facing conversational surface where
a preference is naturally stated," so the tool has never actually
been reachable from the one surface it was designed for.

Fixed via a new `chat_agent.py` dispatch branch delegating to this
shared `make_record_preference_handler()`.
"""

from __future__ import annotations

from typing import Any, Callable

RECORD_PREFERENCE_TOOL: dict[str, Any] = {
    "name": "record_preference",
    "description": (
        "Record a stated human preference (coding style, naming convention, "
        "testing approach, tooling choice, workflow) so future work in this "
        "project applies it without being re-told. Use this only for a real "
        "preference the user actually expressed, not an inferred guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "preference": {
                "type": "string",
                "description": "The preference itself, in the user's own terms.",
            },
            "scope": {
                "type": "string",
                "description": "Short label for what this preference governs, e.g. "
                "'style', 'naming', 'testing', 'tooling', 'workflow'.",
            },
        },
        "required": ["preference"],
    },
}


def make_record_preference_handler(
    task_id: str = "chat",
) -> Callable[[dict[str, Any]], str]:
    """Build the sync tool handler for record_preference. task_id defaults
    to a synthetic "chat" marker (mirrors record_learning's "fleet-{agent}"
    synthetic task_id convention) since a stated preference isn't tied to
    one specific DevTask."""

    def _handler(inp: dict[str, Any]) -> str:
        preference = str(inp.get("preference", "")).strip()
        if not preference:
            return "[ERROR] preference is required."
        scope = str(inp.get("scope", "")).strip() or "general"

        from app.memory.store import embed_preference_sync

        stored = embed_preference_sync(
            task_id=task_id, preference=preference, scope=scope
        )
        return "Recorded." if stored else "[ERROR] failed to record preference."

    return _handler
