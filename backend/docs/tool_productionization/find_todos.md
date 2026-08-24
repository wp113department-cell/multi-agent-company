# Tool #77 — `find_todos` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()`'s ~35
   one-shot agents.
2. `chat_agent.py`'s own interactive dispatch — a separate, slightly
   less complete inline copy.
3. `sr_find_todos` (style_reviewer agent), `cu_find_todos`
   (cleanup_agent), `td_find_todos` (tech_debt_agent) — three narrower,
   agent-specific handlers with no `directory` param at all, always
   scoped to the fixed agent root via `root.rglob("*.py")`. Audited and
   confirmed NOT exploitable (no LLM-controlled path input exists on
   these at all) — left untouched.

Per `tool_inventory.json`, 60 agents declare `find_todos` in
`allowed_tools`. `CHAT_TOOLS.count("find_todos") == 1` verified. No
existing tests referenced `find_todos` at all — confirmed by grep
(matches the tracking table's "0" test-file figure).

## Problems found

**Finding #1 — worktree-boundary escape, on BOTH implementations #1
and #2, INCLUDING the canonical `make_read_only_handlers()`
factory.** Same class as tool #76's `analyze_file` finding. Neither
called `check_path_in_worktree()` on the optional `directory` field —
the plain `root / directory` pathlib bug. Proved live on both real
call sites:

```python
await agent._execute_tool("find_todos", {"directory": "/tmp/outside"})
handlers["find_todos"]({"directory": "/tmp/outside"})
```

both genuinely returned a real TODO comment's full text (including
its file path) from a file completely outside the repo.

**Finding #2 — a real, minor functionality-parity gap.** The
canonical implementation's `--include` list covers `*.py`, `*.ts`,
`*.tsx`, `*.js`, `*.md`; `chat_agent.py`'s dispatch was missing
`--include=*.js` entirely, silently never finding TODOs in `.js`
files via the interactive chat path even though the canonical
implementation already would.

**Checked, confirmed safe (no fix needed): `kind`.** Structurally
immune to the tool #69 flag-injection class — always embedded inside a
fixed `"(" ... "):"` wrapper before reaching grep's `-E` argument, so
it can never be interpreted as a flag. Proved live with `kind="-e"`,
producing a harmless, literal (empty) search. The schema's `enum` is
advisory only (not runtime-enforced), but an out-of-enum value grants
no capability beyond what `search_code` (tool #69, already
GREEN_FLAG) already exposes to the same caller — deliberately left
unrestricted, matching the precedent set for `search_symbols`'s
`kind` field in tool #73.

## Changes made

Extracted a single shared `find_todos_handler()` in
`app/tools/filesystem/find_todos.py`, used by both real call sites:

- `check_path_in_worktree()` closes finding #1.
- Adopting the canonical implementation's `--include=*.js` for both
  real call sites closes finding #2.

`app/agents/tools.py`'s `READ_ONLY_TOOLS[10]` (verified empirically as
the correct index before editing) now points at the shared
`FIND_TODOS_TOOL` constant, and its `make_read_only_handlers()`
closure delegates to the shared handler. `app/agents/chat_agent.py`'s
dispatch now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_find_todos_hardening.py`, 13 tests, all real (no
mocking) — schema/index checks, worktree-escape rejection on both
real dispatch paths, `.js`-detection regression on both real dispatch
paths, `kind` flag-injection-immunity verification, and
legitimate-usage regression (marker detection, `kind` filtering, clean
no-match message).

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed on both real
implementations; no functionality lost; full regression clean.
