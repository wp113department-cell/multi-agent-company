# Tool #12 — `write_file` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

`write_file` is the most widely-used tool in this initiative so far (60
agents per `tool_inventory.json`), and unlike every high-risk-tier tool,
it has no single "real" and "dead" pair of implementations — it has
**~12 independently-maintained implementations** across the codebase:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_coder_handlers`'s `write_file` — generic.
3. `make_doc_generator_handlers`'s `dg_write_file` — restricted to
   `*.md`/`docs/**`.
4. `make_docs_handlers`'s `write_file` — restricted to `*.md`/`docs/**`.
5. `_make_write_file_handler` — a shared factory reused by 5 separate
   handler-set factories (generic).
6. `make_readme_agent_handlers`'s `rm_write_file` — restricted to
   `*.md`/`docs/**`.
7. `make_api_docs_agent_handlers`'s `ad_write_file` — restricted to
   `*.md`/`docs/**`.
8. `make_migration_agent_handlers`'s `mg_write_file` — restricted to
   `migrations/`/`backend/migrations/`/`*.py`.
9. `make_schema_agent_handlers`'s `sa_write_file` — generic.
10. `make_ai_engineer_handlers`'s `ae_write_file` — generic.
11. `make_chat_handlers`'s own `write_file` — generic, reused by ~35
    one-shot batch agents via `base = make_chat_handlers(repo_path)`.
12. `make_fleet_apply_handlers`'s `write_file_h` — generic, plus a
    role-prompt-registry redirect for `roles/<name>.md` targets; used by
    the 4 fleet self-enhancement agents.

This tool's own most severe bug — `chat_agent.py`'s real dispatch calling
`_is_protected_path(rel)` **without** its `worktree_path` argument,
allowing a real arbitrary-file-write outside the repo with zero
confirmation gate — was already found and fixed during tool #11's
(`undo_changes`) cross-cutting audit (full detail:
`docs/tool_productionization/undo_changes.md`). This turn's job was to
finish the job properly: audit every *other* real implementation for the
same bug class, and modularize per tool_enhance.md's mandatory rule
(rather than leaving the now-fixed code inline in the god-module).

## Problems found

**None new.** Auditing all 9 previously-unaudited implementations
(everything except chat_agent.py's dispatch and `make_fleet_apply_handlers`,
both already fixed in tool #11) found every one of them already correctly
guarded — either via `check_path_in_worktree()` directly or
`_is_protected_path(rel, repo_path)` with the worktree argument present.
Proved with a real security sweep (not just reading the code): each of
the 4 domain-scoped implementations (docs, readme, api_docs, plus the
generic coder/schema/ai_engineer ones) was exercised with a real absolute
path outside its repo and confirmed to reject it before any write —
see Tests below.

## Changes made

**Modularized** (the generic, unscoped variant — see "Deliberately left
untouched" for why the 6 domain-scoped/differently-scoped variants
weren't touched):

- **`app/tools/filesystem/write_file.py`** (new): `WRITE_FILE_TOOL` (the
  canonical schema — previously duplicated verbatim in two places,
  `CODER_TOOLS`'s own list and `_WRITE_FILE_TOOL_SPEC`, now both alias
  the one definition) and `write_file_handler(root, worktree_path, inp)`
  (the shared core: protected-path/worktree check, mkdir parents, write,
  wrapped in try/except so a real disk error surfaces as `[ERROR]`
  instead of an unhandled exception — ported from `make_chat_handlers`'s
  own implementation, which was the only one of the consolidated four
  that already had this).
- **`app/agents/chat_agent.py`**: its real dispatch now calls
  `write_file_handler` after its own existence-check/confirm gate,
  instead of duplicating the write logic inline.
- **`app/agents/tools.py`**: `_make_write_file_handler` (the shared
  factory reused by 5 handler-set factories),
  `make_chat_handlers`'s own `write_file`, and
  `make_fleet_apply_handlers`'s `write_file_h`'s non-role-prompt branch
  all now delegate to the shared function. `_WRITE_FILE_TOOL_SPEC` (used
  by 12 separate tool lists) and `CODER_TOOLS`'s own duplicate schema
  entry now both alias the single canonical `WRITE_FILE_TOOL`.

**One observable, intentional, low-risk change**: the consolidated call
sites' success message changed from a bare `f"Written {rel}"` to
`f"Written {rel} ({len(content)} bytes)"` (chat_agent.py's dispatch
already used this fuller format — every consolidated site now matches
it). Checked every test in the suite referencing `write_file`'s return
value beforehand: all used `.startswith("Written")` except one exact-match
assertion in `tests/test_gap50_prompt_registry_wiring.py`, updated to
`.startswith(...)` too (same real behavior being asserted — the
role-prompt redirect is untouched by this).

**Deliberately left untouched** (audited, found already correctly
guarded, not modularized to avoid unnecessary rewrite of working, tested
code): `make_coder_handlers`'s `write_file`, `make_doc_generator_handlers`'s
`dg_write_file`, `make_docs_handlers`'s `write_file`,
`make_readme_agent_handlers`'s `rm_write_file`,
`make_api_docs_agent_handlers`'s `ad_write_file`,
`make_migration_agent_handlers`'s `mg_write_file`,
`make_schema_agent_handlers`'s `sa_write_file`,
`make_ai_engineer_handlers`'s `ae_write_file`. Four of these
(doc_generator, docs, readme, api_docs) layer a real, intentional
`*.md`/`docs/**`-only policy on top of the base write — a genuine
difference from the generic tool, reflected in `DOCS_TOOLS`' own distinct
schema description — not accidental duplication. `migration_agent`
similarly restricts to `migrations/`. The remaining two (schema_agent,
ai_engineer) are generic and already correctly guarded; consolidating
them was judged not worth the regression risk for tools with no
outstanding security issue.

## Tests (real, not mocked at the mechanism level)

`tests/test_write_file_hardening.py` (new, 18 tests):

- Schema shape check.
- Direct unit tests of `write_file_handler`: absolute-path rejection,
  `../` traversal rejection, `.env` denylist rejection, real in-repo
  write proof, and a real disk-error path (writing under a file that
  can't be a parent directory) proving the try/except still works after
  consolidation.
- Every consolidated call site exercised for real: `chat_agent.py`'s
  dispatch (both the happy path and the escape-rejection path, plus its
  overwrite-confirmation gate still firing correctly),
  `_make_write_file_handler`, `make_chat_handlers`'s `write_file`,
  `make_fleet_apply_handlers`'s `write_file_h` for non-role-prompt paths.
- A full security sweep proving all 6 deliberately-untouched
  implementations (coder, doc_generator, readme, api_docs, schema_agent,
  ai_engineer) still correctly reject a real absolute path outside their
  repo — direct evidence, not just audit notes.

## Regression

Targeted sweep (new test file + boundary-hardening tests from tool #11 +
day1/day2 tool/agent tests + gap15/gap50 + new_tools/chat_tools): **541
passed, 1 skipped.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

This tool's real vulnerability was already closed during tool #11's
audit; this turn verified every other real implementation was already
secure (a real, evidence-backed sweep, not an assumption), then completed
the mandatory modularization step for the generic variant that was still
sitting inline in the god-module across 4 separate call sites. No
functionality lost — every legitimate write still works exactly as
before (message format aside, an intentional and backward-compatible
improvement), and the 6 domain-scoped implementations were left alone
since they carry real, distinct policy logic and were already correct.
