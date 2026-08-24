# Tool #80 — `git_show` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations, functionally identical:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()`'s ~35
   one-shot agents.
2. `chat_agent.py`'s own interactive dispatch — same logic, built
   directly on `subprocess.run` rather than the shared `_git()` helper.

Per `tool_inventory.json`, 38 agents declare `git_show` in
`allowed_tools`. `CHAT_TOOLS.count("git_show") == 1` verified. No
existing tests referenced `git_show` at all beyond two comment
mentions (`test_phase4_item5_git_awareness.py`,
`test_phase63_prompt_injection_defense.py`) — verified directly,
matching the tracking table's "0" figure.

## Problems found

**The MOST SEVERE finding in the low-risk tier so far, on BOTH
implementations (identical root cause): a silent, genuine
arbitrary-file-write primitive via git's own `--output=<path>`
flag.** Same flag-collision root cause as tools #5/#32/#35/#36/#38/
#39/#40 (a bare LLM-controlled positional argv element with no `--`
separator, consumed by the external program's own flag parser when it
starts with `-`), but with a far more dangerous flag on the receiving
end than any prior occurrence of this class: `git show` (and the `git
log` family it shares diff options with) accepts `--output=<file>`,
which redirects the command's own output to an arbitrary file path
chosen entirely by the attacker-controlled `ref` value.

Proved live, first at the raw `git` CLI level, then through both real
tool dispatch paths:

```python
await agent._execute_tool("git_show", {"ref": "--output=/tmp/git_show_pwned.txt"})
handlers["git_show"]({"ref": "--output=/tmp/git_show_pwned.txt"})
```

both genuinely wrote a real file (containing the current HEAD commit's
message, author, date, and diffstat) to the attacker-chosen path — and
critically, the tool's own returned text was `"(no output)"` / `""`,
giving the caller (LLM or human observer of the transcript) **no
visible signal that a file was written to the host filesystem at
all**. This is a strictly worse failure mode than a visible primitive.
Any path the backend process's OS user can write to is in scope — not
limited to the repo worktree, since this bypasses Python's own
filesystem I/O entirely and goes through git's own diff-output
redirection instead, so none of this initiative's
`check_path_in_worktree()` fixes would even have applied here — a
genuinely different code path than every worktree-escape finding so
far.

## Changes made

Extracted a shared `validate_git_show_ref()` + `git_show_handler()` in
`app/tools/git/show.py`, used by both real call sites:
`validate_git_show_ref()` rejects any `ref` starting with `-` outright,
mirroring the tools #5/#32/#35/#36/#38/#39/#40 precedent
(allowlist-by-exclusion, since enumerating every dangerous
git-show/git-log-family flag is not tractable — `--output` was merely
the most obviously severe one found; this closes the entire class in
one shot, not just this one flag).

`app/agents/tools.py`'s `READ_ONLY_TOOLS[13]` (verified empirically as
the correct index before editing) now points at the shared
`GIT_SHOW_TOOL` constant, and its `make_read_only_handlers()` closure
delegates to the shared handler. `app/agents/chat_agent.py`'s dispatch
now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_git_show_hardening.py`, 12 tests, all real (a
real git repository on disk, no mocking) — schema/index checks,
`validate_git_show_ref()` direct unit checks, the `--output=<path>`
exploit verified closed on both real dispatch paths (asserting the
target file genuinely does not exist after the call), other
flag-shaped refs rejected, and legitimate-usage regression across all
three real access paths (`ChatAgent._execute_tool`,
`make_read_only_handlers()`, `make_chat_handlers()`).

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** The real, severe finding proved live and closed on
both real implementations; no functionality lost; full regression
clean.
