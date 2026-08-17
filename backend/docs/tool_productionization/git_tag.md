# Tool #22 — `git_tag` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only ONE real implementation existed: `git_tag_h` inside
`make_chat_handlers()`. Unlike every other tool in this initiative,
`chat_agent.py` had **no dispatch branch for `git_tag` at all** — despite
`git_tag` being advertised to the interactive chat LLM via `CHAT_TOOLS`
(chat_agent's own tool list).

## Problems found (real, empirically verified)

**"Advertised but never dispatched"** — the same bug class already found
and fixed for `npm_install`/`pip_install` (tool #4) and
`github_create_pr` (tool #6). Verified directly: a real
`ChatAgent._execute_tool("git_tag", ...)` call returned the generic
`"[ERROR] Unknown tool: git_tag"` fallback. Any time the interactive
agent's own LLM decided to use a tool it was explicitly told it had, the
call silently failed.

**Checked (not assumed) for the tool #5-class flag-collision bug**:
`git_reset`'s real vulnerability was a flag-shaped value (`ref="--hard"`)
silently changing behavior. Tested the equivalent here — a flag-shaped
tag `name` (`"--force"`) — against a real repo. Unlike `git_reset`, git
itself refuses a flag-shaped tag name outright (exit 129, clean usage
error) rather than doing anything silently dangerous. No fix needed for
this angle; the existing `[ERROR] {stderr}` surfacing already handles it
correctly.

The existing `make_chat_handlers` implementation itself was already safe
on every other count — list-args `subprocess.run`, no `shell=True`, so
no shell-injection surface regardless of `name`/`message` content.

## Changes made

- **`app/tools/git/tag.py`** (new): `GIT_TAG_TOOL` (schema, unchanged)
  and `git_tag_handler(repo_path, inp)` — the existing, already-correct
  logic, extracted so both real call sites share one implementation.
- **`app/agents/chat_agent.py`**: gained a real dispatch branch for
  `git_tag` for the first time, delegating to the shared handler.
- **`app/agents/tools.py`**: `make_chat_handlers`'s own `git_tag_h` now
  delegates to the shared function.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_tag_hardening.py` (new, 7 tests):

- Schema shape check.
- **The proven gap, verified closed**: a real call through
  `ChatAgent._execute_tool` no longer returns "Unknown tool" and produces
  the real, correct result.
- **The flag-collision check**: a flag-shaped tag name is refused
  cleanly, with no tag created under any name as a side effect.
- Regression: a full real create → list → delete lifecycle through
  `chat_agent.py`'s new dispatch, a lightweight (no-message) tag
  creation, an unknown-action error, and the same lifecycle through
  `make_chat_handlers`.

## Regression

Targeted sweep (new test file + audit_q_batch14 + docker_restart
hardening): **41 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, live "advertised but never dispatched" gap closed by wiring up
the already-correct existing implementation — no new logic needed beyond
extraction and a dispatch branch. No functionality lost.
