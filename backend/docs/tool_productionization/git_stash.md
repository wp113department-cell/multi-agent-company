# Tool #42 — `git_stash` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_chat_handlers()`'s own `git_stash`.

Both use list-args `subprocess.run`/the shared `_git()` helper — no
`shell=True`, so no shell-injection surface for `action`.

## Problems found (real, empirically verified — severe: the schema's own
`enum` constraint is purely advisory to the model and was never
enforced at runtime)

`_GIT_STASH_TOOL`'s schema documents `action` as
`enum: ["push", "pop", "list", "drop"]`, but `chat_agent.py`'s real
dispatch built its command as:

```python
if action == "push" and msg:
    return _git(["stash", "push", "-m", msg], repo)
return _git(["stash", action], repo)
```

Any `action` value other than a message-bearing `"push"` was passed
straight through as a literal `git stash <action>` subcommand, with
**zero validation that it's one of the 4 documented values**. Proved
live against a real repo with two real, distinct stashed changes:

```python
await agent._execute_tool("git_stash", {"action": "clear"})
```

`action="clear"` (never in the schema's enum) ran `git stash clear`,
**permanently and irrecoverably deleting every stash entry**, with zero
confirmation and zero warning — `git stash list` was empty afterward.
Same underlying bug class as tools #5/#32/#35/#36/#38/#39/#40's
flag-collision findings (an out-of-schema value reaching a destructive
git subcommand unchecked), just via an enum bypass rather than a
leading-dash flag.

`make_chat_handlers`'s own `git_stash` was already safe by construction
— an explicit `if/elif` chain only recognizes exactly the 4 documented
actions, and anything else silently falls through to a bare
`git stash` (a no-op-ish no-message push) rather than reaching an
arbitrary subcommand. Not exploitable, but not ideal either: an invalid
`action` was silently reinterpreted as "push" instead of surfacing a
clear error.

## Changes made

- **`app/tools/git/stash.py`** (new): `GIT_STASH_TOOL` (schema,
  unchanged) and `validate_git_stash_action(action)` — an explicit
  allowlist chokepoint mirroring the schema's own enum, used by both
  real call sites.
- **`app/agents/chat_agent.py`**: real dispatch now rejects an
  out-of-enum `action` before ever building the git command.
- **`app/agents/tools.py`**: handler now returns a clear `[ERROR]` for
  an out-of-enum `action` instead of silently substituting a plain
  `push`.

## Tests (real, not mocked at the mechanism level — real git repos, real
subprocess execution)

`tests/test_git_stash_hardening.py` (new, 8 tests):

- Schema enum shape check.
- Pure validator tests: out-of-enum actions rejected (`clear`,
  `branch`, `apply`, empty string), all 4 documented actions allowed.
- **The exact proven exploit, verified closed against both real call
  sites**: `action="clear"` against a real repo with 2 real stashes is
  rejected, and both stashes are confirmed to survive via
  `git stash list`.
- Regression: a real push+pop round trip (confirmed via the file's
  content before/after) through `chat_agent.py`, and a real
  list/drop through `make_chat_handlers`.

## Regression

Targeted sweep (new test file + git_restore + git_rebase hardening):
**25 passed.** Full suite re-run after this pass: **5179 passed, 52
skipped, 18 deselected, 0 failed** (up from 5171 before this tool).

## Final verdict

**GREEN FLAG.**
