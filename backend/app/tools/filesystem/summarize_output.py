"""summarize_output tool — tool_enhance.md productionization pass, tool
#273 (2026-09-18).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: summarize_output
Old path: app/agents/tools.py (`_SUMMARIZE_OUTPUT_TOOL` schema dict,
    `summarize_output_h` inside `make_chat_handlers()` — the one real
    implementation).
New path: app/tools/filesystem/summarize_output.py (this file) —
    `SUMMARIZE_OUTPUT_TOOL`, `summarize_output_handler`.
Affected agents: exclusively a `CHAT_TOOLS` entry (confirmed: grepped
    all agent files' own `allowed_tools`, none reference
    `"summarize_output"` — interactive chat is the only real consumer).
Affected modules: app/agents/tools.py (`summarize_output_h` delegates
    to the shared handler), app/agents/chat_agent.py (gains a real
    dispatch branch it never had — see finding #2).
Affected registries: none — app/fleet/tool_manifest.py's
    "summarize_output" ToolManifestEntry is pure metadata, keyed by
    tool NAME not file path.
Affected tests: none required changes — no existing test called this
    handler with a missing `text` key. New tests added: see
    tests/test_summarize_output_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/summarize_output.md.
---------------------------------------------------------------------------

Two real, empirically-verified findings, same classes already found and
fixed on ~25 sibling tools this run:

1. **Malformed-input crash.** The original body did
   `text = str(inp["text"])` — direct dict indexing, not `.get()`.
   `input_schema` declares `"required": ["text"]`, but nothing
   enforces that at runtime for a malformed/schema-violating tool
   call. Proved live: `summarize_output_h({})` raised an uncaught
   `KeyError: 'text'`.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#176/#177/#178/#202/#203.**
   `summarize_output` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: summarize_output"`.

Fixed via a shared `summarize_output_handler(inp)`: coerces `text` via
`.get("text", "")` so a missing/malformed key never crashes, closing
finding #1. A new, real `chat_agent.py` dispatch delegates to this same
shared handler, closing finding #2. All other behavior (LLM-generated
bullet-point summarization via `_llm_generate_text`, optional `focus`
field, graceful degradation to a truncated excerpt on LLM failure)
preserved verbatim.
"""

from __future__ import annotations

from typing import Any

SUMMARIZE_OUTPUT_TOOL: dict[str, Any] = {
    "name": "summarize_output",
    "description": (
        "Condense a long piece of text (e.g. a command/log/tool result you just "
        "received) into a short LLM-generated summary — real summarization, "
        "distinct from just truncating the text. Use this instead of pasting a "
        "huge result verbatim into your own next message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The long text to summarize",
            },
            "focus": {
                "type": "string",
                "description": "Optional: what to focus the summary on (e.g. 'errors only', 'files changed')",
            },
        },
        "required": ["text"],
    },
}


def summarize_output_handler(inp: dict[str, Any]) -> str:
    """Core summarize_output logic. `inp.get("text", "")` is
    deliberately coerced rather than indexed with `inp["text"]` — see
    this module's docstring (finding #1) for why a missing/malformed
    `text` field must never crash the tool call."""
    from app.agents.tools import _llm_generate_text

    text = str(inp.get("text", ""))
    focus = str(inp.get("focus", "")).strip()
    if not text.strip():
        return "(nothing to summarize — empty text)"

    focus_line = f" Focus specifically on: {focus}." if focus else ""
    prompt = (
        "Summarize the following text concisely, in 3-8 concrete bullet "
        "points. Preserve specifics (file paths, error messages, numbers, "
        f"conclusions) — do not write vague generalities.{focus_line}\n\n"
        f"Text to summarize:\n{text[:20000]}"
    )
    summary = _llm_generate_text(prompt, max_tokens=500)
    if not summary:
        return (
            "[summarization unavailable — LLM call failed] "
            f"Original text was {len(text)} chars; here is a truncated excerpt:\n"
            f"{text[:2000]}"
        )
    return summary
