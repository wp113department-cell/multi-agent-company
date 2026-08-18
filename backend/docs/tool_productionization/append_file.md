# Tool #26 — `append_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch — the only agent that
   actually declares this tool (`agent_count: 1` in
   `tool_inventory.json`).
2. `make_chat_handlers()`'s own `append_file` — unreachable by any real
   one-shot agent today (none declare it in `allowed_tools`), kept for
   defense-in-depth/consistency, matching this initiative's own
   precedent for tools.py handlers with no current real caller.

## Problems found

**None new.** The worktree-boundary check was already fixed for both
implementations during tool #11's cross-cutting audit — re-verified
directly this turn (a real absolute path outside the repo and a real
`.env` denylist case are both still rejected), not assumed.

One minor, non-security observation: `chat_agent.py`'s dispatch had no
`try`/`except` around the actual write, unlike `make_chat_handlers`'s
own copy. Confirmed this was never a live crash risk — a top-level
`except Exception` in `ChatAgent._execute_tool_node` (read directly)
already catches any exception and surfaces it as a clean
`[ERROR] Tool ... failed: ...` string. Still folded the `try`/`except`
into the shared handler for a more specific, tool-authored error message
on a real disk error, matching what `make_chat_handlers`'s own
implementation already did.

## Changes made

- **`app/tools/filesystem/append_file.py`** (new): `APPEND_FILE_TOOL`
  (schema, unchanged) and `append_file_handler(root, worktree_path, inp)`
  — the shared core, both implementations' logic merged (they were
  already nearly identical).
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now delegate to the shared function.

## Tests (real, not mocked at the mechanism level)

`tests/test_append_file_hardening.py` (new, 10 tests):

- Schema shape check.
- Worktree-boundary re-verification: absolute path outside the repo,
  `.env` denylist.
- Regression: file creation on first append, appending to an existing
  file, parent-directory auto-creation, a real disk-error path (writing
  under a file that can't be a parent directory) proving the try/except
  works, and both real call sites (`chat_agent.py`'s dispatch and
  `make_chat_handlers`) exercised directly for real appends and a real
  escape rejection.

## Regression

Targeted sweep (new test file + file_ops boundary hardening + semver_bump
hardening): **54 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

No new vulnerability — this tool's real fix landed during tool #11.
This turn completed the mandatory modularization and closed a minor
error-message-quality gap. No functionality lost.
