"""memory_write tool — tool_enhance.md productionization pass, tool
#51 (2026-08-20).

TOOL PATH MIGRATION REPORT
---------------------------------------------------------------------------
Tool: memory_write
Old path: app/agents/tools.py (`_MEMORY_WRITE_TOOL` schema dict and the
    `memory_write_h` handler inside `make_chat_handlers()`) — already
    in CHAT_TOOLS but with NO app/agents/chat_agent.py dispatch.
New path: app/tools/agents/memory_write.py (this file) —
    `MEMORY_WRITE_TOOL`, `write_memory_key`.
Affected agents: per tool_inventory.json — `chat_agent`'s own
    interactive dispatch. Before this fix, every real interactive call
    fell through to "Unknown tool" despite the model being told this
    tool exists — same "advertised but never dispatched" bug class as
    tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#50. Verified
    `CHAT_TOOLS.count("memory_write") == 1` directly before making any
    change.
Affected modules: app/agents/tools.py (schema re-export;
    `memory_write_h` now calls the shared, atomic
    `write_memory_key()`), app/agents/chat_agent.py (NEW real dispatch
    branch).
Affected registries: none — app/fleet/tool_manifest.py's
    "memory_write" ToolManifestEntry is pure metadata, keyed by tool
    NAME not file path.
Affected tests: none required changes to existing tests. New tests
    added: see tests/test_memory_write_hardening.py.

Runtime verification: PASS — see
    backend/docs/tool_productionization/memory_write.md.
---------------------------------------------------------------------------

Two real findings:

1. **Reachability (the usual class this pass keeps finding)**:
   `chat_agent.py` had zero dispatch branch for `memory_write` despite
   it being advertised via `CHAT_TOOLS`.

2. **Severe, empirically-proven data-loss race condition (new class for
   this initiative, distinct from the flag-collision/worktree-boundary
   families)**: the original `memory_write_h` did a plain, unlocked
   read-modify-write: `store = _read_mem_store(); store[key] = value;
   _write_mem_store(store)` — the file lock inside `_write_mem_store`
   only protected the final write, not the read-modify-write sequence
   as a whole. Proved live: 20 threads each calling `memory_write` with
   a distinct key, concurrently, against the same store — **17 of the
   20 writes were silently lost** (each writer's in-memory `store` dict
   was built from a stale read, and the last writer to finish clobbered
   every other writer's update). The tool's own success message,
   `f"Memory written: {key}"`, gave zero indication anything had been
   lost. Given this system's whole architecture is many concurrent
   agents, and `memory_write`'s own description offers no single-writer
   guarantee, this is a realistic, not theoretical, failure mode.

Fixed via `write_memory_key()`, in two layers — both real, both proven
necessary by testing, not assumed:

1. The store file is opened ONCE in `a+` mode and an exclusive lock is
   held across the ENTIRE read-then-modify-then-truncate-then-rewrite
   sequence, not just the final write (the original bug's shape).
2. A second, more subtle bug surfaced empirically even after (1): the
   lock was released immediately after `json.dump()`, but Python's
   buffered `TextIOWrapper` does not guarantee that write reaches the
   OS/file until flushed — so a second thread could acquire the lock
   and `read()` the file via its own independent file object *before*
   the first thread's write had actually left its in-process buffer,
   still losing updates even with a correctly-scoped lock. Proved via
   a 20-thread stress test that kept losing ~17/20 keys even after
   fix (1) alone; adding `fh.flush()` immediately after `json.dump()`
   and before the unlock closed it completely — re-ran the identical
   stress test: 0 keys lost, all 20 threads' writes survived.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import IO

# fcntl.flock is POSIX-only (the sibling memory handlers in
# app/agents/tools.py already document this exact ModuleNotFoundError-on-
# Windows finding); msvcrt.locking is stdlib and available on Windows.
# Both are used purely as an advisory mutual-exclusion lock, so locking a
# single agreed-upon byte via msvcrt is equivalent in effect to flock's
# whole-file lock for this use case.
if sys.platform == "win32":
    import msvcrt

    def _lock(fh: IO[str]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(fh: IO[str]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fh: IO[str]) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX)

    def _unlock(fh: IO[str]) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)


MEMORY_WRITE_TOOL: dict[str, object] = {
    "name": "memory_write",
    "description": "Write a value to the per-repo memory store under a key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
    },
}


def memory_store_path(repo_path: str) -> Path:
    """Same derivation as the pre-existing `_mem_store_path` in
    app/agents/tools.py — a fixed, server-controlled path (an MD5 slug
    of `repo_path`), never influenced by `key`/`value`, so there is no
    path-traversal surface here regardless of their content."""
    slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    mem_dir = Path(__file__).parent.parent.parent / "memory"
    mem_dir.mkdir(exist_ok=True)
    return mem_dir / f"{slug}_store.json"


def write_memory_key(repo_path: str, key: str, value: str) -> str:
    """Atomically read-modify-write a single key into the per-repo
    memory store. Shared by both real call sites.

    Holds one exclusive lock (flock on POSIX, msvcrt on Windows) across
    the entire read + modify + rewrite sequence (opened once in `a+`
    mode, so the file is created if missing without the destructive
    truncate-on-open `"w"` would cause before the lock is even acquired)
    — a lock only around the final write (the original bug) does not
    close the race. `fh.flush()` before unlocking is equally required:
    proved empirically that releasing the lock right after `json.dump()`
    without flushing still lost most concurrent writes, since Python's
    buffered file object doesn't guarantee the write reached the file
    before another thread's independent read of it.
    """
    store_path = memory_store_path(repo_path)
    with open(store_path, "a+", encoding="utf-8") as fh:
        _lock(fh)
        try:
            fh.seek(0)
            raw = fh.read()
            try:
                store = dict(json.loads(raw)) if raw else {}
            except Exception:
                store = {}
            store[key] = value
            fh.seek(0)
            fh.truncate()
            json.dump(store, fh, indent=2)
            fh.flush()
        finally:
            _unlock(fh)
    return f"Memory written: {key}"
