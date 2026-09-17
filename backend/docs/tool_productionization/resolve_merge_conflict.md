# Tool #229 — `resolve_merge_conflict` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`resolve_merge_conflict` is in `CHAT_TOOLS` (confirmed via membership
check), with **two real, near-identical implementations** — the exact
same shape already found and fixed on sibling tools #136
(`explain_merge_conflict`) and #228 (`parse_merge_conflicts`): a
closure inside `make_chat_handlers()` in `app/agents/tools.py`, and
`ChatAgent._execute_tool()`'s own separate interactive dispatch branch
in `app/agents/chat_agent.py`.

Worktree-boundary validation was already correct on both — fixed
2026-08-17 during tool #11's cross-cutting audit (per this tool's own
tracking-row note), re-verified live below.

Existing tests: `test_gap51_merge_conflict_resolution.py`,
`test_file_ops_worktree_boundary_hardening.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py` cover the
underlying `_apply_conflict_resolutions` parsing/resolution logic and
worktree-escape rejection thoroughly — none exercised a genuinely
missing `path`/`index` key, a malformed `index`, or an unreadable
target file.

## Problems found

**Four** real, separate uncaught-crash paths, proved live against
**both** implementations before any fix — worse than sibling tool
#228's two:

1. `rel = str(inp["path"])` used bare dict indexing — a genuinely
   missing `path` key raised an uncaught `KeyError: 'path'`.
2. `idx = int(entry["index"])` inside the resolutions loop **also**
   used bare dict indexing — a resolution entry genuinely missing its
   `index` key raised an uncaught `KeyError: 'index'`.
3. The same `int(entry["index"])` coercion had no guard against a
   malformed value — `{"index": "not-a-number", "choice": "ours"}`
   raised an uncaught `ValueError`.
4. Neither implementation wrapped `target.read_text()` (nor
   `target.write_text()`) in a `try`/`except` — a directory passed as
   `path` raised an uncaught `IsADirectoryError`.

All four proved live via a direct end-to-end `ChatAgent._execute_tool()`
call before any code change.

## Changes made

Extracted into `app/tools/git/resolve_merge_conflict.py`
(`RESOLVE_MERGE_CONFLICT_TOOL`, `resolve_merge_conflict_handler`) —
**both real call sites now delegate to this one shared handler**,
matching tools #136/#228's established consolidation pattern exactly.
`path` is read via an explicit presence check; each resolution entry's
`index` is read via `.get()`-equivalent presence check inside its own
`try`/`except (TypeError, ValueError)`, returning a clean,
hunk-specific error naming which entry failed; and the whole
read+apply+write operation is wrapped in `try`/`except`, returning
`"[ERROR] Could not resolve conflicts in {rel}: {e}"` instead of
raising.

Also removed now-genuinely-dead re-exports: `_apply_conflict_resolutions`
and `_parse_conflict_markers` were self-aliased imports in
`app/agents/tools.py` (`... as _apply_conflict_resolutions`) that
existed solely so `chat_agent.py` could import them from there — with
both dispatch branches now delegating to shared handlers instead of
inlining this logic, neither is imported by any real code anymore
(confirmed via a full AST-based repo scan, not just grep). One existing
test, `tests/test_gap51_merge_conflict_resolution.py`, imported both
directly from `app.agents.tools` as its own test scaffolding — caught
immediately when removing the re-exports broke test collection, fixed
by pointing that import at the functions' actual home,
`app.agents.conflict_resolution`, with zero behavior change to the
tests themselves.

## Tests

Existing tests across 3 files re-run and confirmed passing unchanged
(after the one import fix above).

New file `tests/test_resolve_merge_conflict_hardening.py`, 14 tests:
schema check, `CHAT_TOOLS` membership, all 4 crash-path proofs
(missing `path`, missing `index`, malformed `index`, directory
`path`), a worktree-escape-still-blocked regression, real
`ours`/`theirs` resolution correctness (verifying actual file
contents after resolution, not just the return message),
`custom`-without-`custom_content` rejection, empty-`resolutions`
rejection, missing-file rejection, and two direct proofs that both
real call sites delegate to the shared handler.

## Regression

This tool's own new hardening tests (14/14 pass) plus the 3 existing
test files + `test_parse_merge_conflicts_hardening.py` +
`test_explain_merge_conflict_hardening.py` + `test_new_tools.py` +
`test_final_session.py` (164 passed total), plus a broader
`chat_agent.py`-adjacent sweep since this turn touched that file's
imports and dispatch table again — 49 passed.

Verified via `mypy` (3 touched files, clean) and `ruff check` (3
touched files, clean — including catching and removing the now-unused
`_apply_conflict_resolutions` import from `chat_agent.py` and both
now-dead re-exports from `tools.py`) BEFORE claiming GREEN_FLAG. Also
verified `CHAT_TOOLS` still has zero duplicate names (186 entries) and
that `app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Four real, empirically-verified defects found and
fixed via evidence (live reproduction against both implementations
before the fix, live proof of clean error strings and correct
real-file resolution after consolidation). Genuine duplication
eliminated — both real call sites now provably delegate to one shared,
tested handler. A real regression from this turn's own dead-code
cleanup was caught and fixed before claiming done. No functionality
lost — legitimate hunk resolution (`ours`/`theirs`/`custom`),
unresolved-hunk reporting, and worktree-escape rejection all
re-verified correct. Agent alignment verified: PASS.
