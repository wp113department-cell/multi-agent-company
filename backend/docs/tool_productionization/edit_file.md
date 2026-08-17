# Tool #13 — `edit_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Like `write_file` (tool #12), `edit_file` has multiple independently-
maintained implementations rather than a clean 1-real/1-dead pair — 7 in
total:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_coder_handlers`'s `edit_file` — generic.
3. `_make_edit_file_handler` — a shared factory reused by 4 separate
   handler-set factories (generic).
4. `make_dependency_agent_handlers`'s `dep_edit_file` — restricted to
   `_DEP_EDITABLE` filenames (requirements.txt/package.json/...).
5. `make_cleanup_agent_handlers`'s `cu_edit_file` — generic.
6. `make_chat_handlers`'s own `edit_file` — generic, reused by ~35
   one-shot batch agents.
7. `make_fleet_apply_handlers`'s `edit_file_h` — generic plus a
   role-prompt-registry redirect for `roles/<name>.md` targets; used by
   the 4 fleet self-enhancement agents.

This tool's own most severe bug — `chat_agent.py`'s real dispatch calling
`_is_protected_path` **not at all** (not even the denylist, unlike every
other tool in this initiative which at least had the denylist) — was
already found and fixed during tool #11's (`undo_changes`) cross-cutting
audit (full detail: `docs/tool_productionization/undo_changes.md`). This
turn's job was to finish properly: audit every other real implementation,
and modularize per tool_enhance.md's mandatory rule.

## Problems found

**None new.** All 6 previously-unaudited implementations were already
correctly guarded (`check_path_in_worktree()` or
`_is_protected_path(rel, repo_path)` with the worktree argument present),
proved with a real security sweep against each one — see Tests below.

## Changes made

**Modularized** (the generic, unscoped variant):

- **`app/tools/filesystem/edit_file.py`** (new): `EDIT_FILE_TOOL` (the
  canonical schema — previously two differently-worded but
  functionally-identical copies, `CODER_TOOLS`'s own entry and
  `_EDIT_FILE_TOOL_SPEC`, now both alias the one definition, keeping the
  fuller/more informative wording) and
  `edit_file_handler(root, worktree_path, inp)` (the shared core).
- **`app/agents/chat_agent.py`**: its real dispatch now calls
  `edit_file_handler` directly — no confirmation gate needed here (same
  as before: a unique old_string→new_string replacement is inherently
  safer than a full overwrite and is left ungated everywhere in this
  codebase).
- **`app/agents/tools.py`**: `_make_edit_file_handler` (reused by 4
  handler-set factories) and `make_chat_handlers`'s own `edit_file` now
  delegate to the shared function. `_EDIT_FILE_TOOL_SPEC` (used by 8
  separate tool lists) and `CODER_TOOLS`'s own duplicate schema entry
  now both alias the single canonical `EDIT_FILE_TOOL`.

**Deliberately left untouched** (audited, found already correctly
guarded):

- `make_coder_handlers`'s `edit_file`, `make_cleanup_agent_handlers`'s
  `cu_edit_file` — generic, already correct, left alone to avoid
  unnecessary rewrite of working/tested code with no outstanding issue.
- `make_dependency_agent_handlers`'s `dep_edit_file` — a real,
  intentional policy difference (dependency/requirements files only via
  `_DEP_EDITABLE`), not accidental duplication.
- `make_fleet_apply_handlers`'s `edit_file_h` — unlike `write_file`'s
  fleet_apply equivalent, this one's role-prompt and plain-file branches
  share the same count/replace logic across two different read sources
  (`prompt_registry` vs. disk) and two different write destinations
  (`_propose_and_deploy_role_prompt` vs. disk) — not a clean drop-in for
  the shared handler without a riskier restructure, for a comparatively
  small blast radius (4 agents). Already correctly guarded from tool
  #11's fix.

**One observable, intentional, low-risk change**: error message text on
two of the four consolidated call sites became slightly more detailed
(`_make_edit_file_handler`'s old_string-not-found/not-unique messages now
match the fuller wording chat_agent.py/make_chat_handlers already used).
Checked every test in the suite referencing these exact strings
beforehand — none existed.

## Tests (real, not mocked at the mechanism level)

`tests/test_edit_file_hardening.py` (new, 16 tests):

- Schema shape check.
- Direct unit tests of `edit_file_handler`: absolute-path rejection,
  `../` traversal rejection, `.env` denylist rejection, real in-repo edit
  proof, missing-file error, non-unique-old_string error,
  old_string-not-found error.
- Every consolidated call site exercised for real: `chat_agent.py`'s
  dispatch (happy path + escape rejection), `_make_edit_file_handler`,
  `make_chat_handlers`'s `edit_file`.
- A full security sweep proving all 4 deliberately-untouched
  implementations (coder, dependency_agent, cleanup_agent,
  fleet_apply) still correctly reject a real absolute path outside their
  repo.

## Regression

Targeted sweep (new test file + write_file/boundary-hardening tests from
tools #11/#12 + day1/day2 tool/agent tests + gap50 + new_tools/chat_tools):
**549 passed, 1 skipped.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

This tool's real vulnerability was already closed during tool #11's
audit; this turn verified every other real implementation was already
secure, then completed the mandatory modularization step for the generic
variant. No functionality lost.
