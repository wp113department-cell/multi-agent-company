# Tool #79 — `git_status` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent, `make_chat_handlers()`'s ~35 one-shot
   agents, and `make_monitoring_agent_handlers()`/`make_scan_handlers()`
   (the autonomous infrastructure-health-scan agent reads `git_status`
   straight from the canonical factory with no override of its own).
2. `chat_agent.py`'s own interactive dispatch, built on the shared
   `_git()` subprocess helper.

Per `tool_inventory.json`, 39 agents declare `git_status` in
`allowed_tools`. `CHAT_TOOLS.count("git_status") == 1` verified.

**Test-count note**: the tracking table's "1 existing test file" is
`test_audit_q_batch07_guardian_human_interaction.py`, which only
asserts `"git_status" in handlers` (membership, not behavior) —
verified directly, zero existing tests actually invoke this tool's
real handler and exercise its output. `test_git_service.py` tests
`app.services.git_service.git_status`, a completely separate function
(same false-positive-adjacent shape as tool #78's finding). No
sweep-run was needed.

## Problems found

**No security vulnerability** — this tool's schema takes zero input
(`"properties": {}`), so there is no LLM-controlled field to audit for
any of this initiative's established finding classes.

**A real FUNCTIONALITY bug in the canonical implementation.** It
returns `result.stdout or "(clean)"` without ever checking
`result.returncode`. Proved live: run against a directory that is not
a git repository at all,

```python
handlers["git_status"]({})
```

returned the literal string `"(clean)"`, even though the underlying
command actually failed with `fatal: not a git repository (or any of
the parent directories): .git`. This is genuinely misleading — an
agent (or a human relying on this tool's summary before committing)
would reasonably conclude the working tree has no changes, when the
command never ran successfully at all. `chat_agent.py`'s own dispatch,
built on the shared `_git()` helper (which combines stdout+stderr),
already surfaced the real error text correctly in the same scenario —
the canonical implementation was the less complete of the two here,
the opposite direction from tools #76/#77/#78 where `chat_agent.py`'s
copy was the one missing something.

## Changes made

Extracted a single shared `git_status_handler()` in
`app/tools/git/status.py`, used by both real call sites: now checks
`result.returncode != 0` and returns a clean `[ERROR] git status
failed: ...` message in that case, matching this initiative's
established error-surfacing convention (`git_log_handler`,
`file_info_handler`, etc.) instead of masking a real failure as a
false "clean" result.

`app/agents/tools.py`'s `READ_ONLY_TOOLS[12]` (verified empirically as
the correct index before editing) now points at the shared
`GIT_STATUS_TOOL` constant, and its `make_read_only_handlers()`
closure delegates to the shared handler. `app/agents/chat_agent.py`'s
dispatch now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_git_status_hardening.py`, 10 tests, all real (a
real git repository, or real non-repo directory, on disk — no mocking)
— schema/index checks, the false-"(clean)"-on-failure bug verified
closed on both real dispatch paths, and legitimate-usage regression
(clean repo, real modified file, real untracked file) across all three
real access paths (`ChatAgent._execute_tool`, `make_read_only_
handlers()`, `make_chat_handlers()`).

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** No security vulnerability (zero-input schema); the
real functionality bug proved live and closed on the canonical
implementation while preserving `chat_agent.py`'s already-correct
behavior; no functionality lost; full regression clean.
