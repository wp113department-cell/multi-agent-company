# Tool #24 — `replace_function` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three implementations. This tool's worktree-boundary check was already
fixed for all 3 during tool #11's cross-cutting audit — re-verified
directly this turn (a real absolute path outside the repo still gets
rejected), not assumed.

1. `chat_agent.py`'s real interactive dispatch — a manual, indentation-
   aware line scan: finds `def <name>(`/`async def <name>(` at any
   indentation (so it matches class methods too), then replaces through
   the next same-or-lower-indent, non-blank, non-decorator/comment line.
2. `make_chat_handlers()`'s own `replace_function` — the identical
   algorithm, independently duplicated.
3. `make_refactor_agent_handlers()`'s `rf_replace_function` — a
   completely different, regex-based implementation.

## Problems found (real, empirically verified — severe: a genuine "this
feature has never worked" bug)

**`rf_replace_function` read the wrong input field.** `REPLACE_FUNCTION_TOOL`'s
own schema — the one `refactor_agent` itself advertises to its LLM —
documents the replacement-code field as `new_code`. The handler read
`inp["new_body"]` instead. Proved directly: a real call built exactly the
way the schema instructs raised an unhandled `KeyError('new_body')`.
The agent framework catches handler exceptions centrally
(`_run_tool_with_retry` in `app/agents/base_graph.py`, confirmed by
reading it directly — turns any exception into an `[ERROR] ... raised:
...` string, never crashing the whole run), so this never took down an
agent — but it means **every real `refactor_agent` call to this tool has
failed 100% of the time** since it was written, with no existing test
ever catching it (a hand-constructed test dict happening to use the
schema-mismatched field name would silently "work" while never
exercising a real, schema-conformant call).

**A second, related gap in the same handler**: its regex
(anchored on a line starting with `def`/`async def` with no leading
whitespace) only matched **unindented, top-level** function definitions
— it could never match a class method. Both other implementations
already handle methods correctly (they `.strip()` each line before
comparing).

## Design decision

Rather than fix `rf_replace_function`'s two independent bugs in place
(wrong field name + method-blind regex), switched it onto the shared,
already-correct implementation that the other two call sites already
used successfully — a strict capability increase (finds everything the
regex version could, plus class methods it never could), not a
narrowing, and eliminates an independently-broken second algorithm
entirely rather than maintaining two.

## Changes made

- **`app/tools/filesystem/replace_function.py`** (new): `REPLACE_FUNCTION_TOOL`
  (schema, unchanged) and `replace_function_handler(root, worktree_path,
  inp)` — the proven, already-correct line-scan algorithm (from
  `chat_agent.py`/`make_chat_handlers`), extracted so all 3 real call
  sites share one implementation.
- **`app/agents/chat_agent.py`**, **`app/agents/tools.py`** (`replace_function`
  and `rf_replace_function`): all 3 now delegate to the shared handler.
  Removed the now-unused local `import re as _re` from
  `make_refactor_agent_handlers` (nothing else in that scope used it).

## Tests (real, not mocked at the mechanism level — real file rewrites
throughout)

`tests/test_replace_function_hardening.py` (new, 9 tests):

- Schema shape check (confirms `new_code` is required, `new_body` isn't
  even a documented field).
- **The exact proven "always crashed" bug, verified closed**: a real,
  schema-conformant call through `refactor_agent`'s handler no longer
  raises, and genuinely rewrites the file.
- **The method-blind-regex gap, verified closed**: a real class method
  replacement through `refactor_agent`'s handler now succeeds — this
  specific case was structurally impossible for the old regex to ever
  match.
- Regression: the two implementations that already worked (top-level
  function replacement via `chat_agent.py` and `make_chat_handlers`,
  protected-path denial, missing-file error, missing-function error) all
  verified unchanged. A dedicated worktree-boundary-escape re-check
  against the shared handler directly.

## Regression

Targeted sweep (new test file + day2_agents/chat_tools/file_ops boundary
hardening/rename_symbol hardening): **258 passed.** Full suite re-run
after this pass — see `tool_enhance_tracking.md`'s row for this tool for
the final count.

## Final verdict

**GREEN FLAG.**

A genuinely broken tool (100% failure rate for every real
`refactor_agent` call) fixed by consolidating onto an already-correct,
already-proven implementation — gaining real capability (class-method
support) in the process, not just fixing the crash. No functionality
lost for the two implementations that already worked.

## Correction (added during tool #57's turn, 2026-08-20)

While building `replace_class` (tool #57), the exact same boundary-
detection algorithm used here was found to have a second, independent,
real bug: the end-boundary scan skipped lines starting with `"#"`/`"@"`,
meaning a decorator or comment belonging to the NEXT function/method
got silently swallowed into (and discarded along with) the replaced
target's region. Proved live: replacing `foo()` in a file where
`bar()` was immediately preceded by `@decorator` deleted that decorator
line entirely from the output — a real, functional regression (not
cosmetic) for any decorated function immediately following a
`replace_function` call.

Fixed by removing the `#`/`@` special-case from
`replace_function_handler`'s own boundary scan (the same fix applied to
the new `replace_class_handler`): the end boundary is simply the next
non-blank line at or below the target's own indentation, full stop. A
new regression test
(`test_chat_agent_replace_function_preserves_next_functions_decorator`
in `tests/test_replace_function_hardening.py`) proves this closed. Full
account and the twin fix: `docs/tool_productionization/replace_class.md`.
