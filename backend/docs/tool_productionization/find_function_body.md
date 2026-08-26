# Tool #111 — `find_function_body` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations:

1. `chat_agent.py`'s own interactive dispatch — already correct
   (path+function_name-based line-scan extraction) but see finding #2.
2. `find_function_body` inside `make_chat_handlers()` — same shape as
   #1.
3. `bf_find_function_body` (`make_bug_fix_handlers`) — see finding #1.
4. `rf_find_function_body` (`make_refactor_agent_handlers`) — same bug
   as #3, byte-identical code.

Per `tool_inventory.json`, agents declaring `find_function_body` go
through one of the factories above. `CHAT_TOOLS.count(
"find_function_body") == 1` verified. 2 existing test files reference
this tool — 1 genuinely exercises the real handler (against
`make_chat_handlers` only), re-run and confirmed passing unchanged.

## Problems found

**Finding #1 — a real, severe functionality bug: `bf_find_function_
body` and `rf_find_function_body` are BOTH completely broken, in
three separate ways.** They read `inp["name"]` — but the schema
declares the field as `function_name`, never `name`. Proved live: any
real, schema-conformant call (`{"path": ..., "function_name": ...}`)
raises an uncaught `KeyError: 'name'` — a 100% crash rate. On top of
that, even if the field name were fixed, both implementations also
completely ignore `path` (they `grep -rn` the ENTIRE repo instead of
reading the specified file) and never actually extract "the complete
source code... including its body" as the schema promises — they
return raw `grep` match lines (just the `def ...` signature line
itself), not the function body. Same "dead/wrong field read" class
already established for tools #24/#82/#90/#91.

**Finding #2 — worktree-boundary escape, on the two already-correct
implementations.** Neither validated `path` before `root / path` — an
absolute path discards `root` entirely. Proved live:
`find_function_body({"path": "/tmp/outside/secret.py",
"function_name": "leaked_secret_function"})` genuinely read and
returned the COMPLETE SOURCE of a function from a file completely
outside the repo — a severe file-disclosure primitive, made worse by
this tool's own explicit purpose being to dump out full function
source.

## Changes made

New shared `find_function_body_handler()` in
`app/tools/filesystem/find_function_body.py`: `path` is validated via
`check_path_in_worktree()` — closes finding #2. `bf_`/
`rf_find_function_body` are fully replaced by this shared, correct
handler (adopting the real, working `path`+`function_name`-based
line-scan extraction already proven correct by the other two call
sites) rather than kept as second, broken implementations — closes
finding #1, a genuine capability increase (real body extraction
instead of a crash) for those two call sites.

`app/agents/tools.py`'s `_FIND_FUNCTION_BODY_TOOL` now aliases the
shared `FIND_FUNCTION_BODY_TOOL` constant. No external
direct-importers found.

## Tests

New file `tests/test_find_function_body_hardening.py`, 14 tests, all
real (no mocking) — schema check, duplicate-registration check, a
real proof the two previously-crashing factories now genuinely extract
a real function body, worktree-escape rejection on the interactive
dispatch AND all three handler factories (parametrized, with a real
secret-shaped value verified absent from the result), dotdot-traversal
rejection, and legitimate-usage regression (correct body extraction,
correct boundary detection excluding a sibling function, clean
missing-function error, an `async def` case) across all four real
access paths. Existing tests (`test_chat_tools.py::
TestFindFunctionBody`) re-run and confirmed passing unchanged (2
tests).

## Regression

This tool is tool 3 of the current #109-#113 batch. Its own new
hardening tests (14/14 pass) and directly-referencing existing tests
(2/2 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
find_function_body.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings — a 100%-crash-rate field-name bug
across two implementations, and a severe worktree-escape file-
disclosure primitive on the other two — proved live and closed across
all four real implementations; the tool now genuinely does what it has
always claimed to do, for every real caller; no functionality lost;
tool-specific and directly-referencing regression tests clean.
