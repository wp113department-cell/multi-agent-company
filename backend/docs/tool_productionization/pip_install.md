# Tool #55 — `pip_install` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch — reachability already
   fixed during tool #4's earlier pass, with a genuine confirmation
   gate.
2. `make_chat_handlers()`'s own `pip_install_h` — already
   unconditionally `[BLOCKED]` since tool #4 (no real one-shot caller).
   Re-verified unchanged and correct.

`CHAT_TOOLS.count("pip_install") == 1` verified before making any
change.

## Problems found

**No new vulnerability, no code fix needed beyond modularization.**

- No `directory`/`cwd` field exists on this tool at all (unlike tools
  #53/#54's `npm_install`/`npm_run`) — there is no worktree-escape
  surface to close.
- `subprocess.run([sys.executable, "-m", "pip", "install", package],
  ...)` is already list-args, no `shell=True` — no shell-injection
  surface.
- A real, genuine confirmation gate already exists on the only real,
  reachable call site, showing the human the exact raw `pip install
  <package>` command that will run, unredacted.

**Real, documented (not fixed) finding**: pip's own argument parser
recognizes flags embedded WITHIN a single `package` string. Proved
live, with no shell involved (`subprocess.run` given an explicit argv
list, confirmed one single list element, never shell-split):

```python
subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "-e ."])
```

still triggered pip's editable-install code path (`ERROR:  . is not a
valid editable requirement...`), even though `"-e ."` was genuinely one
argv token. This is real, but **not something safe to reject
outright** — pip's `install` command legitimately accepts version
specifiers, extras, editable installs (`-e <path-or-vcs-url>`), and
direct VCS URLs as ordinary, documented `package` values. A hard
"reject anything flag-shaped" fix (the pattern used for git ref/branch
fields throughout this initiative) would break real, legitimate
developer workflows this tool exists to support — unlike a git ref,
where `-f`/`--hard` genuinely has zero legitimate value. The existing
confirmation gate — which shows the human the complete, raw,
unredacted `package` value — is the correct, intended safeguard for
this class of risk, the same reasoning already applied when a found
risk has no clean reject-boundary without breaking legitimate use
(e.g. tool #37's `git_commit --all` sentinel, kept rather than
blocked).

## Changes made

- **`app/tools/execution/pip_install.py`** (new): `PIP_INSTALL_TOOL`
  schema, unchanged. No validator/handler logic — neither real call
  site's behavior changes.
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: schema
  re-export only, plus explanatory comments documenting this turn's
  audit inline at both real call sites (no logic changes).

## Tests (real — a real pip subprocess call with a guaranteed-
nonexistent package name, so the network round-trip fails fast and no
real package/code is ever actually installed)

`tests/test_pip_install_hardening.py` (new, 6 tests):

- Schema shape check, and confirms `pip_install` appears in
  `CHAT_TOOLS` exactly once.
- The already-correct confirmation gate, re-verified: a declined
  confirmation installs nothing; an approved confirmation genuinely
  invokes real `pip` (confirmed via real, live pip output referencing
  the fake package name); the standalone `make_chat_handlers` version
  confirmed still blocked.
- The documented pip flag-recognition finding, proved directly with an
  explicit argv list (confirmed exactly one list element, never
  shell-split) still triggering pip's editable-install code path.

Also swept 8 pre-existing test files referencing `pip_install` — no
logic changed on either real call site, so none were expected to break;
all 191 confirmed still passing.

## Regression

Targeted sweep (new test file + npm_run + npm_install hardening): **21
passed.** Full suite re-run after this pass: **5283 passed, 52
skipped, 18 deselected, 0 failed** (up from 5277 before this tool).

## Final verdict

**GREEN FLAG.**
