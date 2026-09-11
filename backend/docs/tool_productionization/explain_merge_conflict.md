# Tool #136 — `explain_merge_conflict` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real, near-identical implementations:

1. `explain_merge_conflict` inside `make_chat_handlers()`.
2. `chat_agent.py`'s own interactive dispatch.

Per `tool_inventory.json`, agents declaring `explain_merge_conflict`
go through one of these. `CHAT_TOOLS.count("explain_merge_conflict")
== 1` verified. 4 existing test files reference this tool
(`test_file_ops_worktree_boundary_hardening.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py`,
`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_audit_q_batch10_deployment_external_git_docs.py`) — 110 tests
total, re-run and confirmed passing unchanged.

**Note (tracking-table carry-over)**: worktree-boundary validation was
already correct on both real implementations
(`check_path_in_worktree(rel, repo_path)` /
`_is_protected_path(emc_rel, repo)`, both performing full worktree-
containment checking given `worktree_path`) — fixed 2026-08-17 during
tool #11's (`undo_changes`) cross-cutting audit. Confirmed still
correct here by direct inspection and re-verified live (see Real
Execution below), not assumed to still hold.

## Problems found

One real finding — a robustness gap: neither implementation wrapped
`target.read_text()` in a `try/except`, same class already fixed for
tools #70/#72/#76/#135. Proved live with a real `chmod 000` file: a
genuine `PermissionError` propagated straight out of both real
handlers.

## Changes made

New shared `explain_merge_conflict_handler()` in
`app/tools/git/explain_merge_conflict.py`: the file read is now
wrapped in `try/except`, matching the class already fixed for other
tools. Worktree validation is unchanged — reused verbatim from the
already-correct implementation. Both real call sites delegate to this
one handler.

`_llm_explain_conflict_hunks()` (the LLM-backed explanation generator
in `app/agents/tools.py`, built on the broadly-shared
`_llm_generate_text()` utility used by several other, out-of-scope
tools) is deliberately left in place and passed into the new handler
as an injected `explain_fn` callable, rather than relocated —
avoiding both a circular import (this module would otherwise need to
import from `app.agents.tools`, which imports this module) and any
out-of-scope change to a utility shared by unrelated tools.
`_parse_conflict_markers` is imported directly from its own existing
home, `app.agents.conflict_resolution` — already a neutral,
non-circular module, so no relocation was needed there either.

`app/agents/tools.py`'s `_EXPLAIN_MERGE_CONFLICT_TOOL` now aliases the
shared `EXPLAIN_MERGE_CONFLICT_TOOL` constant. No external
direct-importers of the old names were found.

## Tests

New file `tests/test_explain_merge_conflict_hardening.py`, 11 tests:
schema check, duplicate-registration check, a real proof the
permission-error crash is fixed (across `chat_agent.py`'s dispatch, a
direct handler call, and `make_chat_handlers`), a re-verification that
worktree-boundary rejection still works on both real access paths, and
legitimate-usage regression (no-conflict-markers case, missing-file
error, a real parsed-hunks-reach-`explain_fn` proof) across both real
access paths.

Existing tests re-run and confirmed passing:
`test_file_ops_worktree_boundary_hardening.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py`,
`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_audit_q_batch10_deployment_external_git_docs.py` — 110 tests
total.

## Regression

This tool is tool 1 of a new #136-#140 batch. Its own new hardening
tests (11/11 pass) and all 4 directly-referencing existing test files
(110/110 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/
explain_merge_conflict.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The real robustness finding proved live and closed
across both real implementations; the already-correct worktree
validation re-verified live rather than assumed; no functionality lost
— legitimate conflict explanations are proven to still work;
tool-specific and directly-referencing regression tests clean.
