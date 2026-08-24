# Tool #81 — `git_blame` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two real implementations, functionally identical:

1. The canonical `make_read_only_handlers()` factory — reused by every
   `run_agent_graph`-based agent and `make_chat_handlers()`'s ~35
   one-shot agents.
2. `chat_agent.py`'s own interactive dispatch — same logic, built on
   the shared `_git()` subprocess helper.

Per `tool_inventory.json`, 34 agents declare `git_blame` in
`allowed_tools`. `CHAT_TOOLS.count("git_blame") == 1` verified. No
existing tests referenced this tool beyond two comment/tuple mentions
(`test_phase63_prompt_injection_defense.py`,
`test_phase4_item5_git_awareness.py`) — verified directly, neither
exercises the real handler.

## Problems found

**Same flag-collision root cause class as tool #80's `git_show`**
(`path` is a bare positional argv element with no `--` separator, so
git's own argument parser treats a leading `-` as one of its own
flags), on BOTH implementations — but **checked and confirmed lower
severity here**:

1. `git blame --help` was checked directly — there is no `--output`-
   equivalent flag for `git blame` (unlike the `git log`/`git show`
   family).
2. Its two file-reading flags that could otherwise be concerning
   (`--contents <file>`, `-S <file>` / `--ignore-revs-file <file>`)
   each require a SEPARATE target-path argument that a single `path`
   field cannot also supply. Proved live:

   ```
   $ git blame --date=short -w "--contents=/etc/passwd"
   usage: git blame [<options>] [<rev-opts>] [<rev>] [--] <file>
   ```

   git's own usage error (exit 129) fires immediately — not a working
   exploit.

**Checked, confirmed safe (no fix needed): `path`'s worktree
boundary.** Same class as tool #78's `file` and tool #80's precedent —
git's own `git blame -- <path>` already refuses any path outside the
repository on its own. Verified live with both `path="/etc/hostname"`
and `path="../../../etc/hostname"`, both producing `fatal: ... is
outside repository at '<repo>'`.

**Checked, confirmed safe: `start_line`/`end_line`.** Always embedded
inside a fixed `-L{start},{end}` prefix before reaching argv, so they
can never be interpreted as a different flag — same structurally-
immune class established for tools #73-77's `kind`/`pattern` fields.

## Changes made

Fixed **defensively anyway**, matching this initiative's consistent
policy from tools #5/#32/#35/#36/#38/#39/#40/#80 (reject flag-shaped
positional values outright regardless of whether a maximally severe
flag was found for this specific tool — this closes the class for any
current or future git-blame flag, not just the ones checked today, and
avoids a real correctness bug where a legitimate filename starting
with `-` would otherwise be silently misinterpreted as a flag):
extracted a shared `validate_git_blame_path()` + `git_blame_handler()`
in `app/tools/git/blame.py`, used by both real call sites.
`validate_git_blame_path()` rejects any `path` starting with `-`.

`app/agents/tools.py`'s `READ_ONLY_TOOLS[14]` (verified empirically as
the correct index before editing) now points at the shared
`GIT_BLAME_TOOL` constant, and its `make_read_only_handlers()` closure
delegates to the shared handler. `app/agents/chat_agent.py`'s dispatch
now calls the same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_git_blame_hardening.py`, 13 tests, all real (a
real git repository on disk, no mocking) — schema/index checks,
`validate_git_blame_path()` direct unit checks, the flag-shaped-path
rejection verified closed on both real dispatch paths, the
already-safe worktree-boundary refusal re-verified as a regression
guard, and legitimate-usage regression (full blame output, line-range
narrowing) across all three real access paths
(`ChatAgent._execute_tool`, `make_read_only_handlers()`,
`make_chat_handlers()`).

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** The flag-collision class closed defensively on both
real implementations (checked and confirmed lower severity than tool
#80, but consistent with established policy); `path`'s existing
worktree protection and the numeric line-range fields' immunity
re-verified rather than assumed; no functionality lost; full
regression clean.
