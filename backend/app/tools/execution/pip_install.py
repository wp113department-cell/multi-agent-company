"""pip_install tool — tool_enhance.md productionization pass, tool
#55 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: pip_install
Old path: app/agents/tools.py (`_PIP_INSTALL_TOOL` schema dict).
New path: app/tools/execution/pip_install.py (this file) —
    `PIP_INSTALL_TOOL`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch, the only real, reachable caller (reachability
    already fixed during tool #4's earlier pass, confirmation-gated).
    `make_chat_handlers`'s own `pip_install_h` is already
    unconditionally `[BLOCKED]` (tool #4, no real one-shot caller) —
    unaffected by this turn, re-verified unchanged.
Affected modules: app/agents/tools.py (schema re-export only — no
    handler-logic changes on either real call site this turn).
Affected registries: none — app/fleet/tool_manifest.py's "pip_install"
    ToolManifestEntry is pure metadata, keyed by tool NAME not file
    path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_pip_install_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/pip_install.md.
---------------------------------------------------------------------------

Audit result: no new vulnerability, no code fix needed beyond
modularization.

- No `directory`/`cwd` field exists on this tool at all (unlike
  tools #53/#54's `npm_install`/`npm_run`) — there is no worktree-
  escape surface to close.
- `subprocess.run([sys.executable, "-m", "pip", "install", pi_package],
  ...)` is already list-args, no `shell=True` — no shell-injection
  surface.
- A real, genuine confirmation gate already exists on the only real,
  reachable call site (`chat_agent.py`), showing the human the exact
  raw `pip install <package>` command that will run, unredacted.

**Real, documented (not "fixed") finding**: pip's own argument parser
recognizes certain flags EMBEDDED WITHIN a single `package` string —
proved live, with no shell involved (`subprocess.run` with an explicit
argv list, confirmed via the exact list printed before the call):

```python
subprocess.run(["python3", "-m", "pip", "install", "--dry-run", "-e ."])
```

still triggered pip's editable-install code path
(`ERROR:  . is not a valid editable requirement...`), even though
`"-e ."` was genuinely ONE argv token, never split by a shell. This is
a real, if narrow, "second-order" argument-recognition surface distinct
from OS-level shell injection — but **not something safe to reject
outright**: pip's `install` command legitimately accepts version
specifiers, extras, editable installs (`-e <path-or-vcs-url>`), and
direct VCS URLs (`git+https://...`) as ordinary, documented `package`
values — the same richness that makes a hard "reject anything
flag-shaped" fix (the pattern used for git ref/branch fields throughout
this initiative) inappropriate here, since it would break real,
legitimate developer workflows this tool is meant to support. The
schema's own `package` description ("Package name with optional
version, e.g. 'requests==2.31.0'") already signals this is a rich,
pip-native value, not a narrow token.

The existing confirmation gate is the correct, intended safeguard for
this class of risk (verified it shows the human the complete, raw,
unredacted `package` value before anything runs) — this matches the
same reasoning already applied elsewhere in this initiative when a
found risk has no clean reject-boundary without breaking legitimate use
(e.g. tool #37's `git_commit --all` sentinel, kept rather than
blocked).
"""

from __future__ import annotations

PIP_INSTALL_TOOL: dict[str, object] = {
    "name": "pip_install",
    "description": "Install a Python package in the current environment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name with optional version, e.g. 'requests==2.31.0'",
            },
        },
        "required": ["package"],
    },
}
