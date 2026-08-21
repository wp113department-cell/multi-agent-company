# Tool #53 — `npm_install` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch — already fixed for
   reachability during tool #4's earlier pass (was "advertised but
   never dispatched"; a real confirmation-gated dispatch was added
   then). This turn's own full audit found a separate, more severe bug
   still present in that same dispatch.
2. `make_chat_handlers()`'s own `npm_install_h` — already
   unconditionally `[BLOCKED]` since tool #4 (no real, safely-
   confirmable one-shot caller). Re-verified unchanged and correct.

## Problems found (real, empirically verified — severe: arbitrary code
execution via a worktree-escaping `directory`/`cwd` field)

`chat_agent.py`'s real dispatch built `ni_target_dir = str(root /
ni_directory)` with **zero validation that `directory` stays inside
the repo**. Proved live:

```python
await agent._execute_tool("npm_install", {"directory": "/tmp/td_npminstall_outside"})
```

where `/tmp/td_npminstall_outside/package.json` contained:

```json
{"scripts": {"preinstall": "touch /tmp/td_npminstall_PWNED_marker"}}
```

The confirmation dialog shown to the human only displayed the raw
`directory` string ("Run npm install in /tmp/..."), with no structural
signal that it escapes the repo. Once approved, `npm install` genuinely
executed the `preinstall` lifecycle script — confirmed via the marker
file's real existence afterward. This is real, arbitrary command
execution in an attacker/LLM-chosen directory, via npm's own
lifecycle-script mechanism — the same underlying class as tool #9's
`run_parallel_commands`/`bash` sandbox-escape and tool #23's
`rename_symbol` cross-file-rewrite findings, but landing on real OS
command execution rather than a file read/write.

## Changes made

- **`app/tools/execution/npm_install.py`** (new): `NPM_INSTALL_TOOL`
  (schema, unchanged) and `validate_npm_install_directory(directory,
  worktree_path)` — a `check_path_in_worktree()` chokepoint, the same
  mechanism used throughout this initiative for LLM-controlled
  `cwd`/`directory` fields since tool #9.
- **`app/agents/chat_agent.py`**: real dispatch now rejects an
  out-of-worktree `directory` before ever building the npm command or
  showing the confirmation dialog.
- **`app/agents/tools.py`**: schema re-export only — the standalone
  handler stays unconditionally `[BLOCKED]`, unchanged (it has no logic
  to fix).

## Tests (real, not mocked — real `npm` subprocess execution against
real `package.json` files on disk; skipped if `npm` isn't installed)

`tests/test_npm_install_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `npm_install` appears in
  `CHAT_TOOLS` exactly once.
- Pure validator tests: an outside-repo `directory` rejected, a real
  in-repo `directory` (including a subdirectory) allowed.
- **The exact proven exploit, verified closed**: the malicious
  `preinstall` package/directory setup is rejected before `npm` ever
  runs — the marker file is confirmed to never exist.
- The standalone `make_chat_handlers` version confirmed still
  unconditionally blocked (unaffected).
- Regression: a real `npm install` in the repo root still succeeds
  (confirmed via real output/lockfile), and a declined confirmation
  still returns `[DENIED]` without running anything.

Also swept 6 pre-existing test files referencing `npm_install`
(`test_day2_agents.py`, `test_audit_q_batch07_guardian_human_
interaction.py`, `test_git_tag_hardening.py`,
`test_git_push_hardening.py`, `test_github_create_pr_hardening.py`,
`test_fleet_tool_manifest.py`) — all either use the default
`directory="."` (unaffected) or test the standalone handler's
unconditional block (unaffected); all 80 confirmed still passing.

## Regression

Targeted sweep (new test file + move_file + memory_write hardening):
**23 passed.** Full suite re-run after this pass: **5270 passed, 52
skipped, 18 deselected, 0 failed** (up from 5262 before this tool).

## Final verdict

**GREEN FLAG.**
