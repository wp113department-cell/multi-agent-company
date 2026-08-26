# Tool #120 — `yaml_validate` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `yaml_validate_h` inside `make_chat_handlers()`,
sharing the private `_load_schema_doc()`/`_validate_against_schema()`
helpers with the sibling `json_validate` tool (#159, still PENDING).
`app/agents/runbook_generator_agent.py` imports `_YAML_VALIDATE_TOOL`
(the schema dict only, not the handler) directly — confirmed unaffected
since `app/agents/tools.py` keeps re-exporting that name unchanged.

`yaml_validate` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

4 existing test files reference this tool
(`test_phase3_verification_audit.py`,
`test_audit_q_batch09_large_project_file_tech.py`,
`test_phase35_per_tier_critique.py`, `test_editor_tier.py`) — 63 tests
total, re-run and confirmed passing unchanged.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine ARBITRARY
FILE READ, on both `path` and `schema_path`.** `yaml_validate_h` built
`root / str(inp["path"])` (and, via the shared `_load_schema_doc()`
helper, `root / schema_rel` for `schema_path`) without checking
whether either was already absolute — the same `pathlib`-silently-
discards-`root`-for-an-absolute-right-operand class already documented
for tools #99/#107/#116 this initiative. Proved live: a `path`/
`schema_path` value pointing outside the intended worktree was
genuinely read.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools #100/#103/#110/#112/#118.** `yaml_validate`
is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s handlers
dict, but `chat_agent.py`'s `_execute_tool()` had no dispatch branch —
every real interactive-chat call fell through to `"[ERROR] Unknown
tool: yaml_validate"`.

## Changes made

New shared `yaml_validate_handler()` (plus worktree-validated
`_load_schema_doc()`/`_validate_against_schema()` helper copies) in
`app/tools/filesystem/yaml_validate.py`:
- Both `path` and `schema_path` are validated via
  `check_path_in_worktree()` before any filesystem access, closing
  finding #1.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #2 — `yaml_validate` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_YAML_VALIDATE_TOOL` now aliases the shared
`YAML_VALIDATE_TOOL` constant; `yaml_validate_h` delegates to the
shared handler.

**Deliberately not fixed here (documented, out of scope for this
tool's own turn)**: the sibling `json_validate` tool (#159, still
PENDING) shares the exact same worktree-escape bug on its own `path`
and `schema_path` fields via the still-untouched, tools.py-resident
`_load_schema_doc()`/`_validate_against_schema()` closures — left
alone here, matching this initiative's established "found but
explicitly did not fix a sibling tool's identical bug" precedent (tool
#14).

## Tests

New file `tests/test_yaml_validate_hardening.py`, 12 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof for
both `path` and `schema_path` (across `make_chat_handlers`, the new
`chat_agent.py` dispatch, and a direct handler call), a proof the new
dispatch no longer returns "Unknown tool", and legitimate-usage
regression (valid YAML, invalid YAML, schema match, schema violation)
across both real access paths.

Existing tests re-run and confirmed passing:
`test_phase3_verification_audit.py`,
`test_audit_q_batch09_large_project_file_tech.py`,
`test_phase35_per_tier_critique.py`, `test_editor_tier.py` — 63 tests
total.

## Regression

This tool is tool 2 of the #119-#123 batch (tool #123, one of the
`browser_*` tools, was already GREEN_FLAG from an earlier batch). Its
own new hardening tests (12/12 pass) and all 4 directly-referencing
existing test files (63/63 pass) are the per-tool verification gate;
the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
yaml_validate.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG. `runbook_generator_agent.py`'s
real integration re-verified working.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific and directly-referencing regression tests clean.
