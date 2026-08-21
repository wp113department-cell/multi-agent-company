# Tool #56 — `rename_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, already near-identical (differing only by a
trailing period and a try/except wrapper):

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `rename_file`.

Both already call `_is_protected_path(from_path, repo_path)` AND
`_is_protected_path(to_path, repo_path)`, with `repo_path` passed as
`worktree_path` — enabling full `check_path_in_worktree()` containment
checking on BOTH sides. This is tool #11's fix, applied here
(2026-08-17), confirmed still present and re-verified live (rejects an
absolute outside-repo path on either field, and a protected filename
like `.env`). `CHAT_TOOLS.count("rename_file") == 1` verified — no
duplicate-advertisement risk.

## Problems found

**No new security vulnerability** — both fields' worktree/protected-
path handling was already correct on both real call sites.

The real, actionable work was pure modularization/consolidation: the
two previously independently-maintained, near-identical copies of this
handler are now one shared function, closing the risk of them silently
drifting apart in the future (the exact failure mode multiple earlier
tools in this initiative found between their own real implementations).

## Changes made

- **`app/tools/filesystem/rename_file.py`** (new): `RENAME_FILE_TOOL`
  (schema, unchanged) and `rename_file_handler(root, worktree_path,
  inp)` — the shared implementation, validating both `from_path` and
  `to_path`.
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: both real
  call sites now delegate to the shared handler instead of maintaining
  two independent, near-identical copies.

## Tests (real, not mocked — real files on disk, real reads/writes)

`tests/test_rename_file_hardening.py` (new, 9 tests):

- Schema shape check, and confirms `rename_file` appears in
  `CHAT_TOOLS` exactly once.
- **Worktree-boundary protection, re-verified live on both call
  sites**: an outside-repo `from_path` rejected (nothing created), an
  outside-repo `to_path` rejected (original file untouched), and a
  protected filename (`.env`) rejected.
- Regression: a real in-repo rename (confirmed via the source no
  longer existing and the destination holding the exact original
  content), a real move across subdirectories (destination directory
  auto-created), and a clean `[ERROR]` for a nonexistent source.

Also swept 2 pre-existing test files referencing `rename_file`
(`test_file_ops_worktree_boundary_hardening.py`,
`test_batch11_policy_check_structural_chokepoint.py`) — both confirmed
still passing (43 tests total).

## Regression

Targeted sweep (new test file + pip_install + npm_run hardening): **22
passed.** Full suite re-run after this pass: **5292 passed, 52
skipped, 18 deselected, 0 failed** (up from 5283 before this tool).

## Final verdict

**GREEN FLAG.**
