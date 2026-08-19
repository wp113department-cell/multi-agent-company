# Tool #45 — `github_create_issue` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Only one real implementation existed: `make_chat_handlers()`'s own
`github_create_issue_h`. **`chat_agent.py` had no dispatch for it at
all**, despite the tool already being advertised via `CHAT_TOOLS`
("Day 3G — External integrations" section) — the exact same
"advertised but never dispatched" bug class as tools #4/#6/#22/#25/#33,
and the same class tool #44's `github_comment` turned out to actually
be (after a self-caught correction there). This time, `CHAT_TOOLS`
membership was verified directly by checking the constant's real
position in the list and confirming a clean count via
`CHAT_TOOLS.count("github_create_issue") == 1` before and after the
fix — not repeating tool #44's earlier mistake.

## Problems found

The handler's own command-building logic was already safe: `title`/
`body` are distinct argv items (list-args, no `shell=True`), `labels`
is iterated with each value appended as its own `--label <value>` pair
— no injection surface. The real gap was purely reachability: a
fully-implemented, already-safe handler that no live interactive agent
could ever invoke.

## Changes made

- **`app/tools/git/github_create_issue.py`** (new):
  `GITHUB_CREATE_ISSUE_TOOL` (schema, unchanged) and
  `github_create_issue_command(title, body, labels)` — the shared,
  already-safe argv builder, now used by both implementations instead
  of being duplicated inline.
- **`app/agents/tools.py`**: `github_create_issue_h` now calls the
  shared builder.
- **`app/agents/chat_agent.py`**: **new** real dispatch branch (this
  tool had none before), placed right after tool #44's
  `github_comment` dispatch. Since creating a GitHub issue is a real,
  publicly-visible external write — the same risk category as
  `create_pr`/`github_comment` — the new dispatch gates the actual
  creation behind a real `self._confirm()` dialog showing the exact
  `gh` command, title, body, and labels, mirroring those tools'
  established confirmation pattern exactly.

## Tests (real, not mocked at the mechanism level for the parts that
matter — a fake `gh` script on `PATH` so no real, live GitHub issue is
ever created during testing, but the real dispatch/confirmation/
subprocess-invocation path is genuinely exercised)

`tests/test_github_create_issue_hardening.py` (new, 8 tests):

- Schema shape check, and confirms `github_create_issue` appears in
  `CHAT_TOOLS` exactly once (explicit duplicate-prevention check, given
  tool #44's near-miss).
- Pure command-builder tests: no-labels and with-labels argv shapes.
- **The reachability fix, verified live**: a declined confirmation
  creates nothing (`[DENIED]`); an approved confirmation genuinely
  invokes the real `gh` argv (verified via a fake `gh` script on
  `PATH`); a missing `gh` CLI returns a clean `[ERROR]`.
- Regression: `make_chat_handlers`' own `github_create_issue` still
  works correctly with the shared command builder.

## Regression

Targeted sweep (new test file + github_comment hardening +
`test_chat_tools.py`/`test_day1_tools.py`/`test_day2_tools.py` — the
explicit duplicate-detection tests from tool #44's correction): **370
passed, 1 skipped.** Full suite re-run after this pass: **5207 passed,
52 skipped, 18 deselected, 0 failed** (up from 5199 before this tool).

## Final verdict

**GREEN FLAG.**
