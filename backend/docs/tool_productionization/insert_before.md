# Tool #48 — `insert_before` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`insert_before_h` — the exact mirror-image of tool #46's
`insert_after_h` (insert BEFORE instead of AFTER a matching pattern).
**`chat_agent.py` had no dispatch for it at all**, despite the tool
already being advertised via `CHAT_TOOLS` — same "advertised but never
dispatched" class as tools #4/#6/#22/#25/#33/#44/#45/#46.
`CHAT_TOOLS.count("insert_before") == 1` verified directly before
making any change.

## Problems found

The handler's worktree-boundary handling was **already correct**: it
calls `_is_protected_path(path, repo_path)`, passing `repo_path` as
`worktree_path` — enabling full `check_path_in_worktree()` containment
checking (tool #11's fix, re-verified live: rejects both `.env` and an
absolute outside-repo path `/etc/hostname`).

**Deferred finding (documented, not fixed — same class already
deferred for tool #33's `delete_block` and tool #46's `insert_after`,
identical reasoning):** `pattern` is an LLM-controlled string passed
directly to `re.search(pattern, line)` once per line with no timeout.
Python's stdlib `re` module has no timeout primitive — logged for its
own future turn, matching the two sibling reports.

The real, actionable gap was purely reachability: a fully-implemented
handler that no live interactive agent could ever invoke.

## Changes made

- **`app/tools/filesystem/insert_before.py`** (new): `INSERT_BEFORE_TOOL`
  (schema, unchanged) and `insert_before_handler(root, worktree_path,
  inp)` — the existing, already-correct logic, moved here verbatim
  (not rewritten), used by both real call sites.
- **`app/agents/tools.py`**: `insert_before_h` now delegates to the
  shared handler.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before), placed right after tool #46's `insert_after`
  dispatch.

## Tests (real, not mocked — real files on disk, real reads/writes)

`tests/test_insert_before_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `insert_before` appears in
  `CHAT_TOOLS` exactly once.
- **The reachability fix, verified live**: a real insertion before a
  matching pattern (confirmed via the file's post-insert content)
  works through `chat_agent.py`'s new dispatch; a non-matching pattern
  returns `[WARN]`; a protected path (`.env`) and an absolute
  outside-repo path (`/etc/hostname`) are both rejected.
- Regression: `make_chat_handlers`' own `insert_before` still works
  correctly and still rejects an outside-repo path.

## Regression

Targeted sweep (new test file + insert_at_line + insert_after hardening
+ `test_chat_tools.py`/`test_day1_tools.py`/`test_day2_tools.py`): **378
passed, 1 skipped.** Full suite re-run after this pass: **5232 passed,
52 skipped, 18 deselected, 0 failed** (up from 5224 before this tool).

## Final verdict

**GREEN FLAG.**
