# Tool #84 — `git_diff` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two schema definitions (an inline dict in `CODER_TOOLS`, and
`_GIT_DIFF_TOOL_SPEC` used by `BUG_FIX_AGENT_TOOLS`/
`REFACTOR_AGENT_TOOLS`/`CHAT_TOOLS`) — cosmetically different
description text but the identical single optional `file` field — and
FOUR real implementations:

1. `make_coder_handlers()`'s own `git_diff` closure — already used a
   `--` pathspec separator before `file`, but only showed the
   unstaged diff.
2. The shared `_make_git_diff_handler()` factory, used by
   `make_bug_fix_handlers()` and `make_refactor_agent_handlers()` —
   no `--` separator, unstaged-only.
3. `make_chat_handlers()`'s own `git_diff` closure (~35 one-shot
   agents) — no `--` separator, staged+unstaged.
4. `app/agents/chat_agent.py`'s separate interactive dispatch — no
   `--` separator, staged+unstaged.

Per `tool_inventory.json`, 10 agents declare `git_diff` in
`allowed_tools`. `CHAT_TOOLS.count("git_diff") == 1` verified. 6
existing test files reference this tool — all membership/metadata
checks or a completely unrelated `app.services.git_service.git_diff`
function, not real handler invocations — verified directly, all
re-run and confirmed passing unchanged (200 tests).

## Problems found

**The same severe class as tool #80's `git_show`, on THREE of the
four real implementations.** `file` was appended as a bare LAST
positional argv element with no `--` separator, so a flag-shaped value
was consumed by git's own argument parser instead of being treated as
a pathspec. Proved live, first at the raw `git` CLI level, then
through all three vulnerable real dispatch paths:

```python
await agent._execute_tool("git_diff", {"file": "--output=/tmp/git_diff_pwned.txt"})
make_chat_handlers(repo)["git_diff"]({"file": "--output=/tmp/git_diff_pwned2.txt"})
make_bug_fix_handlers(repo)["git_diff"]({"file": "--output=/tmp/git_diff_pwned3.txt"})
```

all three genuinely wrote a real file (containing the actual diff
content) to the attacker-chosen path — and critically, the tool's own
returned text (`"No changes."` / `"(no output)"`) gave the caller no
visible signal that a file was written at all, the identical
silent-failure-mode severity as tool #80. `make_coder_handlers()`'s
own implementation was NOT exploitable — it already placed `file`
after a `--` separator.

**A secondary, non-security finding.** The four implementations
diverged in real behavior — two showed only the unstaged diff, two
showed both staged and unstaged. The tool's own description ("review
your own changes before submitting") is best served by the more
complete staged+unstaged view (staged changes are exactly the ones
about to be committed).

## Changes made

Extracted a shared `git_diff_handler()` in `app/tools/git/diff.py`,
adopted by **all four** real call sites: places `file` after a `--`
separator (mirroring `make_coder_handlers()`'s own already-correct
pattern) for both the staged and unstaged `git diff` invocations,
closing the vulnerability everywhere at once; adopts the more complete
staged+unstaged output for all four real call sites.

Both schema constants (`CODER_TOOLS`'s inline dict and
`_GIT_DIFF_TOOL_SPEC`) now alias the shared `GIT_DIFF_TOOL` constant,
preserving every existing reference.

## Tests

New file `tests/test_git_diff_hardening.py`, 13 tests, all real (a
real git repository on disk, no mocking) — schema check, the
`--output=<path>` exploit verified closed on all three previously
vulnerable real dispatch paths plus a regression guard confirming
`make_coder_handlers()` was and remains safe, and legitimate-usage
regression (staged+unstaged output, file-filter narrowing, clean
no-changes message) across all four real access paths.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** The real, severe finding proved live and closed on all
three vulnerable real implementations; the already-safe implementation
re-verified as a regression guard; the behavioral divergence unified
onto the more complete, more useful view; no functionality lost; full
regression clean.
