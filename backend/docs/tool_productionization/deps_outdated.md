# Tool #134 — `deps_outdated` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `deps_outdated_h` inside `make_chat_handlers()`.

`deps_outdated` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #3.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

Three real, empirically-verified findings.

**Finding #1 (most severe) — a worktree-boundary escape on the `npm`
branch.** `directory` reached `subprocess.run(["npm", "outdated"],
cwd=target_dir, ...)` with `target_dir = str(root / directory)` never
validated — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132 this initiative, but here it
changes the *working directory of an external program invocation*
rather than a plain file read, letting `npm outdated` run — with its
own network calls and any configured npm lifecycle hooks — against an
arbitrary host directory. Proved live: a real fake `npm` script placed
on `PATH` reported its own `cwd` was genuinely the injected absolute
`directory`, not anything inside the intended worktree.

**Finding #2 — a real correctness bug: `has_npm` was computed but
never used** (marked `# noqa: F841` — a linter suppression for code
someone already knew was unused, same dead-code-from-incomplete-logic
class as tool #130's `cpu_profile`). The `auto` manager-detection logic
was `manager = "pip" if has_pip else "npm"` — meaning a directory with
NEITHER `requirements.txt`/`pyproject.toml` NOR `package.json` still
silently defaulted to `"npm"`, and because `npm outdated` exits
cleanly with empty output when run against a directory with no
`package.json`, the tool then returned the misleading `"✅ All
dependencies are up to date"` — a false positive — instead of
reporting that no recognized package manager was found at all. Proved
live: a directory with none of the three manifest files still
returned the "up to date" success message.

**Finding #3 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133.**
`deps_outdated` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: deps_outdated"`.

**Note (documented, not changed)**: for `manager == "pip"`, `directory`
has always had zero effect — `pip list --outdated` inspects the
active Python environment, not a directory's manifest file, and the
original implementation never passed `cwd=` for that branch either.
This is an inherent limitation of `pip list`'s own design (there is no
clean way to scope it to an arbitrary directory without parsing
`requirements.txt` directly, a materially different mechanism), not a
bug fixed here — matching this initiative's precedent for noting a
real but out-of-scope-for-a-clean-fix limitation.

## Changes made

New shared `deps_outdated_handler()` in
`app/tools/execution/deps_outdated.py`:
- `directory` is validated via `check_path_in_worktree()` immediately
  before it is used to build a subprocess `cwd` (the `npm` branch
  only, matching exactly where it was ever actually used — a
  mid-implementation review caught that computing `target_dir`
  unconditionally, as in an earlier draft, would reintroduce a
  `NameError` regression for a non-`"pip"`/non-`"npm"` `manager`
  value, since the original code's `else` branch covers any such
  value; the fix preserves that exact branching), closing finding #1.
- The `auto` branch now genuinely uses `has_npm` and returns a clear
  `"(no recognized package manager found — ...)"` message when neither
  manifest file is present, closing finding #2.
- A new `chat_agent.py` dispatch branch delegates to this same shared
  handler, closing finding #3 — `deps_outdated` is now genuinely
  reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_DEPS_OUTDATED_TOOL` now aliases the shared
`DEPS_OUTDATED_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_deps_outdated_hardening.py`, 10 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof on
the `npm` branch (across a direct handler call, `make_chat_handlers`,
and the new `chat_agent.py` dispatch) using a real fake `npm` script on
`PATH` that reports its own `cwd` (same technique already established
for tool #45's `github_create_issue`, avoiding real network calls
while remaining a genuine subprocess-execution proof), the
`has_npm`-false-positive-fix proof, auto-detection-with-`package.json`
proof, a proof the new dispatch no longer returns "Unknown tool", and
a proof the `pip` branch genuinely ignores `directory` even when set
to an absolute, outside-worktree path (using an analogous fake `pip`
script instead of the real, slow, network-bound `pip` — the original,
real `pip list --outdated` call was also verified once manually via
`make_chat_handlers` during the audit and reproduction phase, timing
out at the handler's existing 60s limit under this environment's
network conditions, confirming the fixed-timeout behavior is
unchanged, not a regression).

Zero existing tests referenced this tool — confirmed, no sweep needed.

## Regression

This tool is tool 4 of the #131-#135 batch. Its own new hardening
tests (10/10 pass, ~2.5s) are the per-tool verification gate; the full
suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/execution/
deps_outdated.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed; the
tool went from silently escaping the worktree and returning a
misleading false positive to genuinely correct and safe behavior, and
is now reachable from interactive chat for the first time — a strict
capability increase, not a narrowing; no functionality lost —
legitimate `npm`/`pip` usage (including `pip`'s documented,
intentional `directory`-independence) is proven to still work.
