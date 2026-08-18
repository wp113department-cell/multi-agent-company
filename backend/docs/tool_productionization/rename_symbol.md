# Tool #23 — `rename_symbol` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations, all delegating to the real, shared engine
`app.repo_tools.ast_engine.rename_symbol()`:

1. `chat_agent.py`'s real interactive dispatch.
2. `make_refactor_agent_handlers()`'s `rf_rename_symbol`.
3. `make_chat_handlers()`'s own `rename_symbol_h`.

`old_name`/`new_name` are validated by the engine itself as valid Python
identifiers (`^[A-Za-z_][A-Za-z0-9_]*$`), so there's no injection surface
via the symbol names.

## Problems found (real, empirically verified — severe: a proven, live
cross-file rewrite outside the repo)

**None of the 3 implementations validated `directory` stayed inside the
repo.** `app.repo_tools.ast_engine.rename_symbol()` takes `directory`,
`rglob()`s it for files matching `file_pattern`, and **rewrites every
file that contains the symbol** — not a read, a real multi-file write.
Proved directly, before writing any fix, against a file in a directory
this session created and removed itself (never a real system path):

```python
result = await agent._execute_tool("rename_symbol", {
    "old_name": "old_function_name",
    "new_name": "PWNED",
    "directory": "/tmp/td_rename_symbol_outside/",  # absolute, outside the repo
})
```

— the call succeeded, and the outside file's real content was rewritten
from `old_function_name` to `PWNED` throughout. This is broader in blast
radius than a typical single-file write bug (tools #11/#12): it
recursively rewrites **every** matching file under whatever directory the
LLM points it at, not just one.

**Secondary, non-security finding**: `make_chat_handlers`'s own
`rename_symbol_h` never passed `confirm_large_batch` through to the AST
engine at all, despite `RENAME_SYMBOL_TOOL`'s own schema documenting it
as a real, LLM-settable field ("pass confirm_large_batch=true to
actually apply it"). That implementation could never apply a rename
touching more files than `Settings.rename_symbol_max_files` (default
200), even when the LLM explicitly confirmed it should — a real gap
against the tool's own documented contract, though a fail-safe one (it
always fell back to a no-write dry-run, never silently over-applied).

## Changes made

- **`app/tools/refactor/rename_symbol.py`** (new domain folder —
  AST-based, repo-wide code-refactoring tools): `RENAME_SYMBOL_TOOL`
  (schema, unchanged) and `validate_rename_symbol_directory(directory,
  worktree_path)` — the shared chokepoint, using the same
  `check_path_in_worktree` mechanism established in tool #9. Empty/
  omitted `directory` (meaning "repo root") is always allowed, matching
  every real call site's own existing default.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`** (both
  `rf_rename_symbol` and `rename_symbol_h`): all 3 real call sites now
  call the shared validator before resolving `directory`. Each site's own
  call into the AST engine is otherwise untouched — this pass shares
  only the validator, matching the pattern already used for
  `run_migration`/`seed_database`/`docker_build`.
- **`rename_symbol_h`** additionally now passes `confirm_large_batch`
  through to the AST engine, closing the secondary functionality gap.

## Tests (real, not mocked at the mechanism level — real file rewrites
throughout)

`tests/test_rename_symbol_hardening.py` (new, 12 tests):

- Schema shape check.
- Pure validator tests: empty directory allowed, a real relative
  in-repo directory allowed, an absolute outside-repo directory
  rejected, a `../` traversal rejected.
- **The exact proven exploit, run for real against all 3 implementations
  and confirmed closed**: a directory outside the repo is rejected before
  the AST engine ever runs, and the real, planted victim file is
  confirmed unchanged afterward — not just that an error was returned.
- **The `confirm_large_batch` gap, proven closed**: with the safety
  threshold patched low, a call without `confirm_large_batch` still
  returns a dry-run preview (no files touched), and the same call with
  `confirm_large_batch=true` now genuinely rewrites all matching files —
  proving the parameter reaches the engine for the first time.
- Regression: a real, legitimate in-repo rename through all 3 call sites,
  verified via the actual rewritten file content, not just a
  success-shaped return string.

## Regression

Targeted sweep (new test file + day1/day2_agents/audit_q_batch01 tests):
**244 passed.** Full suite re-run after this pass — see
`tool_enhance_tracking.md`'s row for this tool for the final count.

## Final verdict

**GREEN FLAG.**

A real, severe, proven multi-file-rewrite vulnerability closed with the
same, already-established validation mechanism used throughout this
initiative. A secondary functionality gap (silently-dropped
`confirm_large_batch`) closed alongside it. No functionality lost: every
real, legitimate in-repo rename continues to work exactly as before,
including the large-batch confirmation flow, which now actually works
for the implementation that previously couldn't ever apply it.
