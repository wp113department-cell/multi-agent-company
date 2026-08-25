# Tool #93 — `call_graph` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

The exact sibling tool to tool #83's `parse_ast` — five real
implementations, all thin one-liners around the same shared
`app.repo_tools.ast_engine.build_call_graph()` utility:

1. `chat_agent.py`'s own interactive dispatch.
2. `call_graph_h` inside `make_chat_handlers()` (~35 one-shot agents).
3. `bf_call_graph` (`make_bug_fix_handlers`).
4. `ar_call_graph` (`make_arch_reviewer_handlers`).
5. `rf_call_graph` (`make_refactor_agent_handlers`).

Per `tool_inventory.json`, 4 agents declare `call_graph` in
`allowed_tools`. `CHAT_TOOLS.count("call_graph") == 1` verified. 2
existing test files reference this tool and both exercise the real
handler — re-run and confirmed passing unchanged (7 tests).

## Problems found

Same two finding classes already established for tool #83's
`parse_ast`, proved live independently for this sibling tool.

**Finding #1 — worktree-boundary escape, on all five
implementations.** None called `check_path_in_worktree()` — `root /
path` let `path` resolve to any absolute host path before being
handed to `ast_engine.build_call_graph()`. Proved live:
`call_graph({"path": "/tmp/outside/secret.py"})` genuinely returned a
real call graph (caller names, line numbers, and every function each
one calls) of a Python file completely outside the repo, through
multiple real call sites (`chat_agent.py`'s dispatch,
`make_chat_handlers()`, `make_bug_fix_handlers()`).

**Finding #2 — an uncaught `PermissionError`, on all five
implementations — same class as tools #70/#72/#76/#82/#83.** Neither
each thin wrapper nor `ast_engine.get_call_edges()`'s own internal
`p.exists()` call is wrapped in a `try/except PermissionError`. Proved
live with a real file inside a `chmod 000` parent directory.

## Changes made

Extracted a shared `call_graph_handler()` in
`app/tools/filesystem/call_graph.py`, adopted by **all five** real
call sites: `check_path_in_worktree()` closes finding #1; wrapping the
call to the existing, UNMODIFIED `ast_engine.build_call_graph()` in
`try/except PermissionError` closes finding #2.
`ast_engine.build_call_graph()`/`get_call_edges()` themselves are left
completely untouched — `get_call_edges()` is also used by
`generate_diagram_h`, a separate, out-of-scope tool.

`app/agents/tools.py`'s `_CALL_GRAPH_TOOL` now aliases the shared
`CALL_GRAPH_TOOL` constant via a plain module-level assignment (not a
renaming `as` import) — checked proactively before wiring, since
`architecture_doc_agent.py` imports this name directly, the same mypy
`--strict` class first caught in tool #86. One now-dead `from
app.repo_tools import ast_engine as _ast` import (in
`make_bug_fix_handlers`, whose only remaining use was the old
`bf_call_graph` body) was removed after `ruff` caught it post-fix —
the sibling imports in `make_arch_reviewer_handlers`/
`make_refactor_agent_handlers` are still genuinely used by other,
out-of-scope tools (`import_graph`, `dead_code_detect`,
`rename_symbol`) and were left alone.

## Tests

New file `tests/test_call_graph_hardening.py`, 17 tests, all real (no
mocking) — schema check, worktree-escape rejection on the interactive
dispatch AND all four factories (parametrized), traversal rejection,
permission-denied handling on two real access paths, and
legitimate-usage regression (real call graph, function-name filter,
missing-file error) across all five real access paths (parametrized
where applicable). Existing tests
(`test_day2_agents.py::TestBugFixHandlers::test_call_graph_returns_text`,
`test_day1_tools.py::TestCallGraph`) re-run and confirmed passing
unchanged.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change. Per the standing lessons from tools #88/#90, this turn
was also verified via a comprehensive `mypy app/agents/` sweep (98
files clean), an `importlib.import_module()` sweep (all clean), and a
`python -W error` docstring escape-sequence check (clean) BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
five real implementations; the underlying, shared, correct call-graph
utility reused verbatim rather than reinvented; no functionality lost;
full regression clean.
