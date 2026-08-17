# Tool #10 — `seed_database` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Two implementations, same shape as `run_migration` (tool #8): a real,
reachable `chat_agent.py` dispatch (confirmation-gated, blocked in
production) and an already-unreachable `tools.py` handler (simplified to
an unconditional `[BLOCKED]` in tool #4's earlier pass).

**This tool's shell-injection bug was already diagnosed** while auditing
`run_migration` (tool #8) — the identical code shape sits right next to
it in `chat_agent.py`. Per explicit user direction at the time, it was
logged as a known issue rather than fixed early, to keep that pass
scoped. This is where it gets closed.

## Problems found (real, empirically verified — not assumed)

**#1 — shell injection**, same bug class as `run_migration`:

```python
seeddb_fp = root / seeddb_script
...
seeddb_cmd = f"{activate} && python3 {str(seeddb_fp)} 2>&1"
return await asyncio.to_thread(_run_subprocess, seeddb_cmd, repo, 120)
```

`seeddb_script` is LLM-controlled and interpolated raw into a
`shell=True` command. Verified directly: a real file was created with a
literal filename containing a shell metacharacter (`seed.py; touch
/tmp/PWNED...`), and referencing it via `script` executed the injected
command for real.

**#2 — a second, distinct vulnerability**, found while designing the fix
for #1 (not present in `run_migration`, since that tool's `revision`
field isn't used to build a filesystem path): `root / seeddb_script`
silently **ignores `root` entirely** when `seeddb_script` is an absolute
path. This is Python's own documented `pathlib.Path.__truediv__`
behavior, not a bug in this codebase — but combined with zero validation,
it's a real path-boundary escape. Verified directly:

```python
root = Path("/some/repo/root")
script = "/etc/hostname"
str(root / script) == script  # True — root was discarded entirely
```

The tool's own schema documents `script` as "relative to repo root," so
this is a genuine deviation from the documented contract. A `../`-style
relative traversal has the identical practical effect.

## Changes made

- **`app/tools/database/seed.py`** (new — see Modularization below):
  `validate_seed_database_script(script, worktree_path)` — the one
  shared chokepoint both real call sites now run through. Two layers:
  (a) a character allowlist (`[A-Za-z0-9_./-]+`) rejecting every shell
  metacharacter, closing #1; (b) `check_path_in_worktree` (the same,
  already-established mechanism this codebase already uses for
  `write_file`/`edit_file`'s own path arguments), closing #2 by
  rejecting any absolute path or `../` traversal that resolves outside
  the repo.
- **`app/agents/chat_agent.py`**: calls `validate_seed_database_script`
  before the script-existence check, replacing zero prior validation.
- **`app/agents/tools.py`**: the already-unreachable handler also calls
  the shared validator, for defense-in-depth consistency.

## Modularization (tool_enhance.md §7/§8)

Extracted `SEED_DATABASE_TOOL` (schema) and the (now-thin)
`seed_database_handler` out of `app/agents/tools.py` into
`app/tools/database/seed.py`, alongside `migration.py` (tool #8) in the
`app/tools/database/` domain folder. Full TOOL PATH MIGRATION REPORT
lives in the new module's own docstring.

## Tests (real, not mocked at the mechanism level)

- `tests/test_seed_database_hardening.py` (new, 11 tests): two baseline
  tests proving the real shell/pathlib behavior the fix depends on (not
  this project's code); the proven shell-injection payload rejected
  before the confirmation gate is even reached; 6 additional shell-
  metacharacter payloads rejected; the proven absolute-path escape
  rejected; a `../` traversal rejected; the same payloads proven rejected
  by the `tools.py` handler too; and real regression proof that the
  default script path, a real custom relative script, and the
  script-not-found error path all still work exactly as before.

## Regression

Targeted sweep (seed_database + run_migration + git_push/git_reset/
run_parallel_commands hardening + day1/fleet-manifest/chat-graph test
files): 252 passed. Full suite re-run after this pass: **4848 passed, 52
skipped, 18 deselected, 0 failures.**

## Final verdict

**GREEN FLAG.**

Both real vulnerabilities — the shell injection diagnosed during tool
#8's audit, and the path-boundary escape found while designing this
fix — are closed with real, evidence-backed tests, verified to exist
before the fix and verified closed after it. No functionality was lost:
every real, legitimate script path continues to work exactly as before.
