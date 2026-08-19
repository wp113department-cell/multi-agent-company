# Tool #44 — `github_comment` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`github_comment_h`. **`chat_agent.py` had no dispatch for it at all** —
the exact same "advertised but never dispatched" bug class as tools
#4/#6/#22/#25/#33. A fully-implemented, already-safe handler that no
live agent could ever invoke through the interactive surface.

**Correction, made transparently:** the first pass of this audit
incorrectly concluded `github_comment` wasn't in `CHAT_TOOLS` at all
(missed `_GITHUB_COMMENT_TOOL` at its actual location, under the
"Day 3G — External integrations" section of the `CHAT_TOOLS` list,
~90 lines further down than the other git/GitHub tool entries this
initiative usually touches). On that wrong premise, this was framed to
the user as a scope-expansion question via `AskUserQuestion` rather
than the routine "wire up the missing dispatch" fix it actually was.
The user's answer ("wire it into interactive chat") still produced the
correct outcome, but re-adding `_GITHUB_COMMENT_TOOL` to `CHAT_TOOLS`
created a real, genuine duplicate entry — caught by the full-suite
regression run (`test_chat_tools.py::test_chat_tools_has_no_duplicates`
and two sibling tests), not assumed. Fixed by removing the duplicate
insertion; the tool was already correctly advertised at its original
location. The rest of this report reflects the corrected, accurate
picture: this was always an "advertised but never dispatched" bug, not
a reachability-from-zero one.

## Problems found

The handler's own command-building logic was already safe: `number` is
coerced via `int(...)` (can't be flag-shaped), `body` is passed as a
distinct argv item (list-args, no `shell=True`, no injection surface),
`kind` only toggles a two-way ternary. There was no vulnerability to
fix in the existing logic — the real gap was **reachability**, and the
manifest (`app/fleet/tool_manifest.py`) already documents
`permissions=["write_remote"]` for it: a real, publicly-visible
external write with real-world consequence, sitting completely
unreachable.

Since this is a scope decision (expand what the interactive agent can
do) rather than a routine "fix the existing wiring bug" pattern, this
was raised to the user via `AskUserQuestion` rather than assumed. User
chose: **wire it into interactive chat**, rather than leaving it
hardened-but-unreachable.

## Changes made

- **`app/tools/git/github_comment.py`** (new): `GITHUB_COMMENT_TOOL`
  (schema, unchanged) and `github_comment_command(number, body, kind)`
  — the shared, already-safe argv builder, now used by both
  implementations instead of being duplicated inline.
- **`app/agents/tools.py`**: `_GITHUB_COMMENT_TOOL` was already in
  `CHAT_TOOLS` (see Correction above); `github_comment_h` now calls
  the shared builder.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before). Since posting a GitHub comment is a real,
  publicly-visible external write — the same risk category `create_pr`
  (tool #2) is in — the new dispatch gates the actual post behind a
  real `self._confirm()` dialog showing the exact `gh` command and
  comment body, mirroring `create_pr`'s own established confirmation
  pattern exactly (confirm AFTER all fields are resolved, so the human
  sees real content, not a preview of unresolved fields).

## Tests (real, not mocked at the mechanism level for the parts that
matter — a fake `gh` script on `PATH` so no real, live GitHub comment
is ever posted during testing, but the real dispatch/confirmation/
subprocess-invocation path is genuinely exercised)

`tests/test_github_comment_hardening.py` (new, 9 tests):

- Schema shape check, and confirms `github_comment` is now present in
  `CHAT_TOOLS` (previously absent).
- Pure command-builder tests: `issue`/`pr`/unknown-kind argv shapes.
- **The reachability fix, verified live**: a declined confirmation
  posts nothing (`[DENIED]`); an approved confirmation genuinely
  invokes the real `gh` argv (verified via a fake `gh` script on
  `PATH` that echoes its arguments — proves the real subprocess call
  happens with the correct command, without ever hitting the real
  GitHub API); a missing `gh` CLI returns a clean `[ERROR]`.
- Regression: `make_chat_handlers`' own `github_comment` still works
  correctly with the shared command builder.

## Regression

Targeted sweep (new test file + git_worktree + git_stash hardening):
**28 passed.**

First full-suite run surfaced the self-caught duplicate-CHAT_TOOLS
regression described above (`test_chat_tools_has_no_duplicates` +
`test_day1_tools.py::test_no_duplicate_tool_names` +
`test_day2_tools.py::TestChatToolsIntegrity::test_no_duplicate_tool_names`,
3 failed). Fixed by removing the duplicate `_GITHUB_COMMENT_TOOL`
insertion. Full suite re-run once more after that fix: **5199 passed,
52 skipped, 18 deselected, 0 failed** (up from 5190 before this tool).

## Final verdict

**GREEN FLAG.**
