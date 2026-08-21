# Tool #49 — `kill_process` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Both `chat_agent.py`'s real dispatch and `make_chat_handlers()`'s own
`kill_process` already delegated to one shared implementation:
`app.fleet.process_manager.kill(pid, sig_name, procs)`. That function's
own module docstring documents a real, deliberate prior design choice:
"a kill is attempted even for a PID this process never itself tracked
(no ownership gate existed before this unification, and none is added
here — see this module's own docstring on why NOT changing that is
deliberate)."

## Problems found (real, empirically verified — severe, and explicitly
flagged to the user before fixing, since it was a documented, deliberate
design decision, not an oversight)

`kill()` called `os.kill(pid, sig)` on ANY `pid` at all — no check that
it belonged to a process the calling session had actually started via
`run_background`. Proved live:

```python
p = subprocess.Popen(["sleep", "300"])   # completely unrelated real process
pm.kill(p.pid, "KILL", {})               # empty procs dict — never tracked
```

genuinely killed the unrelated process. This directly contradicted the
tool's own schema description — "Kill a background process by PID. Use
after run_background" — and meant an LLM-controlled `pid` could
terminate ANY process the server's OS user has permission to signal,
including the backend server's own process, or unrelated processes on
the host.

Because this was an explicit, documented decision from a prior
de-duplication refactor rather than an accidental bug, it was raised
directly to the user via `AskUserQuestion` instead of being fixed or
left unilaterally. **User chose: add an ownership gate.**

## Changes made

- **`app/fleet/process_manager.py`** — `kill()` now returns a clear
  `[ERROR]` if `pid` is not a key in the caller's own `procs` dict
  (i.e., a process this exact session started via `run_background`)
  before ever calling `os.kill()`. This is the single shared
  implementation both real call sites already used, so the fix closes
  the gap at both simultaneously.
- **`app/tools/execution/kill_process.py`** (new): `KILL_PROCESS_TOOL`
  schema, moved verbatim (unchanged) — the actual behavior fix lives in
  `process_manager.py`, not duplicated here.
- **`app/agents/tools.py`**, **`app/agents/chat_agent.py`**: schema
  re-export only; both dispatch bodies were already correct
  (delegating to the shared `process_manager.kill()`), now with
  explanatory comments pointing at the real fix location.
- **`tests/test_chat_tools.py`**: fixed a stale, now-intentionally-
  broken test (`TestKillProcess::test_kills_existing_process`) that
  spawned a process via a bare `subprocess.Popen` never registered with
  `run_background` — this is now correctly rejected by the ownership
  gate. Updated to spawn via the real `run_background` handler first,
  matching the tool's own always-documented contract. Added a new test
  asserting the opposite case (an untracked process is genuinely
  rejected) explicitly.

## Tests (real, not mocked — every test spawns a genuine OS process via
`subprocess.Popen`/`run_background` and proves the fix against real
process signals, never mocking `os.kill`)

`tests/test_kill_process_hardening.py` (new, 6 tests):

- Schema shape check.
- Pure `process_manager.kill()` tests: an untracked real process is
  rejected and confirmed to survive; a tracked real process is
  genuinely killed.
- **The exact proven exploit, verified closed against both real call
  sites**: an untracked real `sleep 300` process survives a
  `kill_process` call through both `chat_agent.py`'s dispatch and
  `make_chat_handlers`.
- Regression: a full real `run_background` → `kill_process` workflow
  (spawn, then kill by the returned PID) through `chat_agent.py`.

Plus fixed/extended `tests/test_chat_tools.py::TestKillProcess` (see
above) and re-ran `tests/test_audit_q_batch01_execution_terminal_fixes.py`
(24 tests, all already used the correct tracked-`procs` pattern,
confirmed unaffected).

## Regression

Targeted sweep (new test file + fixed/extended `test_chat_tools.py` +
`test_audit_q_batch01_execution_terminal_fixes.py` +
`test_insert_before_hardening.py`): **170 passed.** Full suite re-run
after this pass: **5239 passed, 52 skipped, 18 deselected, 0 failed**
(up from 5232 before this tool).

## Final verdict

**GREEN FLAG.**

## Correction (added during tool #58's turn, 2026-08-20)

While verifying tool #58's (`run_background`) own Docker-sandboxing
work, a second real, severe bug was found in `kill()` — not introduced
by tool #58, pre-existing since this tool's own original
implementation: `process_manager.spawn()`'s `subprocess.Popen(command,
shell=True)` makes the TRACKED pid the WRAPPING `/bin/sh -c <command>`
process, not the real command underneath it. `kill()`'s plain
`os.kill(pid, sig)` therefore only ever reached that shell wrapper.
Proved live with a plain `sleep 300` background command: the shell
wrapper was correctly reaped, but the real `sleep` process was left
running, orphaned, completely untracked — `kill_process` returned a
false "Sent TERM to PID X" success message while the actual command
kept running indefinitely.

**Fix** (in `app/fleet/process_manager.py`): `kill()` now calls
`os.killpg(os.getpgid(pid), sig)` (signals the whole process group)
instead of plain `os.kill()`, falling back to `os.kill()` only if
`killpg` raises. This requires `spawn()`'s Popen to set
`start_new_session=True` so each background command gets its own
process group — without it, `killpg` would reach the CALLER's process
group too (proved live: an early test of `killpg` without this flag
killed the test script's own process group).

This also surfaced a matching hazard in this tool's own existing test
suite: `tests/test_kill_process_hardening.py::
test_kill_allows_a_tracked_real_process` constructed its `Popen`
without `start_new_session=True`. Under the old plain-`os.kill()`
`kill()`, that was harmless; under the new `killpg()`-based `kill()`,
it meant running that ONE test SIGKILL'd the entire pytest process
(confirmed via `journalctl -k` showing no kernel OOM event — this was
not memory pressure). Fixed by adding `start_new_session=True` to that
test's own `Popen`, matching how every real tracked process is
actually created in production. Re-verified: 6/6 tests pass cleanly.

Full account, both fixes, and their live verification:
`docs/tool_productionization/run_background.md` (tool #58's own
report).
