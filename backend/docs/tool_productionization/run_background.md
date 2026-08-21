# Tool #58 — `run_background` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations:

1. `chat_agent.py`'s real interactive dispatch.
2. `app/agents/tools.py`'s `make_chat_handlers()` `run_background`.

Both already delegated to the single shared
`app.fleet.process_manager.spawn()`. `CHAT_TOOLS.count("run_background")
== 1` verified.

## Problems found

**Finding #1 (severe) — zero sandboxing.** `spawn()` ran `command` via
plain `subprocess.Popen(command, shell=True)` — full, unrestricted host
shell execution, the same state `bash` (tool #1) was in before its own
real Docker-sandboxing remediation. Proved live: a real payload wrote a
marker file to an arbitrary host path with no restriction whatsoever.

Given the scope (same class of fix as tool #1's own, an established,
reviewed pattern), this was raised to the user directly via
AskUserQuestion before implementing. User chose: apply the same real
Docker sandboxing tool #1 built for `bash`.

**Fix:** `spawn()` now routes `command` through a real, `--init`-based,
read-only-rootfs, non-root, resource-capped (`--memory=1g
--pids-limit=512 --cpus=1.0`), no-`docker.sock` `docker run` when
`Settings.bash_sandbox_enabled` (default True; fails closed with
`[SANDBOX UNAVAILABLE]` if Docker itself is unreachable — proved live
by monkeypatching `_docker_available` to return False). Falls back to
the original raw host execution only when an operator has explicitly
set `BASH_SANDBOX_ENABLED=false` (proved live: unsandboxed spawn +
kill both still work exactly as before).

Critically, `docker run` is invoked WITHOUT `-d` (foreground, not
detached) so it blocks for the container's entire real lifetime,
streaming stdout/stderr through the wrapping `Popen`'s own pipes —
chosen specifically so the existing PID-based `kill_process`/
`read_output`/`list_background_processes` machinery needed **zero**
changes; they only ever look at a tracked Popen's `.pid`/`.poll()`/
`.stdout`/`.stderr`, all of which remain valid against the sandboxed
container's real state. Proved live: a real multi-line, multi-second
script's output arrived via `Popen.communicate()` exactly as if run
unsandboxed.

`--init` is required, not optional — proved live: without it, `docker
kill --signal=TERM` on a `sh -c "sleep 300"` container did NOT stop it
(a well-known Docker gotcha — a shell running as the container's PID 1
does not forward signals to its own children by default). With
`--init` (a lightweight init process as real PID 1), the identical TERM
test stopped the container within seconds, exit code 143.

`cwd` now gets bind-mounted into the sandbox, so an unvalidated `cwd`
would let an LLM-controlled value mount an ARBITRARY host directory
read-write into the "sandboxed" container — defeating the point of
sandboxing it. Fixed via `validate_run_background_cwd()` (the same
`check_path_in_worktree()` chokepoint used since tool #9) on both real
call sites, before `spawn()` is ever called. Proved live: an absolute
`cwd` outside the repo is rejected before any container is started.

**Finding #2 (severe, retroactive correction to tool #49, already
shipped) — `kill_process` orphaned the real process.** Uncovered while
verifying THIS turn's own sandboxing work, not introduced by it:
`spawn()`'s `shell=True` Popen makes the tracked PID the WRAPPING
`/bin/sh -c <command>` process, not the real command. `kill()`
previously sent `sig_name` to that PID via plain `os.kill()` — which
only ever reached the shell wrapper, never its child. Proved live with
a plain `sleep 300` background command: the shell wrapper was
correctly reaped, but the real `sleep` process was left running,
orphaned, completely untracked — `kill_process` returned a false "Sent
TERM to PID X" success message while the actual command kept running
indefinitely.

**Fix:** `kill()` now calls `os.killpg(os.getpgid(pid), sig)` (signals
the whole process group), falling back to plain `os.kill()` only if
`killpg` raises `ProcessLookupError`/`PermissionError`/`OSError`. This
requires a companion fix: `spawn()`'s Popen now sets
`start_new_session=True`, so every background command's shell — and
everything it spawns, sandboxed or not — gets its OWN process group,
letting `killpg` reach the real command without also reaching the
caller's own process group.

This companion fix is not cosmetic: proved live the hard way. The
first attempt at testing `killpg()` *without* `start_new_session=True`
killed the entire *test script's own process group* (the spawned shell
inherited the same pgid as the caller by default) — exit code 143 on
the test runner itself, not the target. With `start_new_session=True`
added, the target process's group correctly differs from the caller's,
and `killpg` only ever affects the intended target. This exact gotcha
recurred a second time as a pre-existing test bug — see "Regression
found and fixed" below.

Verified closed both sandboxed (a `docker kill`-stopped container, no
orphaned container left running — `docker ps` confirmed clean) and
unsandboxed (the real `sleep` process confirmed gone via
`ps -p <pid>`, exit code 1).

**Finding #3 (regression introduced by Finding #1's own fix, caught by
an existing pre-dating test before merge) — the sandbox's fixed
`/workspace` mount point broke absolute-host-path commands.** The
initial sandboxing implementation mirrored `run_sandboxed()`'s own
`-v {cwd}:/workspace:rw -w /workspace` exactly. Running the full
regression sweep surfaced a real failure in a PRE-EXISTING test
(`test_run_background_wait_for_pids_dependency`, from AUDIT_Q_BATCH01,
predating this turn entirely) that ran `touch {tmp_path}/marker` — an
ABSOLUTE HOST PATH. Inside a `/workspace`-mounted container, that same
absolute path does not correspond to the bind-mounted directory (which
is remapped to `/workspace`, not preserved at its original path) — the
file was silently created inside the container's own ephemeral
filesystem and vanished when the container exited, never reaching the
host. This is a real, empirically-proven functionality loss: a test
that passed before this turn's own sandboxing change failed after it.

**Fix:** `_build_sandboxed_argv()` now mounts `cwd` at its own path
inside the container instead of a fixed `/workspace`
(`-v {cwd}:{cwd}:rw -w {cwd}`). Security posture is identical — still
only `cwd` and nothing else of the host is exposed — but absolute-path
commands referencing files under `cwd` (a common real pattern, not a
contrived one) now work exactly as before. Proved live, twice: (a) the
originally-failing `touch {absolute_path_under_cwd}` now creates the
file, confirmed visible on the host; (b) an absolute path OUTSIDE `cwd`
is still fully contained — confirmed NOT visible on the host, proving
this fix did not weaken the sandbox's actual boundary.

This finding is scoped to `run_background`'s own new
`_build_sandboxed_argv()` — `bash` (tool #1)'s own, separately-shipped,
separately-tested `run_sandboxed()` still uses `/workspace` and was not
touched; that tool's own commands are not known to build absolute host
paths, and changing an already-GREEN_FLAG tool's sandbox contract is
out of this turn's scope.

## Regression found and fixed (test-suite hazard, not a product bug)

Sweeping existing tests that reference `kill_process` surfaced a second
instance of the exact `killpg`-without-`start_new_session` gotcha
described in Finding #2 — this time in the TEST SUITE itself, not
production code. `tests/test_kill_process_hardening.py`'s
`test_kill_allows_a_tracked_real_process` constructed its own `Popen`
without `start_new_session=True`. Under the OLD `kill()` (plain
`os.kill()`), this was harmless. Under the NEW, correct `kill()`
(`os.killpg()`), that Popen shared the *test runner's own* process
group — running this one test SIGKILL'd the entire pytest process,
repeatedly, with no kernel OOM event logged (confirmed via
`journalctl -k`, ruling out the environmental-pressure explanation this
initiative has previously seen for unrelated failures). Fixed by adding
`start_new_session=True` to that test's own `Popen` call, matching how
every real tracked process is actually created in production
(`process_manager.spawn()` always sets it). Re-ran: 6/6 passed cleanly,
no more runner kills.

## Changes made

- **`app/fleet/process_manager.py`**: `_build_sandboxed_argv()` (new),
  `spawn()` (now routes through the sandbox when enabled, `cwd`-mount
  fixed to `cwd:cwd` not `cwd:/workspace`), `kill()` (retroactive
  `killpg` + fallback fix, tool #49 correction).
- **`app/tools/execution/run_background.py`** (new): `RUN_BACKGROUND_TOOL`
  schema (unchanged), `validate_run_background_cwd()`.
- **`app/agents/tools.py`**: `_RUN_BACKGROUND_TOOL_DEF` now points at the
  shared schema; `run_background()` handler now validates `cwd` before
  calling `spawn()` (in addition to the pre-existing `check_command()`
  policy check, preserved).
- **`app/agents/chat_agent.py`**: `run_background` dispatch now
  validates `cwd` via the shared validator AND calls `check_command()`
  (added during this turn — the initial dispatch edit had dropped this
  pre-existing check that `tools.py`'s handler still had; caught before
  commit by a side-by-side comparison of both real call sites).
- **`tests/test_kill_process_hardening.py`**: `start_new_session=True`
  fix to `test_kill_allows_a_tracked_real_process` (see "Regression
  found and fixed" above).
- **`tests/test_run_background_hardening.py`** (new, 17 tests).

## Tests (real, not mocked)

`tests/test_run_background_hardening.py` (new, 17 tests):

- Schema shape check.
- `validate_run_background_cwd()`: allows repo root and relative
  subdirs, rejects an absolute outside-repo path and `..` traversal.
- Real sandboxed execution: cannot write outside `cwd` (Finding #1,
  closed), can write inside `cwd`, absolute-path-under-`cwd` reaches
  the host (Finding #3, closed), fails closed when Docker is
  unreachable.
- Explicit `BASH_SANDBOX_ENABLED=false` opt-out still works unsandboxed.
- `kill_process` actually stops the real process, both unsandboxed and
  sandboxed (Finding #2, closed both ways).
- `wait_for_pids` dependency chaining still works under sandboxing
  (AUDIT_Q_BATCH01 §58 regression).
- Both real dispatch paths reject a `cwd` outside the repo.
- `run_background` appears exactly once in `CHAT_TOOLS`.
- A full real `run_background` → `kill_process` workflow through
  `ChatAgent._execute_tool`.

Also re-ran and fixed `tests/test_kill_process_hardening.py` (6/6,
see correction above) and re-ran
`tests/test_audit_q_batch01_execution_terminal_fixes.py` (24/24, the
Finding #3 regression test included) and `tests/test_chat_tools.py` /
`tests/test_day1_tools.py` (all passing, no other Popen-without-
`start_new_session` hazards found in either file).

## Regression

Full suite: see commit for final pass/fail counts (run in background
alongside writing this report).

## Final verdict

**GREEN FLAG.**

Note: this report also documents a retroactive correction to tool #49
(`kill_process`), already marked GREEN_FLAG — its own doc/tracking
entry is amended with a "Correction" section (matching the tool #9 /
#24 / #57 precedent for retroactive fixes), not rewritten.
