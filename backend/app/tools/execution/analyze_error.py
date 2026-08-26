"""analyze_error tool — tool_enhance.md productionization pass, tool
#121 (2026-08-26).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: analyze_error
Old path: app/agents/tools.py (`_ANALYZE_ERROR_TOOL` schema dict) with
    THREE real implementations: `bf_analyze_error`
    (`make_bug_fix_handlers` — see the severe finding below),
    `analyze_error` (inside `make_chat_handlers()`) +
    `app/agents/chat_agent.py`'s own interactive dispatch (a
    near-identical copy of `make_chat_handlers()`'s own logic).
New path: app/tools/execution/analyze_error.py (this file) —
    `ANALYZE_ERROR_TOOL`, `analyze_error_handler`. ALL THREE real call
    sites now delegate to this one shared handler.
Affected agents: per tool_inventory.json, agents declaring
    `analyze_error` in `allowed_tools` (plus interactive chat).
Affected modules: app/agents/tools.py (both of its own closures
    delegate to the shared handler — `bf_analyze_error` is fully
    replaced, see finding below), app/agents/chat_agent.py (its
    dispatch now calls the same shared handler).
Affected registries: none — app/fleet/tool_manifest.py's
    "analyze_error" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes. New tests added: see
    tests/test_analyze_error_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/analyze_error.md.
---------------------------------------------------------------------------

One real, empirically-verified, severe finding — a field-name mismatch
causing a 100% functional-failure rate, same class as tool #111's
`find_function_body`: `bf_analyze_error` read `inp.get("traceback",
"")`, but the tool's own schema requires (and every real caller sends)
`error`, never `traceback`. Since the dict key never matches, `.get()`
always silently falls back to its `""` default — proved live: a
genuine, well-formed traceback passed as `{"error": "..."}` produced
`"(no error markers found)"` every single time, completely ignoring
the real input. `analyze_error` (`make_chat_handlers`) and
`chat_agent.py`'s dispatch both already read `inp["error"]` correctly
and implement the tool's full documented contract ("structured
breakdown with suggestions") — `bf_analyze_error`'s simplistic
grep-for-keyword-lines stub never matched that contract even before
accounting for the field-name bug.

Fixed by full replacement: the shared `analyze_error_handler()` is the
correct, already-working logic from `make_chat_handlers()`/
`chat_agent.py` (structured exception-line extraction, stack-frame
extraction with library-frame filtering, and heuristic suggestions
keyed on the exception type) — `bf_analyze_error`'s broken stub is
fully replaced rather than patched to merely read the right field,
since even a field-name fix would leave it a capability regression
relative to its two siblings.
"""

from __future__ import annotations

from typing import Any


def analyze_error_handler(inp: dict[str, Any]) -> str:
    """Core analyze_error logic shared by all three real call sites."""
    ae_error = str(inp["error"])
    ae_lines = ae_error.strip().splitlines()
    exception_line = ""
    for ae_line in reversed(ae_lines):
        if any(
            x in ae_line for x in ("Error:", "Exception:", "Warning:", "Traceback")
        ):
            exception_line = ae_line
            break
    frames: list[str] = []
    ae_i = 0
    while ae_i < len(ae_lines):
        ae_line = ae_lines[ae_i]
        if ae_line.strip().startswith("File ") and "line " in ae_line:
            if not any(x in ae_line for x in ("site-packages", ".venv", "lib/python")):
                code_line = (
                    ae_lines[ae_i + 1].strip() if ae_i + 1 < len(ae_lines) else ""
                )
                frames.append(f"  {ae_line.strip()}\n    → {code_line}")
            ae_i += 2
        else:
            ae_i += 1
    ae_result = ["=== Error Analysis ==="]
    if exception_line:
        ae_result.append(f"Exception: {exception_line.strip()}")
    if frames:
        ae_result.append(f"\nRelevant frames ({len(frames)}):")
        ae_result.extend(frames[-5:])
    ae_low = ae_error.lower()
    suggestions: list[str] = []
    if "modulenotfounderror" in ae_low or "importerror" in ae_low:
        suggestions.append("→ Missing dependency — run: pip install -r requirements.txt")
    elif "attributeerror" in ae_low:
        suggestions.append(
            "→ Object doesn't have this attribute — check spelling and type"
        )
    elif "typeerror" in ae_low:
        suggestions.append("→ Wrong argument type/count — check function signature")
    elif "keyerror" in ae_low:
        suggestions.append("→ Dictionary key not found — use .get() or check key exists")
    elif "filenotfounderror" in ae_low:
        suggestions.append("→ Path doesn't exist — verify path and working directory")
    elif "connectionrefusederror" in ae_low or "connection refused" in ae_low:
        suggestions.append(
            "→ Service not running — check if DB/Redis/backend is started"
        )
    elif "syntaxerror" in ae_low:
        suggestions.append("→ Python syntax error — check brackets, colons, indentation")
    elif "valueerror" in ae_low:
        suggestions.append("→ Invalid value — validate input before passing it")
    if suggestions:
        ae_result.append("\nSuggestions:")
        ae_result.extend(suggestions)
    return "\n".join(ae_result)


ANALYZE_ERROR_TOOL: dict[str, Any] = {
    "name": "analyze_error",
    "description": "Parse and analyze a Python traceback or error message. Returns structured breakdown with suggestions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "error": {
                "type": "string",
                "description": "Error message or full traceback to analyze",
            },
        },
        "required": ["error"],
    },
}
