# Tool #46 — `insert_after` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`insert_after_h`. **`chat_agent.py` had no dispatch for it at all**,
despite the tool already being advertised via `CHAT_TOOLS` — same
"advertised but never dispatched" class as tools #4/#6/#22/#25/#33/
#44/#45. `CHAT_TOOLS.count("insert_after") == 1` was verified directly
before making any change, applying the lesson from tool #44's
near-miss.

## Problems found

The handler's worktree-boundary handling was **already correct**: it
calls `_is_protected_path(path, repo_path)`, passing `repo_path` as
`worktree_path` — per `_is_protected_path`'s own docstring this enables
full `check_path_in_worktree()` containment checking, not just the bare
filename denylist. This is tool #11's fix, already applied here;
re-verified live (rejects both `.env` and an absolute outside-repo
path like `/etc/hostname`), not re-fixed.

**Deferred finding (documented, not fixed — same class already
deferred for tool #33's `delete_block`, identical reasoning):**
`pattern` is an LLM-controlled string passed directly to
`re.search(pattern, line)` once per line of the target file, with no
timeout. Python's stdlib `re` module has no timeout primitive, so
closing this needs real design work (a subprocess-based regex sandbox,
the third-party `regex` module's timeout support, or a length/
complexity cap on `pattern`) rather than a small local patch — logged
for its own future turn, matching `delete_block`'s report exactly.

The real, actionable gap was purely reachability: a fully-implemented
handler that no live interactive agent could ever invoke.

## Changes made

- **`app/tools/filesystem/insert_after.py`** (new): `INSERT_AFTER_TOOL`
  (schema, unchanged) and `insert_after_handler(root, worktree_path,
  inp)` — the existing, already-correct logic, moved here verbatim
  (not rewritten), used by both real call sites.
- **`app/agents/tools.py`**: `insert_after_h` now delegates to the
  shared handler.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before), delegating to the same shared handler —
  placed right after `insert_at_line`.

## Tests (real, not mocked — real files on disk, real reads/writes)

`tests/test_insert_after_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `insert_after` appears in
  `CHAT_TOOLS` exactly once.
- **The reachability fix, verified live**: a real insertion after a
  matching pattern (confirmed via the file's post-insert content) works
  through `chat_agent.py`'s new dispatch; a non-matching pattern
  returns `[WARN]`; a protected path (`.env`) and an absolute
  outside-repo path (`/etc/hostname`) are both rejected.
- Regression: `make_chat_handlers`' own `insert_after` still works
  correctly and still rejects an outside-repo path.

## Regression

Targeted sweep (new test file + github_create_issue hardening +
`test_chat_tools.py`/`test_day1_tools.py`/`test_day2_tools.py`): **369
passed, 1 skipped.** Full suite re-run after this pass: **5215 passed,
52 skipped, 18 deselected, 0 failed** (up from 5207 before this tool).

## Final verdict

**GREEN FLAG.**
