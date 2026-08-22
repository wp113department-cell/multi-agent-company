# Tool #64 — `sync_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

This tool appears to have been missed by tool #11's cross-cutting
worktree-boundary sweep (2026-08-17) — it is not among the tracking-
table rows that sweep annotated as pre-closed.

## Current implementation (audit)

Two real implementations:

1. `chat_agent.py`'s real interactive dispatch — read `source` and wrote
   each `paths` entry with `root / source` / `root / target` and **no
   boundary validation at all**.
2. `app/agents/tools.py`'s `make_chat_handlers()` `sync_files` — already
   correctly called `check_path_in_worktree()` on both `source` and
   every `paths` entry before touching the filesystem.

`CHAT_TOOLS.count("sync_files") == 1` verified.

## Problems found

**Real, severe finding: `chat_agent.py`'s dispatch had ZERO
worktree-boundary validation.** `root / source` and `root / target`
both silently discard `root` when the value is an absolute path — the
same pathlib bug class as tools #10/#11/#18/#23/#43/#59/#61/#62.

Proved live, combined in one call (a real, severe exfiltration +
arbitrary-write primitive, not two independent minor issues):

```python
await agent._execute_tool("sync_files", {
    "source": "/etc/hostname",
    "paths": ["exfiltrated.txt", "/tmp/PWNED.txt"],
})
```

genuinely:
- **Read** a real host file outside the repo (`/etc/hostname`).
- **Wrote** its content into the repo (`exfiltrated.txt`) — a real
  exfiltration vector, since that content is now visible to anyone who
  can later read the repo (including, eventually, being committed or
  reviewed by a human or another agent).
- **Wrote** its content to an arbitrary path OUTSIDE the repo
  (`/tmp/PWNED.txt`) — a real arbitrary-host-file-write primitive,
  independent of the exfiltration.

`tools.py`'s own implementation was NOT exploitable by this payload —
it already correctly rejected both the outside-repo `source` and the
outside-repo `paths` entry.

## Changes made

- **`app/tools/filesystem/sync_files.py`** (new): `SYNC_FILES_TOOL`
  schema (moved verbatim, copied directly from the live `CHAT_TOOLS`
  entry rather than from the nearby stale comment description — a
  discipline check applied deliberately this turn) and
  `sync_files_handler(root, worktree_path, inp)` — the existing,
  already-correct logic from `tools.py`'s implementation, moved here
  verbatim: `check_path_in_worktree()` on `source` before any read, and
  independently on every `paths` entry before any write (one target
  failing validation does not block the others, matching the original
  per-target error-collection behavior).
- **`app/agents/chat_agent.py`**: dispatch no longer builds its own
  unvalidated read/write loop — delegates to the shared, protected
  handler.
- **`app/agents/tools.py`**: handler now delegates to the same shared
  function (zero behavior change on this side).

## Tests (real, not mocked — every test uses real files on disk)

`tests/test_sync_files_hardening.py` (new, 9 tests):

- Schema shape check.
- **The proven finding, verified closed on the real dispatch path that
  lacked protection**: an outside-repo `source` alone is rejected; an
  outside-repo `paths` entry alone is rejected; the exact combined
  exploit shape (`source="/etc/hostname"` + one in-repo and one
  outside-repo target in the same call) is fully blocked — neither the
  in-repo exfiltration file nor the outside-repo write is created.
  Re-verified `make_chat_handlers`'s already-safe implementation stays
  safe.
- Regression: a legitimate sync still creates/updates real targets
  (including into a new subdirectory) and correctly detects "unchanged"
  on a second call with identical content, on both real dispatch paths;
  a missing source still errors cleanly; `sync_files` appears exactly
  once in `CHAT_TOOLS`.

Also re-ran `tests/test_audit_q_batch01_execution_terminal_fixes.py`
(its `TestSyncFiles` class uses only in-repo relative paths — confirmed
unaffected; 24 total tests in the file, all passing).

## Regression

Full suite: **5405 passed, 52 skipped, 18 deselected, 0 failed** (up
from 5396 before this tool).

## Final verdict

**GREEN FLAG.**
