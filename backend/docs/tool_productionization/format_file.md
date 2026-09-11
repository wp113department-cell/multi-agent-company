# Tool #143 — `format_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations:

1. `format_file` inside `make_chat_handlers()`.
2. `chat_agent.py`'s own interactive dispatch — an even more severely
   broken copy (see finding #2).

Per `tool_inventory.json`, agents declaring `format_file` go through
one of these. `CHAT_TOOLS.count("format_file") == 1` verified. 1
existing test file references this tool
(`test_chat_tools.py::TestFormatFile`, 2 tests) — re-run and confirmed
passing unchanged.

Same finding shape as tool #115's `organize_imports` — this tool's
whole purpose is to REWRITE the target file in place via an external
formatter, so a worktree-escape here is a genuine arbitrary-file-WRITE
primitive, more severe than a plain read.

## Problems found

Two real findings.

**Finding #1 (severe) — a worktree-boundary escape on BOTH real
implementations, a genuine ARBITRARY FILE WRITE.** Neither validated
`path` before `root / path` — the same
`pathlib`-silently-discards-`root`-for-an-absolute-right-operand class
already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142
this initiative. Proved live, in isolated `/tmp` directories (per the
established safe-mutation-testing rule, since this tool genuinely
mutates files — never the real project): an absolute `path` outside
the intended worktree would have been genuinely reformatted in place
by both real implementations before this fix.

**Finding #2 — `chat_agent.py`'s dispatch was additionally a genuine,
direct shell-injection RCE, worse than `tools.py`'s own copy.**
`tools.py`'s `format_file` at least wraps the target in
`shlex.quote()` before interpolating it into the `shell=True` command
string (protecting against shell metacharacters, though not the
worktree escape — `shlex.quote()` is not enough for a path that
already resolves outside the worktree, the exact same
"shlex.quote-is-not-enough" class established for several other
tools' `chat_agent.py` dispatches this initiative). `chat_agent.py`'s
own dispatch, however, interpolated `str(fmt_target)` into its
`shell=True` command COMPLETELY UNQUOTED — the same class as tool
#115's `organize_imports` shell-injection finding. Proved live, in an
isolated `/tmp` directory: a path payload that would close the
intended command early was confirmed to no longer create an injected
marker file after the fix.

## Changes made

New shared `format_file_handler()` in
`app/tools/filesystem/format_file.py`: `path` is validated with
`check_path_in_worktree()` before any filesystem access, closing
finding #1. Both `ruff`/`black` and `prettier` are now invoked via
list-args `subprocess.run()` — `shell=True` dropped entirely, the same
structural fix pattern established for tool #115 — closing finding #2
structurally rather than by adding more quoting. Both real call sites
now delegate to this one handler.

`app/agents/tools.py`'s `_FORMAT_FILE_TOOL` now aliases the shared
`FORMAT_FILE_TOOL` constant. No external direct-importers of the old
names were found.

`tests/test_stage4_tier3_venv_activate_cross_platform.py` was updated:
this fix removes 2 more of the shell-snippet call sites that test
counts (5 remain in `app/agents/tools.py`, down from 7), matching the
same precedent as tools #101/#115.

## Tests

New file `tests/test_format_file_hardening.py`, 11 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(across `make_chat_handlers`, the new `chat_agent.py` dispatch, and a
direct handler call) with assertions the outside file's content is
genuinely unchanged, a real shell-injection-blocked proof on
`chat_agent.py`'s dispatch, and legitimate-usage regression (a real
Python file genuinely reformatted, missing-file error, unknown-
formatter error) across both real access paths. All escape/injection
proofs use `tmp_path` fixtures exclusively — no real-project-directory
exposure, per the safe-mutation-testing rule established after tool
#115's incident.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestFormatFile` (2/2).

## Regression

This tool is tool 3 of the #141-#145 batch. Its own new hardening
tests (11/11 pass) and the directly-referencing existing test file
(2/2 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
format_file.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live (safely, in isolated
`/tmp` directories) and closed across both real implementations; no
functionality lost — legitimate formatting (ruff, and by the same
mechanism black/prettier) is proven to still work; tool-specific and
directly-referencing regression tests clean.
