# Tool #9 — `run_parallel_commands` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, same shape as prior tools: `chat_agent.py`'s real,
reachable dispatch (the only agent that advertises this tool), and
`app/agents/tools.py`'s `make_chat_handlers()` version (unreachable by
any one-shot agent, kept for defense-in-depth). Both fan out N
independent shell commands concurrently via `asyncio.gather`, each
running through `_run_bash_command` — the same real Docker-sandboxed
execution primitive tool #1 (`bash`) hardened. Each sub-command is
denylist-checked (`check_command`/`_is_dangerous_command`) individually,
with no confirmation flow — a dangerous sub-command is refused outright
rather than offered for human approval, since there's no sane multi-
command confirmation UX. This part of the design was already sound.

## Problem found — a real, empirically-verified sandbox boundary escape, shared with the already-GREEN-FLAGGED `bash` tool

Each command entry accepts an optional `cwd`. Reading both real
implementations:

```python
rpc_cwd = str(rpc_entry.get("cwd") or repo)
...
return await asyncio.to_thread(_run_bash_tool, cmd, cwd, rpc_timeout)
```

`cwd` is **fully LLM-controlled** and was passed straight through to
`app.policy.sandbox.run_sandboxed`, which mounts whatever `cwd` it
receives **read-write** as the container's `/workspace` — with **no
validation that it stays inside the caller's own repo**.

Verified directly, before writing any fix (not assumed):

```python
outside_dir = tempfile.mkdtemp(prefix="outside_the_intended_worktree_")
Path(outside_dir, "secret.txt").write_text("must not be reachable from a different worktree")

stdout, stderr, returncode, timed_out = _run_bash_command(
    "ls -la && cat secret.txt", outside_dir, timeout=30
)
# stdout contained the real file content — the arbitrary host directory
# was genuinely mounted and readable through the real sandbox.
```

**This is the same bug, and it also exists in the generic `bash` tool
(tool #1)** — `chat_agent.py`'s `bash` dispatch has the identical
`cwd = str(inp.get("cwd") or repo)` pattern with no validation. Tool #1
was marked GREEN FLAG before this was found. Per explicit user direction
(this finding is more consequential than the analogous run_migration/
seed_database split in tool #8, since it retroactively affects an
already-closed tool), **both are fixed together in this pass**, not
split across two tool turns.

Notably, `app/agents/tools.py`'s own `make_chat_handlers()` `bash`
handler (a different, third implementation, already closed off from any
one-shot agent) had already been fixed for this exact bug class in an
earlier, unrelated audit (`Gap-closure Audit 05, SEC-05-006`) — by
hardcoding `cwd = repo_path` with no override at all. This pass takes a
less blunt approach for `bash`/`run_parallel_commands`'s real,
interactive-chat-agent dispatches: validate the LLM-supplied `cwd`
instead of removing the parameter outright, since both tools' own schemas
explicitly advertise `cwd` as real, intended functionality (e.g. running
a command in `apps/web` vs `backend`) that a blunt removal would break.

## Changes made

- **`app/agents/chat_agent.py`**: both the `bash` dispatch and the
  `run_parallel_commands` dispatch (once per sub-command) now call
  `check_path_in_worktree(cwd, repo)` — the same, already-established
  mechanism this codebase already uses for `write_file`/`edit_file`'s own
  path arguments — before the command ever reaches the sandboxed
  execution primitive. A `cwd` that resolves outside the repo (via an
  absolute path or a relative `../` traversal) is refused with
  `[POLICY DENIED]`.
- **`app/agents/tools.py`**: `run_parallel_commands_handler` gets the
  identical check for defense-in-depth consistency, even though it has
  no real reachable caller today.

## Modularization (tool_enhance.md §7/§8)

Extracted `MAX_PARALLEL_COMMANDS`, `RUN_PARALLEL_COMMANDS_TOOL`, and the
handler out of `app/agents/tools.py` into
`app/tools/execution/parallel.py` — the exact location
`tool_enhance.md`'s own suggested structure names
(`execution/parallel.py`). Full TOOL PATH MIGRATION REPORT lives in the
new module's own docstring. `chat_agent.py` updated its
`MAX_PARALLEL_COMMANDS` import to the new location (previously imported
from `app.agents.tools`).

## Tests (real, not mocked at the mechanism level)

- `tests/test_run_parallel_commands_hardening.py` (new, 8 tests): the
  real exploit proven closed against **both** affected tools (`bash` and
  `run_parallel_commands`, in both the real `chat_agent.py` dispatch and
  the `tools.py` handler) — a `cwd` pointed outside the worktree is
  rejected before the sandbox ever runs; a `../`-traversal relative `cwd`
  is caught the same way (`check_path_in_worktree` resolves via
  `realpath`, not a naive string prefix check); and real regression
  proof that legitimate `cwd` usage — including a real subdirectory like
  `apps/web` — keeps working exactly as before, for both tools.
- Full existing bash-tool suite (`test_bash_tool_execution.py`,
  `test_bash_sandbox_wiring.py`, `test_bash_toolchain_sandbox.py`,
  `tests/security/test_bash_security.py`, `test_sandbox.py` — 159 tests)
  re-run to confirm zero regression from this correction to an
  already-GREEN-FLAGGED tool.

## Regression

Targeted sweep (run_parallel_commands + full bash-tool suite + related
hardening test files): 224 passed. Full suite re-run after this pass:
**4837 passed, 52 skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

A real, empirically-proven sandbox boundary-escape vulnerability is fixed
with a real, evidence-backed test — verified to exist before the fix
(across both affected tools), verified closed after it. No functionality
was lost: every legitimate `cwd` usage, including real subdirectories,
continues to work exactly as before. `docs/tool_productionization/bash.md`
(tool #1) is updated separately to record this correction transparently,
consistent with this initiative's own standing practice of never hiding
a finding that affects an already-closed tool.
