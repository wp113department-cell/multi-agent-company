# Tool #51 — `memory_write` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`memory_write_h`, backed by shared `_read_mem_store()`/
`_write_mem_store()` helpers. **`chat_agent.py` had no dispatch for it
at all**, despite the tool already being advertised via `CHAT_TOOLS` —
same "advertised but never dispatched" class as tools #4/#6/#22/#25/
#33/#44/#45/#46/#48/#50. `CHAT_TOOLS.count("memory_write") == 1`
verified directly before making any change.

## Problems found

**Finding 1 (the usual class): reachability.** Zero interactive
dispatch, despite advertisement.

**Finding 2 (new class for this initiative, severe, empirically
proven): a genuine data-loss race condition.** The original
`memory_write_h` did a plain, unlocked read-modify-write:
`store = _read_mem_store(); store[key] = value; _write_mem_store(store)`.
The file lock inside `_write_mem_store` only protected the final write
call, not the read-modify-write sequence as a whole.

Proved live: 20 threads, each calling `memory_write` with a distinct
key, concurrently, against the same store:

```python
threads = [threading.Thread(target=writer, args=(f"key{i}", f"value{i}")) for i in range(20)]
```

**17 of the 20 writes were silently lost.** Each writer's in-memory
`store` dict was built from a stale read; the last writer to finish
clobbered every other writer's update. The tool's own success message,
`"Memory written: {key}"`, gave zero indication anything had been
lost — every caller believed their write succeeded. Given this
system's whole architecture is many concurrent agents, and the tool's
own description offers no single-writer guarantee, this is a realistic
failure mode, not a theoretical one.

**A second, more subtle bug surfaced even after fixing the lock
scope.** Widening the lock to cover the full read+modify+write
sequence (opening the file once, holding one exclusive lock across the
whole operation) was NOT sufficient on its own — the 20-thread stress
test still lost ~17/20 keys. Root cause, found by direct
experimentation, not assumed: the lock was released immediately after
`json.dump()`, but Python's buffered `TextIOWrapper` does not guarantee
a write has reached the OS file the moment `json.dump()` returns — a
second thread could acquire the lock and `read()` the file (via its own
independent file object) *before* the first thread's write had
actually left its in-process buffer. Adding `fh.flush()` immediately
after `json.dump()`, before the unlock, closed this completely.

## Changes made

- **`app/tools/agents/memory_write.py`** (new): `MEMORY_WRITE_TOOL`
  (schema, unchanged) and `write_memory_key(repo_path, key, value)` —
  opens the store file once in `a+` mode, holds one exclusive lock
  (flock on POSIX, msvcrt on Windows — matching the existing,
  already-fixed cross-platform pattern documented right next to the
  original handler in `app/agents/tools.py`) across the entire
  read + modify + truncate + rewrite + **flush** sequence, then
  unlocks. Both real call sites now use this.
- **`app/agents/tools.py`**: `memory_write_h` now delegates to the
  shared, fixed function.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before). No confirmation gate — unlike
  `create_pr`/`github_comment`/`linear_create_issue`, this is a purely
  local, non-externally-visible write with no third-party consequence.

## Tests (real, not mocked — real threads, real file I/O against a real
JSON store on disk, every time)

`tests/test_memory_write_hardening.py` (new, 7 tests):

- Schema shape check, and confirms `memory_write` appears in
  `CHAT_TOOLS` exactly once.
- **The proven lost-update race, verified closed**: 20 real threads
  calling `write_memory_key()` concurrently — 0 keys lost (re-run 3x
  for confidence during development, consistently 0/20 lost after the
  fix, vs. a consistently-reproducible ~17/20 lost before it).
- The same closed-race proof repeated through the REAL
  `ChatAgent._execute_tool` dispatch path, via `asyncio.gather` over 20
  concurrent tool calls.
- The reachability fix, verified live: a real write through
  `chat_agent.py`'s new dispatch, confirmed via the store file's actual
  on-disk content.
- Regression: cross-implementation, cross-tool consistency — a write
  via `chat_agent.py` is visible to `make_chat_handlers`' `memory_read`
  and vice versa, and `make_chat_handlers`' own `memory_write` still
  works.

Also confirmed the new module's memory-store path derivation resolves
to the exact same directory as the pre-existing `_mem_store_path` in
`app/agents/tools.py` (both compute `<backend>/app/memory`) — critical,
since `memory_read` (a separate, not-yet-reached tracking row #167)
still uses the old derivation and must keep seeing what `memory_write`
writes.

## Regression

Also swept the existing test files referencing "memory_write" as a
string (`test_fleet_tool_manifest.py`, `test_chat_agent_memory_wiring.py`,
`test_memory_hooks.py`) — confirmed all reference an unrelated concept
(`ChatAgent._memory_write_outcome`, a DB-backed lesson-store method, not
this tool) or pure manifest-presence metadata; none touch the changed
behavior. All 54 passed.

Targeted sweep (new test file + linear_create_issue + kill_process
hardening): **21 passed.** Full suite re-run after this pass: **5254
passed, 52 skipped, 18 deselected, 0 failed** (up from 5247 before this
tool).

## Final verdict

**GREEN FLAG.**
