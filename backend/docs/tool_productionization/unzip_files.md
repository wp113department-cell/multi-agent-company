# Tool #206 — `unzip_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `unzip_files_h` inside `make_chat_handlers()`.
Exclusively a `CHAT_TOOLS` entry (membership count confirmed = 1);
grepped all other agent files — none reference `"unzip_files"` in
their own `allowed_tools`.

## Problems found

Three real, empirically-verified findings — a severe "arbitrary file
write" class primitive, worse than most `path`-only worktree-escape
findings this initiative because BOTH the read side (`archive`) and
the write side (`dest`) were uncontrolled.

1. **`dest` resolution was fully broken, not merely unvalidated — a
   genuine logic bug that also amounted to an arbitrary-directory-
   write primitive.** The original ternary,
   `dest_path = root / dest if not (root / dest).is_absolute() else
   Path(dest)`, is a tautology: `root` (the configured repo root) is
   always itself absolute, so `root / dest` is ALWAYS absolute
   regardless of `dest`'s own shape — `not (root / dest).is_absolute()`
   is ALWAYS `False`, and `dest_path` ALWAYS evaluated to `Path(dest)`,
   completely discarding `root` in every real call. Proved live two
   ways: (a) a relative `dest` (the schema's own documented common
   case) resolves against the process's cwd instead of the repo root
   — a real functional bug; (b) an absolute `dest` extracts a real
   archive's content to that exact absolute path with zero repo
   confinement — proved live with a real archive extracted completely
   outside the intended worktree.
2. **`archive` (the source zip) had zero worktree-boundary
   validation** — same class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#202/#203/#204.
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204.**

**Investigated and REFUTED, not treated as a finding**: classic "zip
slip" path-traversal via crafted archive entry names. Proved live
against this project's real Python 3.12.3 `zipfile.extractall()`: both
a `../../../../tmp/PWNED.txt`-shaped entry and a `/etc/PWNED.txt`-
shaped entry were correctly sanitized and confined inside the
destination directory — CPython's `zipfile` module has included this
protection since Python 3.6.4/2.7.15. Not a real vulnerability on this
real runtime; not fixed because there was nothing real to fix.

## Changes made

Extracted into `app/tools/filesystem/unzip_files.py`
(`UNZIP_FILES_TOOL`, `unzip_files_handler`): `archive` is validated
with `check_path_in_worktree()` before opening, closing finding #2;
`dest` is now correctly resolved against `root` when relative
(matching the schema's own documented contract) and then ALSO
validated with `check_path_in_worktree()` regardless of shape, closing
finding #1 both as a functional fix and a security fix. A new
`chat_agent.py` `_execute_tool()` dispatch delegates to this same
shared handler, closing finding #3.

## Tests

`tests/test_new_tools.py::test_zip_unzip` passed a relative
`dest="extracted"` and only ever asserted on the RETURNED STRING
content, never on the extracted file actually existing at the expected
location — a real, pre-existing coverage gap that would not have
caught the dest-resolution bug. Strengthened with a real assertion
(`(out_dir / "mydir" / "file.txt").exists()`) and re-run; passes
cleanly with the fix in place (it would have failed against the
original broken ternary, since `dest="extracted"` would have resolved
relative to the test process's cwd instead of `tmp_path`).

New file `tests/test_unzip_files_hardening.py`, 15 tests: schema
check, `CHAT_TOOLS` single-registration check, dest-resolution-bug
proofs (relative dest resolves against root, absolute-outside-worktree
dest blocked on all 3 real access paths, absolute-inside-worktree dest
still allowed), archive worktree-escape blocked, dispatch no longer
"Unknown tool", a zip-slip regression guard confirming the refuted
finding stays refuted, and legitimate-usage regression (real archive
extraction with nested directories, missing-archive error) verified
through both real access paths.

## Regression

This tool's own new hardening tests (15/15 pass) plus
`tests/test_new_tools.py` (49 total across both files, including the
strengthened `test_zip_unzip`). Also ran a broader chat_agent
regression sweep (`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_gap16_chat_agent_verification_gate.py`) — **19 passed**, 0
failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Three real findings (an arbitrary-directory-write
primitive from a broken dest-resolution ternary, a worktree-escape on
the archive source, and a completely non-functional interactive-chat
dispatch) identified and fixed; zip slip investigated and empirically
refuted rather than assumed safe or assumed vulnerable. No
functionality lost — a real, pre-existing test coverage gap was also
closed. Tool-specific and broader chat_agent regression tests clean.
Agent alignment verified: PASS (`chat_agent.py`'s dispatch and
`make_chat_handlers()`'s handler both now route through the one
shared, worktree-validated, dest-resolution-corrected implementation).
