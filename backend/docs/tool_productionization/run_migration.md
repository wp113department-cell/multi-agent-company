# Tool #8 — `run_migration` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, same shape as prior git/GitHub tools:

1. `app/agents/chat_agent.py::ChatAgent._execute_tool()` — the real,
   reachable path for the only agent that advertises `run_migration`
   (`chat_agent`). Confirmation-gated via a real `self._confirm()`
   interrupt()-based pause, and blocked outright in production
   environments.
2. `app/agents/tools.py::make_chat_handlers()` — `run_migration` isn't
   in any one-shot agent's `allowed_tools`, and tool #4's earlier pass
   already removed this handler's dead `session.request_confirmation()`
   plumbing, leaving it an unconditional `[BLOCKED]`.

## Problem found — a real, empirically-verified shell-injection vulnerability

This is the most severe finding of this entire initiative so far.

Reading the real, reachable `chat_agent.py` implementation:

```python
rmig_dir = str(inp.get("direction", "upgrade"))
rmig_rev = str(inp.get("revision", "head" if rmig_dir == "upgrade" else "-1"))
...
rmig_cmd = f"{activate} && cd {rmig_backend} && alembic {rmig_dir} {rmig_rev} 2>&1"
return await asyncio.to_thread(_run_subprocess, rmig_cmd, rmig_backend, 120)
```

`_run_subprocess` runs with `shell=True` on a raw string. `rmig_dir` and
`rmig_rev` are **fully LLM-controlled** and were interpolated directly
into that string with **zero validation**.

Verified directly, before writing any fix (not assumed):

```python
rmig_rev = 'head; touch /tmp/PWNED_run_migration_proof'
# constructed command: ...&& alembic upgrade head; touch /tmp/PWNED_run_migration_proof 2>&1
# subprocess.run(..., shell=True) executed it for real —
# os.path.exists('/tmp/PWNED_run_migration_proof') → True
```

The injected command ran. This is real arbitrary command execution, not
a theoretical concern, and it **completely defeats the confirmation
dialog's purpose** — a human reviewing "alembic upgrade `<revision>`" has
no reasonable way to notice an injection payload hidden inside what
looks like an ordinary revision identifier.

**Scope note**: the identical pattern exists in `seed_database` (tool
#10) right next to this code — confirmed while auditing this tool, not
fixed here. Per explicit user direction, this pass stays scoped to
`run_migration`; `seed_database`'s copy of the same bug is logged in
`bhaskar_next/tool_enhance_tracking.md` as the first thing to fix when
that tool's own turn comes, not left undocumented.

## Changes made

- **`app/tools/database/migration.py`** (new — see Modularization below):
  `validate_run_migration_inputs(direction, revision)` — the one shared
  chokepoint both real call sites now run through before building any
  command. `direction` must be exactly `"upgrade"` or `"downgrade"`;
  `revision` must match `[A-Za-z0-9_+-]+` — covers every real Alembic
  revision shape (`head`, `heads`, `base`, a hex revision id, or a
  relative offset like `-1`/`+1`/`head-1`) while rejecting every shell
  metacharacter (`;`, `&&`, `|`, backticks, `$()`, newlines, `>`/`<`).
- **`app/agents/chat_agent.py`**: calls `validate_run_migration_inputs`
  before ever building the shell command, replacing the ad-hoc inline
  checks that previously validated `direction` but never `revision` at
  all.
- **`app/agents/tools.py`**: the already-unreachable handler also calls
  the shared validator before its own unconditional block, for
  defense-in-depth consistency with the real, reachable implementation.

## Modularization (tool_enhance.md §7/§8)

Extracted `RUN_MIGRATION_TOOL` (schema) and the (now-thin)
`run_migration_handler` out of `app/agents/tools.py` into
`app/tools/database/migration.py` — the first tool in a new
`app/tools/database/` domain folder (matching tool_enhance.md's own
suggested structure). Full TOOL PATH MIGRATION REPORT lives in the new
module's own docstring. `chat_agent.py`'s own real dispatch stays where
it is, now importing the shared validator directly instead of
duplicating it — same precedent as `git_reset`'s
`validate_git_reset_inputs`.

## Tests (real, not mocked at the mechanism level)

- `tests/test_run_migration_hardening.py` (new, 14 tests): a baseline
  test proving the real shell behavior the fix depends on (not this
  project's code); the exact proven exploit payload driven through the
  real `ChatAgent._execute_tool` dispatch, asserting it's rejected
  *before* the confirmation gate is even reached (`_confirm` mock
  asserted never awaited) and that the injected marker file never
  appears; 6 additional shell-metacharacter payloads (`&&`, `|`,
  backticks, `$()`, `>`, newline) all rejected; invalid `direction`
  rejected; every real legitimate Alembic revision shape (`head`,
  `heads`, `base`, `-1`, `+1`, `head-1`, a real-looking hex revision, a
  relative offset from a hash) proven to still work — real regression
  proof that the fix doesn't limit legitimate usage; the confirmation
  gate itself (decline/approve) proven still functionally correct.

## Regression

Targeted sweep (run_migration + related git/day1/fleet-manifest test
files): 378 passed. Full suite re-run after this pass: **4829 passed, 52
skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

A real, empirically-proven arbitrary-command-execution vulnerability is
fixed with a real, evidence-backed test — verified to exist before the
fix, verified closed after it. No functionality was lost: every real
Alembic revision shape continues to work exactly as before. The
identical bug in `seed_database` is explicitly logged as a known,
already-diagnosed follow-up for that tool's own turn, not silently
carried forward as an unstated gap.
