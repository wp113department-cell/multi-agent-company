# Tool #95 — `import_graph` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

The exact sibling tool to tool #83's `parse_ast` — four real
implementations, all thin one-liners around the same shared
`app.repo_tools.ast_engine.build_import_graph()` utility:

1. `chat_agent.py`'s own interactive dispatch.
2. `import_graph_h` inside `make_chat_handlers()`.
3. `ar_import_graph` (`make_arch_reviewer_handlers`).
4. `rf_import_graph` (`make_refactor_agent_handlers`).

Per `tool_inventory.json`, 4 agents declare `import_graph` in
`allowed_tools`. `CHAT_TOOLS.count("import_graph") == 1` verified. 7
existing test-file matches found — read in context (not trusted at
face value); most were an unrelated `import_graph_ran` verification
flag from a different data structure. Two genuinely exercise the real
handler (`test_day2_agents.py::test_import_graph_on_python_file`,
`test_day1_tools.py`'s membership + handler-presence checks) — re-run
and confirmed passing unchanged.

## Problems found

Same two finding classes already established for tool #83's
`parse_ast`, proved live independently for this sibling tool.

**Finding #1 — worktree-boundary escape, on all four
implementations.** None called `check_path_in_worktree()` — `root /
path` let `path` resolve to any absolute host path before being
handed to `ast_engine.build_import_graph()`. Proved live:
`import_graph({"path": "/tmp/outside/secret.py"})` genuinely returned
a real import list (module names and imported symbols) of a Python
file completely outside the repo.

**Finding #2 — an uncaught `PermissionError`, on all four
implementations — same class as tools #70/#72/#76/#82/#83/#93.**
`ast_engine.build_import_graph()`'s own internal `p.read_text()` call
is not wrapped in `try/except PermissionError`. Proved live with a
real file inside a `chmod 000` parent directory. Confirmed this is the
single-file-read shape (raises), not tool #94's directory-walk shape
(silently swallows) — checked directly rather than assumed either way.

## Changes made

Extracted a shared `import_graph_handler()` in
`app/tools/filesystem/import_graph.py`, adopted by **all four** real
call sites: `check_path_in_worktree()` closes finding #1; wrapping the
call to the existing, UNMODIFIED `ast_engine.build_import_graph()` in
`try/except PermissionError` closes finding #2.
`ast_engine.build_import_graph()` itself is left completely untouched.

`app/agents/tools.py`'s `_IMPORT_GRAPH_TOOL` now aliases the shared
`IMPORT_GRAPH_TOOL` constant via a plain module-level assignment (not
a renaming `as` import) — checked proactively before wiring, since
`architecture_doc_agent.py` imports this name directly (the same file
that also imports `_CALL_GRAPH_TOOL`/`_DEAD_CODE_DETECT_TOOL` from
tools #93/#94), the same mypy `--strict` "not explicitly exported"
class first caught in tool #86.

## Tests

New file `tests/test_import_graph_hardening.py`, 14 tests, all real
(no mocking) — schema check, duplicate-registration check,
worktree-escape rejection on the interactive dispatch AND all three
handler factories (parametrized), dotdot-traversal rejection,
permission-denied handling on two real access paths, and
legitimate-usage regression (real import list, missing-file error)
across all four real access paths (parametrized where applicable).
Existing tests (`test_day2_agents.py::TestArchReviewerHandlers::
test_import_graph_on_python_file`, `test_day1_tools.py`) re-run and
confirmed passing unchanged (3 tests).

## Regression

Per the user's 2026-08-25 cadence correction, the full suite is run
once per 5-tool batch rather than per tool — see
`feedback_tool_enhance_batch_full_suite` memory. This tool (#95) is
tool 2 of the current batch (#94-#98); its own new hardening tests
(14/14 pass) and directly-referencing existing tests (3/3 pass) are
the per-tool verification gate. The full-suite run covering this
batch will be executed and reported once tool #98 completes.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
import_graph.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed across all
four real implementations; the underlying, shared, correct
import-extraction utility reused verbatim rather than reinvented; no
functionality lost; tool-specific and directly-referencing regression
tests clean. Full-suite confirmation pending as part of the #94-#98
batch.
