# Tool #52 — `move_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`move_file_h`. **`chat_agent.py` had no dispatch for it at all**,
despite the tool already being advertised via `CHAT_TOOLS` — same
"advertised but never dispatched" class as tools #4/#6/#22/#25/#33/
#44/#45/#46/#48/#50/#51. `CHAT_TOOLS.count("move_file") == 1` verified
directly before making any change.

## Problems found

**Severe, real finding — same class as tool #11's `copy_file` bug
("never validated `from_path` at all... a real cross-repo exfiltration
primitive"), but worse here since a MOVE also deletes the original.**
The handler validated `dest` via `_is_protected_path(dest, repo_path)`
(already correctly enforcing full `check_path_in_worktree()`
containment, re-verified live: an absolute outside-repo `dest` is
correctly rejected) — but **`source` was never validated at all**.

Proved live:

```python
handlers["move_file"]({
    "source": "/tmp/td_movefile_outside/secret.txt",  # a real file OUTSIDE the repo
    "dest": "exfiltrated.txt",
})
```

genuinely relocated the file into the repo via `shutil.move()` — and
the original file's location was confirmed empty afterward. This is a
real arbitrary-file exfiltration primitive that is also destructive at
the source, strictly worse than `copy_file`'s already-fixed finding
(which at least leaves the original intact).

## Changes made

- **`app/tools/filesystem/move_file.py`** (new): `MOVE_FILE_TOOL`
  (schema, unchanged) and `move_file_handler(root, worktree_path, inp)`
  — validates BOTH `source` and `dest` through
  `_is_protected_path(..., worktree_path)` before ever calling
  `shutil.move()`, mirroring the exact fix already applied to
  `copy_file`'s `from_path`/`to_path` pair during tool #11's
  cross-cutting audit.
- **`app/agents/tools.py`**: `move_file_h` now delegates to the shared,
  hardened handler.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before), placed right after `copy_file`'s dispatch,
  which already used the identical two-sided validation pattern.

## Tests (real, not mocked — real files on disk, real reads/writes/
deletes)

`tests/test_move_file_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `move_file` appears in `CHAT_TOOLS`
  exactly once.
- **The proven exfiltration-and-delete finding, verified closed on
  both real call sites**: an outside-repo `source` is rejected, and
  the original file is confirmed to survive untouched with its content
  intact (through both `chat_agent.py`'s dispatch and
  `make_chat_handlers`).
- An outside-repo `dest` is rejected (re-confirms the pre-existing
  protection still works).
- A protected-filename `source` (`.env`) is rejected.
- Regression: a real in-repo move (confirmed via the source no longer
  existing and the destination holding the exact original content) and
  a real move across subdirectories (destination directory
  auto-created).

Also swept 2 pre-existing tests referencing `move_file`
(`test_new_tools.py::test_move_file`,
`test_batch11_policy_check_structural_chokepoint.py::
test_move_file_protected_destination_denied`) — both use safe relative
`source` values, confirmed unaffected by the new `source` check.

## Regression

Targeted sweep (new test file + memory_write + linear_create_issue
hardening): **23 passed.** Full suite re-run after this pass: **5262
passed, 52 skipped, 18 deselected, 0 failed** (up from 5254 before this
tool).

## Final verdict

**GREEN FLAG.**
