# Tool #221 — `list_migrations` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Module-level function `list_migrations()` in `app/agents/tools.py`,
one of the 3 Day-53 "real introspection, never a guess" tools
(alongside `list_registered_agents` and `list_all_tool_specs`). Shared
by exactly 1 real agent, confirmed via direct grep —
`migration_guide_doc_agent` — matching `tool_inventory.json`'s
`agent_count: 1` exactly. Deliberately NOT in `CHAT_TOOLS` (confirmed
via membership check). Takes no meaningful input at all (`inp` is
unused; schema declares no properties).

Always introspects THIS backend's own `migrations/versions/` directory
(a fixed, self-referential path computed from `__file__`, never a
per-agent `repo_path` or any user input) — real, AST-parsed data (file
name, revision id, down_revision, docstring) for
`migration_guide_doc_agent` to write a migration guide from, never
guessed from file names alone.

Already has thorough real-filesystem test coverage in
`tests/test_gap53_doc_generators.py::TestListMigrations` (3 tests,
including a real regression guard for a bug found while originally
building this tool: Alembic's generated files use annotated
assignments — `ast.AnnAssign` — not plain `ast.Assign`, which an
earlier draft parser missed entirely) — re-read and re-verified as
still passing before making any change.

## Problems found

None. No security vulnerability and no functional bug found — this
audit's real conclusion. Specifically investigated and ruled out:

- **Injection surface**: none — the glob pattern (`"*.py"`) and target
  directory are both fixed; nothing in `inp` reaches any path or
  filter.
- **Crash on a missing directory**: guarded explicitly
  (`if not versions_dir.exists(): return "[]"`).
- **Crash on a malformed/unparseable migration file**: the AST parse
  is wrapped in its own `try`/`except Exception: continue` — one bad
  file is skipped, not fatal to the whole call.
- **Arbitrary code execution from a malicious migration file**: the
  file is only ever passed to `ast.parse()`, never `exec`'d or
  `import`ed — parsing untrusted-looking Python source with `ast` does
  not execute it.

## Changes made

Extracted into `app/tools/filesystem/list_migrations.py`
(`LIST_MIGRATIONS_TOOL`, `list_migrations_handler`) with zero intended
behavior change. The one real thing to get right during this move: the
self-referential path calculation
(`Path(__file__).resolve().parent...`) needed adjusting because the
new module lives one directory level deeper
(`app/tools/filesystem/`) than the old `app/agents/tools.py` location
— changed from 3 `.parent`s to 4 to still land on the real
`backend/migrations/versions/` directory. **Verified live, not
assumed**: before wiring anything into `tools.py`, called the new
module directly and confirmed it found all 48 real migration files,
including the specific `001_initial_schema.py` regression case the
existing test suite checks.

`app/agents/tools.py` now re-exports both names for backward
compatibility (`_LIST_MIGRATIONS_TOOL = LIST_MIGRATIONS_TOOL`,
`list_migrations = list_migrations_handler`) — the real consumer agent
(`migration_guide_doc_agent`) continues
`from app.agents.tools import list_migrations` unchanged, verified by
identity.

## Tests

Existing `TestListMigrations` (3 tests) re-run and confirmed passing
unchanged — full file (32 tests) also re-run clean.

New file `tests/test_list_migrations_hardening.py`, 5 tests: schema
check, `CHAT_TOOLS` non-membership, the path-resolution-after-the-move
proof (the real risk in this modularization), and two object-identity
proofs (the re-exported handler in `tools.py`, and the real consumer
agent's wired handler) that the move introduced no behavior change.

## Regression

This tool's own new hardening tests (5/5 pass) plus
`test_gap53_doc_generators.py` + `test_new_tools.py` +
`test_final_session.py` (98 passed total).

Verified via `mypy` (2 touched files, clean) and `ruff check` (2
touched files, clean) BEFORE claiming GREEN_FLAG. Also verified
`CHAT_TOOLS` still has zero duplicate names (186 entries) and that
`app.agents.tools` reloads cleanly.

## Final verdict

**GREEN FLAG.** Thorough audit found no security vulnerability and no
functional defect. The one real risk in this turn — a path-depth
mismatch after moving the file — was caught and fixed by verifying
live before wiring anything in, not assumed correct. No functionality
lost — the real consumer agent verified via identity to still use the
exact same shared handler; all 48 real migration files still parse
identically. Agent alignment verified: PASS.
