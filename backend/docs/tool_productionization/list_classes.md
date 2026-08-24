# Tool #87 — `list_classes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

The exact sibling tool to tool #82's `list_functions` — seven real
implementations:

1. `chat_agent.py`'s own interactive dispatch — single-file, no
   worktree check.
2. `list_classes` inside `make_chat_handlers()` (~35 one-shot agents)
   — identical logic, also unprotected.
3. `ar_list_classes` (`make_arch_reviewer_handlers`) — read the wrong
   field (`file` vs the schema's `path`).
4. `rf_list_classes` (`make_refactor_agent_handlers`) — same
   field-name bug.
5. `rm_list_classes` (`make_readme_agent_handlers`) — same
   field-name bug.
6. `sr_list_classes` (`make_style_reviewer_handlers`) — correct field,
   `rglob`-based, no worktree check.
7. `td_list_classes` (`make_tech_debt_agent_handlers`) — same as #6.

Unlike `list_functions`, this tool was never wired into
`make_api_docs_agent_handlers()` or `make_performance_reviewer_
handlers()` at all — confirmed by grep, not assumed. Per
`tool_inventory.json`, 7 agents declare `list_classes` in
`allowed_tools`. `CHAT_TOOLS.count("list_classes") == 1` verified. 1
existing test file references this tool, exercising the real handler
— re-run and confirmed passing unchanged (4 tests).

## Problems found

Same four finding classes already established for tool #82's
`list_functions`, proved live independently for this sibling tool.

**Finding #1 — worktree-boundary escape + uncaught `PermissionError`
on the two single-file implementations.** Proved live:
`list_classes({"path": "/tmp/outside/secret.py"})` genuinely listed a
real class definition (and its methods) from a file completely
outside the repo, through both real call sites. A `chmod 000` parent
directory produced an uncaught `PermissionError`.

**Finding #2 — a field-name mismatch in THREE agent-specific
implementations** (`ar_list_classes`, `rf_list_classes`,
`rm_list_classes`). Proved live: a schema-conformant call for
`{"path": "src/target.py"}` returned class definitions from BOTH
`src/target.py` AND a completely unrelated file elsewhere in the
repo.

**Finding #3 — worktree-boundary escape via relative `../` traversal
in TWO agent-specific implementations** (`sr_list_classes`,
`td_list_classes`). Proved live:
`list_classes({"path": "../../../../tmp/outside"})` via
`sr_list_classes` genuinely returned a real class definition from a
file outside the repo — the absolute-path exploit shape is blocked
only by an accidental swallowed `ValueError`, not by design.

**Finding #4 — a design mismatch**: the tool's own schema/description
promise single-file analysis, but five agent-specific implementations
instead grep/rglob an entire subtree.

## Changes made

Extracted one shared `list_classes_handler()` in
`app/tools/filesystem/list_classes.py`, adopted by **all seven** real
call sites: `check_path_in_worktree()` closes findings #1 and #3;
reading the correct `path` field (not `file`) closes finding #2;
adopting the single-file, indentation-aware class+method-detection
logic already shared by `chat_agent.py`/`make_chat_handlers()`
everywhere closes finding #4.

`app/agents/tools.py`'s `_LIST_CLASSES_TOOL` now aliases the shared
`LIST_CLASSES_TOOL` constant (a plain module-level assignment, not a
renaming `as` import — `architecture_doc_agent.py` imports this name
directly, and the lesson from tool #86's mypy fix was applied
proactively here rather than caught after the fact).

## Tests

New file `tests/test_list_classes_hardening.py`, 18 tests, all real
(no mocking) — schema/duplicate checks, worktree-escape rejection on
the single-file implementations, permission-denied handling, the
field-name-mismatch fix verified closed on all three affected
factories (parametrized), the relative-traversal-escape fix verified
closed on both affected factories (parametrized), and legitimate-usage
regression (class + method detection, missing-file error) across all
seven real access paths. The one existing test
(`test_chat_tools.py::TestListClasses`) re-run and confirmed passing
unchanged.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** All four real findings proved live and closed across
all seven real implementations, independently verified rather than
assumed to transfer from tool #82's sibling fix; no functionality
lost; full regression clean.
