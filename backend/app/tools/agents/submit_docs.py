"""submit_docs tool — tool_enhance.md productionization pass, tool #85
(2026-08-24).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: submit_docs
Old path: app/agents/tools.py (`_SUBMIT_DOCS_TOOL` schema dict) with
    FOUR real implementations, all functionally identical (`inp` is
    stored into a per-call `docs_result` dict, a confirmation string is
    returned), differing only in cosmetic return-message wording:
    `dg_submit` (`make_doc_generator_handlers`), `submit_docs` (inside
    `make_docs_handlers`), `rm_submit` (`make_readme_agent_handlers`),
    `ad_submit` (`make_api_docs_agent_handlers`).
New path: app/tools/agents/submit_docs.py (this file) —
    `SUBMIT_DOCS_TOOL`, `make_submit_docs_handler`. ALL FOUR real call
    sites now delegate to this one shared handler factory.
Affected agents: per tool_inventory.json, 8 agents declare
    `submit_docs` in `allowed_tools`. `app/agents/architecture_doc_
    agent.py` reuses `make_docs_handlers()`'s own `submit_docs` entry
    directly (`handlers["submit_docs"] = doc_handlers["submit_docs"]`)
    rather than defining a fifth implementation — confirmed by reading
    it, not assumed.
Affected modules: app/agents/tools.py (all four closures now delegate
    to the shared handler factory).
Affected registries: none — app/fleet/tool_manifest.py's "submit_docs"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path. Not in `CHAT_TOOLS` at all (confirmed) — this is a
    batch-agent final-answer tool, never exposed to the interactive
    chat session, so `app/agents/chat_agent.py` has no dispatch branch
    for it (correctly — not a bug, matches its own documented purpose).
Affected tests: none required changes — every existing real test
    accesses this tool via one of the four handler factories (or
    `architecture_doc_agent.py`'s reuse of `make_docs_handlers()`).
    New tests added: see tests/test_submit_docs_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/submit_docs.md.
---------------------------------------------------------------------------

No security vulnerability and no functional bug found. This is a pure
in-memory result sink: `docs_result.update(inp)` stores the LLM's
self-reported summary of what it wrote, then a confirmation string is
returned — no file I/O, no subprocess, no path handling, and each real
caller's `docs_result` dict is freshly created per `make_*_handlers()`
invocation (verified: no cross-session or cross-agent leakage is
possible). Traced the real downstream consumer
(`app/agents/docs.py::run_docs_agent`, `handlers.get("_docs_result",
{})`) to confirm `files_written`/`summary` only ever populate a
`DocsReport` dataclass used for reporting — never re-opened, executed,
or trusted as a path to act on. `DocsReport.files_written` itself was
also checked and confirmed to have no other real consumer anywhere in
`app/` — a pure, harmlessly-unused report field, not a defect worth
fixing (removing it would be a functionality change with no reported
problem to justify it).

Unified purely for consistency and to eliminate duplicate code: the
four implementations differed only in cosmetic return-message text
("Docs submitted" / "Docs report submitted" / "Docs submitted" /
"API docs submitted"), which no existing test asserts on (verified —
every real test checks `_docs_result`'s stored dict contents, never
the returned string). Standardized on one clear message for all four.
"""

from __future__ import annotations

from typing import Any, Callable

SUBMIT_DOCS_TOOL = {
    "name": "submit_docs",
    "description": "Submit the list of documentation files written or updated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "files_written": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths of markdown files created or updated",
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of documentation changes",
            },
        },
        "required": ["files_written", "summary"],
    },
}


def make_submit_docs_handler(
    docs_result: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    """Core submit_docs logic shared by all four real call sites.

    `docs_result` is the per-agent-instance dict each factory already
    creates and exposes as `handlers["_docs_result"]` — this function
    does not own or create that dict, matching the existing contract
    every real downstream consumer (`app/agents/docs.py`) relies on.
    """

    def submit_docs_handler(inp: dict[str, Any]) -> str:
        docs_result.update(inp)
        return "Docs submitted"

    return submit_docs_handler
