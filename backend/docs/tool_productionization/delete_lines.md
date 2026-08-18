# Tool #34 — `delete_lines` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch — the only agent that
   actually declares this tool.
2. `make_chat_handlers()`'s own `delete_lines` — reachable by any other
   agent declaring this tool.

## Problems found

**None new.** The worktree-boundary check was already fixed for both
implementations during tool #11's cross-cutting audit — re-verified
directly this turn (a real absolute path outside the repo and a real
`.env` denylist case are both still rejected), not assumed. The two
implementations were already nearly identical (only the invalid-range
error message's wording differed — "Invalid range" vs "Invalid line
range") — merged onto one shared handler using the more descriptive
wording.

## Changes made

- **`app/tools/filesystem/delete_lines.py`** (new): `DELETE_LINES_TOOL`
  (schema, unchanged) and `delete_lines_handler(root, worktree_path,
  inp)` — the shared core, both implementations' logic merged.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`**: both real
  call sites now delegate to the shared function.

## Tests (real, not mocked at the mechanism level)

`tests/test_delete_lines_hardening.py` (new, 11 tests):

- Schema shape check.
- Worktree-boundary re-verification: absolute path outside the repo,
  `.env` denylist.
- Regression: a real middle-range deletion with exact expected remaining
  content, an invalid range (end before start) rejected without
  touching the file, a zero/negative start line rejected, a start line
  beyond the file's length errors cleanly, an end line beyond the file's
  length correctly clamps instead of erroring, a missing-file error, and
  both real call sites (`chat_agent.py`'s dispatch and
  `make_chat_handlers`) exercised directly for real deletions.

## Regression

Targeted sweep (new test file + chat_tools + file_ops boundary
hardening + delete_block hardening): **183 passed.** Full suite re-run
after this pass — see `tool_enhance_tracking.md`'s row for this tool for
the final count.

## Final verdict

**GREEN FLAG.**

No new vulnerability — this tool's real fix landed during tool #11.
This turn completed the mandatory modularization. No functionality lost.
