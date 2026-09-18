# Tool #273 — `summarize_output` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`summarize_output` is a `CHAT_TOOLS`-only tool (confirmed: grepped
every agent's own `allowed_tools`, none reference it — interactive
chat is the only real consumer), previously living entirely inline in
`app/agents/tools.py`'s `make_chat_handlers()`: `_SUMMARIZE_OUTPUT_TOOL`
schema dict plus `summarize_output_h` closure. Condenses a long text
(e.g. a command/log/tool result) into an LLM-generated bullet-point
summary via `_llm_generate_text` (the same shared, circuit-breaker-
protected, never-raises one-shot LLM call used by `generate_commit_msg`
and sibling "generate X" tools).

## Problems found

Two real, empirically-verified findings — the same classes already
found and fixed on ~50 sibling tools this run:

1. **Malformed-input crash.** The original body did `text =
   str(inp["text"])` — direct dict indexing, not `.get()`.
   `input_schema` declares `"required": ["text"]`, but nothing
   enforces that at runtime for a malformed/schema-violating tool
   call. Proved live: `summarize_output_h({})` raised an uncaught
   `KeyError: 'text'`.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools #100/#103/.../#202/#203.** `summarize_output`
   is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s
   handlers dict, but `app/agents/chat_agent.py`'s `_execute_tool()`
   had NO dispatch branch for it — grepped and confirmed absent.
   Proved live: a real dispatch attempt via `ChatAgent._execute_tool`
   fell through to `"[ERROR] Unknown tool: summarize_output"` before
   the fix.

## Changes made

Extracted the shared logic into a new module,
`app/tools/filesystem/summarize_output.py` (`SUMMARIZE_OUTPUT_TOOL`,
`summarize_output_handler`), matching this codebase's established
migration precedent for this exact finding class (e.g.
`summarize_repo`, `generate_diagram`, `export_markdown`). The new
handler coerces `text` via `.get("text", "")` (closing finding #1) and
is now the single source of truth for both call sites:
- `app/agents/tools.py`'s `summarize_output_h` now delegates to it.
- `app/agents/chat_agent.py` gained a real dispatch branch delegating
  to the same shared handler (closing finding #2).

All other behavior — LLM-generated 3-8 bullet-point summarization,
optional `focus` field, graceful degradation to a truncated excerpt on
LLM failure — preserved verbatim.

Verified live, post-fix:
- `summarize_output_handler({})` → `"(nothing to summarize — empty
  text)"` — no crash.
- `make_chat_handlers("/tmp")["summarize_output"]({})` → same clean
  result, no crash.
- `ChatAgent._execute_tool("summarize_output", {"text": "error: file
  not found at line 42"})` → a real, genuine LLM-generated summary
  (`"• Error occurred at line 42 of a file\n• ..."`) — the dispatch
  gap is closed, and a real API key in this environment let the actual
  LLM call succeed end to end.

`ruff check` and `mypy` clean on all three touched/new files. Both
`app.agents.chat_agent` and `app.agents.tools` still import cleanly.
Confirmed `_llm_generate_text` still has 5 other real callers in
`tools.py` (no dead code introduced by the extraction).

## Tests

Existing tests (`test_audit_q_batch14_extensibility_enterprise.py`,
filtered to `summarize_output`): 4 tests, all still pass unchanged.

New file `tests/test_summarize_output_hardening.py`, 11 tests: schema
check, `CHAT_TOOLS` single-membership check, the
malformed-input-never-crashes proof across all 3 real access paths
(direct handler, `make_chat_handlers`, `ChatAgent._execute_tool`), a
whitespace-only-text rejection regression, the
dispatch-no-longer-unknown-tool proof (finding #2), a `focus`-field
regression, an LLM-failure-fallback regression, and delegation
regressions for both call sites.

## Regression

This tool's own new hardening tests (11/11 pass) plus the existing
summarize_output tests (4) + `test_new_tools.py` +
`test_day2_tools.py` + `test_summarize_repo_hardening.py` — 172
passed, 4 failed. The 4 failures
(`test_audit_q_batch14_extensibility_enterprise.py`'s repo-scoping and
credential-vault tests) are the same pre-existing
`ConnectionRefusedError` on `127.0.0.1:5432` environmental issue
already documented on tools #259/#264/#265/#267/#272 (no local
Postgres running) — unrelated to this fix.

## Final verdict

**GREEN FLAG.** Two real findings (malformed-input crash, missing
interactive-chat dispatch) found and fixed, matching this codebase's
established modularization and hardening precedent for this exact
class. Fix verified live end to end through the real `ChatAgent`
dispatch path. Zero functionality lost. Agent alignment verified:
PASS.
