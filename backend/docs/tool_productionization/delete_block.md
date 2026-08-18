# Tool #33 — `delete_block` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only ONE real implementation existed: `delete_block_h` inside
`make_chat_handlers()`. Like tools #22/#25/#32, `chat_agent.py` had **no
dispatch branch at all** despite `delete_block` being advertised in
`CHAT_TOOLS`.

## Problems found

**"Advertised but never dispatched"** — the same bug class as tools
#22/#25/#32 (`git_tag`/`semver_bump`/`create_branch`). Verified directly:
a real `ChatAgent._execute_tool("delete_block", ...)` call returned the
generic `"[ERROR] Unknown tool: delete_block"` fallback.

The existing implementation's worktree-boundary check was already
correct (`_is_protected_path(path, repo_path)`) — re-verified directly
this turn (a real `.env` target and a real absolute path outside the
repo are both still rejected), not assumed.

## Deferred finding (not fixed this turn — documented, not silently
dropped)

`start_pattern`/`end_pattern` are LLM-controlled regexes passed straight
to `re.search()` once per line, with no timeout. Python's stdlib `re`
module has no built-in ReDoS (catastrophic backtracking) protection, and
unlike every subprocess-based grep-pattern tool elsewhere in this
codebase (which at least has a hard subprocess timeout as a backstop),
an in-process `re.search()` call has no such backstop — a sufficiently
pathological pattern against a sufficiently long line could hang the
worker thread indefinitely. **Not fixed here** because a real fix (a
genuine regex-execution timeout) has no clean stdlib primitive in Python
and would need either a separate-process/thread-with-timeout wrapper or
a third-party dependency — real design work belonging to its own turn,
not a one-line addition alongside a dispatch-wiring fix. Logged here
rather than silently ignored.

## Changes made

- **`app/tools/filesystem/delete_block.py`** (new): `DELETE_BLOCK_TOOL`
  (schema, unchanged) and `delete_block_handler(root, worktree_path,
  inp)` — the existing, already-correct logic, extracted so both real
  call sites share one implementation.
- **`app/agents/chat_agent.py`**: gained a real dispatch branch for
  `delete_block` for the first time, delegating to the shared handler.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `delete_block_h`
  now delegates to the shared function.

## Tests (real, not mocked at the mechanism level)

`tests/test_delete_block_hardening.py` (new, 9 tests):

- Schema shape check.
- **The proven gap, verified closed**: a real call through
  `ChatAgent._execute_tool` no longer returns "Unknown tool" and
  produces the real, correct deletion result.
- Worktree-boundary re-verification: a real `.env` target and a real
  absolute path outside the repo both rejected.
- Regression: a real block deletion with the exact expected remaining
  content, a "pattern not found" warning that leaves the file untouched,
  a missing-file error, and the same real deletion through both
  `chat_agent.py`'s dispatch and `make_chat_handlers`.

## Regression

Targeted sweep (new test file + day2_tools + create_branch hardening):
**108 passed, 1 skipped.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live "advertised but never dispatched" gap closed by wiring up
the already-correct existing implementation. One real, lower-priority
finding (ReDoS exposure via unbounded `re.search`) explicitly deferred
with reasoning, not silently dropped. No functionality lost.
