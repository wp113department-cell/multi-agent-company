# Tool #135 — `env_diff` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `env_diff_h` inside `make_chat_handlers()`.

`env_diff` is in `CHAT_TOOLS` and registered in `make_chat_handlers()`'s
handlers dict, but `chat_agent.py`'s `_execute_tool()` had zero
dispatch branch for it — see finding #3.

1 existing test file references this tool (`test_new_tools.py`,
`test_env_diff`/`test_env_diff_no_diff`) — re-run and confirmed passing
unchanged.

## Problems found

Three real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape on BOTH `example` and
`actual`, a genuine environment-variable-NAME disclosure oracle.**
`env_diff_h` built `root / str(inp.get("example", ...))` and `root /
str(inp.get("actual", ...))` without checking whether either was
already absolute — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134 this initiative. Even
though this tool never returns variable *values* (only key names), the
key names of an arbitrary `.env`-shaped file anywhere on the host are
themselves sensitive — they can confirm which secrets an unrelated
project on the same host uses. Proved live: pointing both fields at
real files outside the intended worktree genuinely disclosed a key
name unique to the outside file.

**Finding #2 — a real robustness gap: an uncaught crash on a real
permission error.** Neither `_keys()`'s `fp.read_text()` call was
wrapped in a `try/except`, same class already fixed for tools
#70/#72/#76. Proved live with a real `chmod 000` file: a genuine
`PermissionError` propagated straight out of the handler.

**Finding #3 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134.**
`env_diff` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: env_diff"`.

## A regression caught and fixed during this same turn

The first implementation attempt reused `check_path_in_worktree()`
wholesale, matching every other filesystem-tool fix so far this
initiative. That function also runs the general secrets/`.env`
DENYLIST (`app/policy/engine.py::_matches_path_rule`) on top of the
worktree check — correct for tools that return file *content*, but
this tool's entire documented purpose is comparing `.env`/
`.env.example`-shaped files by key name only; it never returns values.
Reusing the full denylist verbatim broke the tool's own default
behavior outright — verified live: calling `env_diff({})` (the tool's
documented default, comparing `.env.example` against `.env`) was
rejected with `"[POLICY DENIED] ... matches .env pattern"`. Caught
immediately via the same live-verification step used for every other
tool this initiative, before the turn was considered complete — not
shipped.

## Changes made

New shared `env_diff_handler()` in `app/tools/filesystem/env_diff.py`:
- Both `example` and `actual` are validated for worktree containment
  via a new, narrow `_worktree_boundary_only()` helper — it replicates
  exactly the realpath-based, symlink-safe boundary check from
  `check_path_in_worktree()` but deliberately omits its denylist,
  since disclosing only key names (never values) does not carry the
  risk that denylist exists to prevent. This closes finding #1
  without reintroducing the regression described above.
- `_keys()` now catches read errors and returns an empty set with the
  error noted (surfaced as a clean `[ERROR] Could not read <path>:
  ...]`), closing finding #2 without turning a legitimate "one file
  present, one absent" comparison into a hard failure.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #3 — `env_diff` is now genuinely reachable
  from interactive chat for the first time.

`app/agents/tools.py`'s `_ENV_DIFF_TOOL` now aliases the shared
`ENV_DIFF_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_env_diff_hardening.py`, 13 tests: schema check,
duplicate-registration check, worktree-escape-blocked proof for both
`example` and `actual` (across `make_chat_handlers`, the new
`chat_agent.py` dispatch, and a direct handler call) with assertions
the outside file's key names never leak into the result, a real
permission-error crash-fix proof, a proof the new dispatch no longer
returns "Unknown tool", **an explicit regression test for the
mid-turn-caught denylist bug** (legitimate default `.env`/
`.env.example` usage must not be blocked), and further legitimate-usage
regression (no-differences case, extra-keys case, both-files-missing
case) across both real access paths.

Existing tests re-run and confirmed passing: `test_new_tools.py`'s
`test_env_diff`/`test_env_diff_no_diff` (2/2) — their continued passing
is itself live confirmation the narrow-check fix preserves the tool's
real default behavior exactly.

## Regression

This tool is tool 5 of the #131-#135 batch, completing it. Its own new
hardening tests (13/13 pass) and the directly-referencing existing
test file (2/2 pass) are the per-tool verification gate; the full
suite runs now that the batch is complete, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/env_diff.py`
sweep (102 files clean, re-run after the mid-turn fix), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed; a
real regression from an over-broad initial fix was caught and
corrected within the same turn via this initiative's own live-
verification discipline, before it could ship; the tool is now
genuinely reachable from interactive chat for the first time and its
own documented default behavior is proven to still work exactly as
before; tool-specific and directly-referencing regression tests clean.
