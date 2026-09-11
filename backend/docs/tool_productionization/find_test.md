# Tool #140 — `find_test` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, DIVERGENT implementations:

1. `find_test_h` inside `make_chat_handlers()` — already correct.
2. `chat_agent.py`'s own interactive dispatch — a separately-drifted,
   narrower reimplementation (see finding below), unlike most other
   tools this initiative where the dispatch was either identical or
   entirely missing.

Per `tool_inventory.json`, agents declaring `find_test` go through one
of these. `CHAT_TOOLS.count("find_test") == 1` verified. 1 existing
test file references this tool (`test_day1_tools.py::TestFindTest`, 2
tests) — re-run and confirmed passing unchanged.

`find_test`'s schema has no path field at all (only `function_name`)
— the worktree-boundary-escape class established repeatedly this
initiative does not apply here.

## Problems found

**Checked, confirmed NOT vulnerable (not assumed)**: the
shell-injection / grep-own-flag-collision class already established
repeatedly this initiative for `chat_agent.py`'s `shell=True` grep
dispatches (find_api/find_route/find_sql/inspect_schema/
explain_query/find_config) does NOT apply here. Every pattern this
tool builds always embeds `function_name` INSIDE a larger literal
prefix (`f"def test_{fn}"`, etc.), so the constructed regex argument
can never itself begin with `-`, and `chat_agent.py`'s own
`shlex.quote()` around the whole pattern correctly neutralizes shell
metacharacters. Proved live: a real shell-metacharacter payload
(`"; touch <marker>; echo x"`) produced no injected command and no
marker file, on both real implementations.

One real finding — a functionality-divergence bug:
`chat_agent.py`'s dispatch is a separately-drifted, narrower
reimplementation of the same tool, missing real capability the
canonical `make_chat_handlers()` implementation already has:
1. Only 2 of the 3 search patterns (`def test_{fn}`, `def
   test.*{fn}`) — missing the third, `test.*["'].*{fn}`, which is what
   catches JS/TS `test("...")`/`it("...")`-style test descriptions.
2. `--include=*.test.ts --include=*.spec.ts` instead of the canonical
   `--include=*.ts` — narrower, missing plain `.ts` test files that
   don't follow the `.test.ts`/`.spec.ts` naming convention.
3. When nothing is found, it silently returns `_run_subprocess`'s own
   generic `"(no output)"` placeholder instead of the tool's intended,
   clear `"No tests found for '<name>'"` message.

Proved live: a real JS-style `test("special_widget renders correctly",
...)` file was found by the canonical implementation but silently
missed by `chat_agent.py`'s dispatch, returning the unhelpful
`"(no output)"` instead of either the real match or a clear
"not found" message.

## Changes made

Modularized into `app/tools/filesystem/find_test.py` —
`FIND_TEST_TOOL`, `find_test_handler` (the already-correct
`make_chat_handlers()` logic, moved verbatim: list-args subprocess,
all three patterns, correct `--include` filters, correct fallback
message). `chat_agent.py`'s dispatch is fully replaced to delegate to
this same shared, canonical handler rather than keeping its own
drifted reimplementation — closing the finding as a genuine capability
increase for the interactive-chat surface, not a narrowing.

`app/agents/tools.py`'s `_FIND_TEST_TOOL` now aliases the shared
`FIND_TEST_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_find_test_hardening.py`, 9 tests: schema check,
duplicate-registration check, a re-confirmed no-shell-injection proof
(not assumed from the audit alone), a real proof `chat_agent.py`'s
dispatch now finds a JS-style test it previously missed, a proof it
now gives the clear "No tests found" message instead of "(no
output)", and legitimate-usage regression (real Python test match,
no-match case) across both real access paths.

Existing tests re-run and confirmed passing:
`test_day1_tools.py::TestFindTest` (2/2).

## Regression

This tool is tool 5 of the #136-#140 batch, completing it. Its own new
hardening tests (9/9 pass) and the directly-referencing existing test
file (2/2 pass) are the per-tool verification gate; the full suite
runs now that the batch is complete, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
find_test.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real functionality-divergence finding proved live
and closed via full replacement onto the already-correct canonical
implementation — a strict capability increase for the interactive-chat
surface, not a narrowing; the absence of injection/flag-collision
vulnerabilities was verified live, not assumed; tool-specific and
directly-referencing regression tests clean.
