# Tool #213 — `git_commit_change` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the `make_git_commit_change_handler()`
factory in `app/agents/tools.py`. Exactly 4 real agents, confirmed via
direct grep — `agent_debugger`, `knowledge_curator`, `quality_auditor`,
`agent_performance_reviewer` — matching `tool_inventory.json`'s
`agent_count: 4` exactly (this tool's inventory metadata was accurate,
unlike several `NO_MANIFEST` siblings audited earlier in this
initiative). Deliberately NOT in `CHAT_TOOLS` — confirmed via
membership check; this is the APPLY-phase-only, human-approval-gated
counterpart to `git_commit` (tool #37), not exposed to interactive
chat.

This tool is notable as the **reference implementation another tool
was fixed to match**: tool #37's (`git_commit`) own docstring cites it
directly — *"This codebase already has the exact right protection
built and proven elsewhere: `make_git_commit_change_handler`'s
`git_commit_change`... already calls `check_path_in_worktree()` per
file and `_scan_content_for_secrets()` on each file's content before
ever running `git commit`"* — and `git_commit`'s own fix was
explicitly modeled on this tool's contract, not a new one invented
for it.

## Audit (checked directly, not assumed safe from that reputation)

- Every file in `files` is validated with `check_path_in_worktree()`
  before anything else — a real worktree-escape rejection, re-verified
  live.
- Every in-worktree file's real on-disk content is scanned with
  `_scan_content_for_secrets()` before staging — a real secret-to-
  history-leak guard, the exact protection `git_commit` (tool #37) was
  missing and had to add. Re-verified live: a real AWS-key-shaped
  secret in `.env` is refused, and `git log` confirms it never reached
  history.
- `git add -- <files>` already uses the `--` pathspec separator (the
  same flag-collision protection tool #37 had to add, same class as
  tools #5/#32/#35/#36) — re-verified live: a flag-shaped file entry
  (`-u`) is rejected as an error rather than silently widening staging
  scope to all tracked modifications.
- `message` reaches `git commit -m <message>` as a single, separate
  argv element with no `shell=True` — re-verified live: a message
  starting with `--` is committed as a literal message, never
  reinterpreted as a flag.
- A theoretical `Path.is_file()` exception risk on an edge-case path
  was checked directly against this Python version's real `pathlib`
  behavior — it catches the underlying `OSError` internally and
  returns `False` rather than raising, so this is not a real crash
  risk.

## Problems found

None. No security vulnerability and no functional bug found.

## Changes made

Extracted into `app/tools/git/commit_change.py`
(`GIT_COMMIT_CHANGE_TOOL`, `make_git_commit_change_handler`) with zero
behavior change. `app/agents/tools.py` re-exports the schema and
factory under their old names (self-aliasing imports, matching the
established pattern for widely-shared re-exports) — all 4 real
consumer files continue `from app.agents.tools import
make_git_commit_change_handler` completely unchanged.

## Tests

3 existing test files already exercise this tool
(`tests/test_tools_py_file_ops_worktree_boundary_hardening.py`,
`tests/test_git_commit_hardening.py`, `tests/test_day9_fleet_agents.py`
— `tool_inventory.json`'s "0 test files" is a heuristic false
negative) — all re-run and confirmed passing unchanged (5 tests).

New file `tests/test_git_commit_change_hardening.py`, 9 tests: schema
check, confirmation it is correctly absent from `CHAT_TOOLS`, live
re-verification of all three already-correct protections (worktree
escape, secret-content scan, flag-collision via the `--` separator)
against real git repositories, a real proof a leading-dash commit
message is treated literally, and legitimate-usage regression (missing
files/message errors, a real commit that only touches the named file).

## Regression

This tool's own new hardening tests (9/9 pass) plus the 5 existing
tests across 3 files. Also directly `importlib`-reload-verified all 4
real consumer agent modules (`agent_debugger`, `knowledge_curator`,
`quality_auditor`, `agent_performance_reviewer`) still import cleanly
and resolve the re-exported factory correctly.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), a `ruff check` on all touched files (clean),
a `CHAT_TOOLS` duplicate-registration check (clean), and
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No security or functional defect found — this tool
was already correctly built and served as the reference implementation
for fixing a sibling tool (`git_commit`, #37). Modularized for
structural consistency only, with zero behavior change. Tool-specific
and existing regression tests clean. Agent alignment verified: PASS
(all 4 real consumer agents independently re-confirmed via live
`importlib` reload).
