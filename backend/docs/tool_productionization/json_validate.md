# Tool #159 — `json_validate` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `json_validate_h` inside `make_chat_handlers()`,
sharing private `_load_schema_doc()`/`_validate_against_schema()`
helpers with sibling `yaml_validate` — already fixed and relocated
during that tool's own turn (tool #120), whose docstring explicitly
flagged this exact bug on `json_validate` and deferred it to this
turn.

`json_validate` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/
test_audit_q_batch09_large_project_file_tech.py`'s
`TestSchemaValidation` (3 tests) and `tests/test_new_tools.py`'s
`test_json_validate_valid`/`test_json_validate_invalid` (2 tests) — 5
total, confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings — the identical bug class
already found and fixed for sibling tool #120's `yaml_validate`.

**Finding #1 — a worktree-boundary escape that is a genuine ARBITRARY
FILE READ, on both `path` and `schema_path`.** `json_validate_h` built
`root / str(inp["path"])` (and, via the old `_load_schema_doc()`
helper, `root / schema_rel` for `schema_path`) without checking
whether either was already absolute — the same class already
documented for tools #99/#107/#116/etc this initiative, and for
`yaml_validate` itself. Proved live: `json_validate({"path": "/tmp/
<outside file>"})` genuinely parsed a deliberately-malformed file
outside the intended worktree, confirmed via a parse-position-derived
error message unique to that file's real content — real
cross-boundary access, not a guess.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158.**
`json_validate` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: json_validate"`.

## Changes made

Rather than re-duplicating the identical worktree-validated
schema-loading logic a second time (the literal duplication class this
initiative has repeatedly flagged and consolidated elsewhere — e.g.
tools #145/#153's `generate_commit_msg`/`generate_patch`),
`_load_schema_doc()`/`_validate_against_schema()` were extracted out of
`yaml_validate.py`'s own private copies into a new shared module,
`app/tools/filesystem/json_schema_validation.py`
(`load_schema_doc`/`validate_against_schema`, no leading underscore —
now genuinely shared, not tool-private). `yaml_validate.py` now
imports from there instead of defining its own copies (behavior
unchanged, re-verified via its own 12 existing tests, all still
passing). New shared `json_validate_handler()` in `app/tools/
filesystem/json_validate.py` uses the same shared helpers: `path` is
validated with `check_path_in_worktree()` before the file is ever
read, closing finding #1 (and `schema_path` is validated the same way
inside `load_schema_doc()`). A new `chat_agent.py` dispatch branch
delegates to this shared handler, closing finding #2.

`app/agents/tools.py`'s `_JSON_VALIDATE_TOOL` now aliases the shared
`JSON_VALIDATE_TOOL` constant; its own now-dead private
`_load_schema_doc()`/`_validate_against_schema()` closures were
removed (confirmed via grep they had no other callers).

## Tests

New file `tests/test_json_validate_hardening.py`, 14 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(`path` absolute, `path` relative traversal, and `schema_path`
absolute, across all 3 real access paths), a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (valid/
invalid JSON, schema match/violation, and a `.yaml` schema file
validating a `.json` document — confirming the shared helper's
format-agnostic behavior is preserved).

Existing tests (5 total across 2 files) re-run clean. `yaml_validate`'s
own existing 12 tests also re-run clean after the shared-module
extraction, confirming zero regression to that already-closed tool.

## Regression

This tool is tool 1 of a new #159-#163 batch. Its own new hardening
tests (14/14 pass) plus the 5 pre-existing tests for this tool (5/5
pass) plus `yaml_validate`'s 12 pre-existing tests (12/12 pass,
re-verified after the shared-module refactor) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
json_validate.py app/tools/filesystem/json_schema_validation.py`
sweep (103 files clean — one more than the usual 102 due to the new
shared module), an `importlib.import_module()` sweep over all
`app/agents/` modules (all clean), a `ruff check` on every touched
file (clean), a `python -W error` docstring escape-sequence check on
the new modules (clean), and `CHAT_TOOLS.count("json_validate") == 1`
/ `CHAT_TOOLS.count("yaml_validate") == 1` checks (both clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; the shared-module
extraction eliminates a real duplication/drift risk between this tool
and `yaml_validate` rather than compounding it; no functionality lost;
tool-specific regression tests clean (31/31 across new + swept
existing tests for both tools).
