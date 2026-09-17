# Tool #228 — `parse_merge_conflicts` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`parse_merge_conflicts` is in `CHAT_TOOLS` (confirmed via membership
check), with **two real, near-identical implementations** — the exact
same shape already found and fixed on sibling tool #136
(`explain_merge_conflict`): a closure inside `make_chat_handlers()` in
`app/agents/tools.py`, and `ChatAgent._execute_tool()`'s own separate
interactive dispatch branch in `app/agents/chat_agent.py`. Per this
initiative's established finding, the real caller for interactive chat
sessions is `chat_agent.py`'s own dispatcher, not the handlers dict.

Worktree-boundary validation was already correct on both — fixed
2026-08-17 during tool #11's (`undo_changes`) cross-cutting audit (per
this tool's own tracking-row note): the closure uses
`check_path_in_worktree(rel, repo_path)` directly, and `chat_agent.py`
uses `_is_protected_path(pmc_rel, repo)`, which itself delegates to
`check_path_in_worktree()` when given a worktree path. Re-verified live
below, not assumed.

Existing tests: 4 test files
(`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_file_ops_worktree_boundary_hardening.py`,
`test_gap51_merge_conflict_resolution.py`,
`test_tools_py_file_ops_worktree_boundary_hardening.py`) already cover
real-conflict parsing, clean-file handling, and worktree-escape
rejection — none of them exercised a genuinely missing `path` key or
an unreadable target file.

## Problems found

Two real findings, proved live against **both** implementations before
any fix:

1. `rel = str(inp["path"])` used bare dict indexing in both real call
   sites — a genuinely missing `path` key raised an uncaught
   `KeyError: 'path'`.
2. Neither implementation wrapped `target.read_text()` in a
   `try`/`except` — the same class already fixed for tools
   #70/#72/#76/#135/#136. Proved live with two separate crash inputs:
   ```
   path="adir" (a real directory)     → uncaught IsADirectoryError
   path="bad.bin" (invalid UTF-8 bytes) → uncaught UnicodeDecodeError
   ```

## Changes made

Extracted into `app/tools/git/parse_merge_conflicts.py`
(`PARSE_MERGE_CONFLICTS_TOOL`, `parse_merge_conflicts_handler`) —
**both real call sites now delegate to this one shared handler**,
matching tool #136's established consolidation pattern exactly. `path`
is now read via an explicit `if "path" not in inp: return "[ERROR]
path is required"` check, and the whole read+parse operation is
wrapped in `try`/`except`, returning `"[ERROR] Could not read {rel}:
{e}"` instead of raising.

`app/agents/tools.py`'s closure now reads
`return parse_merge_conflicts_handler(root, repo_path, inp)`.
`app/agents/chat_agent.py`'s dispatch now reads
`return await asyncio.to_thread(parse_merge_conflicts_handler, root,
repo, inp)` (the same `asyncio.to_thread` bridging pattern already
established for `explain_merge_conflict`'s dispatch, since
`_execute_tool` is async but the shared handler is sync). Also removed
the now-unused `_parse_conflict_markers` import from `chat_agent.py`
(its only remaining use in that file was the inline implementation
just replaced — `resolve_merge_conflict`'s dispatch uses the unrelated
`_apply_conflict_resolutions`, confirmed still used).

## Tests

Existing tests across 4 files (67 tests) re-run and confirmed passing
unchanged.

New file `tests/test_parse_merge_conflicts_hardening.py`, 11 tests:
schema check, `CHAT_TOOLS` membership, the missing-`path`-key proof,
the directory-path proof, the invalid-UTF-8-file proof, a
worktree-escape-still-blocked regression, real-conflict-parses and
clean-file and missing-file legitimate-usage regressions, and two
direct proofs that BOTH real call sites (the `tools.py` closure and
`chat_agent.py`'s dispatch) delegate to and produce byte-identical
output from the exact same shared handler.

## Regression

This tool's own new hardening tests (11/11 pass) plus the 4 existing
test files (67 tests) + `test_new_tools.py` + `test_final_session.py`
+ `test_explain_merge_conflict_hardening.py` (150 passed total), plus
a broader `chat_agent.py`-adjacent sweep since this turn touched that
file's imports and dispatch table —
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_chat_agent_memory_wiring.py`,
`test_gap16_chat_agent_verification_gate.py`,
`test_audit_q_batch07_guardian_human_interaction.py`,
`test_ask_human_to_choose_hardening.py` (49 passed).

Verified via `mypy` (3 touched files, clean) and `ruff check` (3
touched files, clean — including catching and removing the now-unused
`_parse_conflict_markers` import) BEFORE claiming GREEN_FLAG. Also
verified `CHAT_TOOLS` still has zero duplicate names (186 entries) and
that `app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Two real, empirically-verified defects found and fixed
via evidence (live reproduction against both implementations before
the fix, live proof of clean error strings and byte-identical output
after consolidation). Genuine duplication eliminated — both real call
sites now provably delegate to one shared, tested handler, matching
established precedent from sibling tool #136. No functionality lost —
legitimate conflict parsing, clean-file reporting, and worktree-escape
rejection all re-verified correct. Agent alignment verified: PASS.
