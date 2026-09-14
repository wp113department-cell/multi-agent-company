# Tool #156 — `inspect_github_repo` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: the module-level `inspect_github_repo`
function in `app/agents/tools.py` (standalone — needs no `repo_path`).
Confirmed via grep that both `make_chat_handlers()` and
`chat_agent.py`'s dispatch call this exact same function object — no
duplication or drift risk here, unlike most tools this initiative.
`chat_agent.py`'s dispatch was already correctly wired before this
turn — no missing-dispatch finding either.

Existing tests referencing this tool: `tests/
test_audit_q_batch10_deployment_external_git_docs.py`'s
`TestInspectGithubRepo` (9 tests) plus 2 registration smoke tests, and
`tests/test_audit_q_batch10_chat_agent_dispatch.py`'s
`test_inspect_github_repo_reachable_in_chat_mode` (1 test) — 12 total,
confirmed via grep and re-run.

## Problems found

None. Audited thoroughly, live-tested, and confirmed already safe on
every dimension this initiative checks:

- `owner`/`repo` are validated against `^[A-Za-z0-9._-]+$` — the same
  regex already proven correct for sibling tool #152's
  `github_inspect_repo`.
- `path` (for `list_files`/`read_file`) rejects any segment equal to
  literally `".."`. Proved live against the REAL GitHub API: a plain
  `../user` traversal is rejected by this check before any request is
  made; a URL-encoded `..%2f..%2fuser` and a double-encoded
  `..%252f..%252fuser` were both passed through to the real `gh api`
  call, and the real GitHub API server itself returned a plain 404
  for both — GitHub's contents API does not normalize percent-encoded
  traversal into actual path segments, so no bypass exists.
- No shell-injection risk: `gh api <endpoint>` runs via list-args
  `subprocess.run()`, never `shell=True`, and the fixed
  `repos/{owner}/{repo}/contents/` prefix (built only from the two
  already-validated identifiers) means no input can redirect the call
  to an unrelated top-level API endpoint.
- Already correctly dispatched by `chat_agent.py`.

## Changes made

Modularization only, matching the identical "no bug found, still
extracted" precedent from tool #147's `generate_patch`. New shared
`inspect_github_repo_handler()` in
`app/tools/integrations/inspect_github_repo.py`, containing the
unchanged validation and API-call logic. `app/agents/tools.py`'s
module-level `inspect_github_repo` function is now a thin one-line
delegating wrapper, kept under its original name for backward
compatibility (existing tests import it directly from
`app.agents.tools`). `chat_agent.py`'s dispatch now imports and calls
the shared handler directly instead of the old module-level function,
matching the established pattern for every other tool this
initiative. `app/agents/tools.py`'s `_INSPECT_GITHUB_REPO_TOOL` now
aliases the shared `INSPECT_GITHUB_REPO_TOOL` constant.

## Tests

New file `tests/test_inspect_github_repo_hardening.py`, 9 tests:
schema check, duplicate-registration check, a proof the old
module-level wrapper still works (backward compatibility), a
re-confirmation of the path-traversal-encoding-bypass check against
the real GitHub API (plain, URL-encoded, double-encoded), and
legitimate-usage regression across all 3 real access paths.

Existing tests (12 total across 2 files) re-run clean, unaffected by
the modularization.

## Regression

This tool is tool 3 of the #154-#158 batch. Its own new hardening
tests (9/9 pass) plus the 12 pre-existing tests (12/12 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/integrations/
inspect_github_repo.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("inspect_github_repo") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** No real bug existed on this tool; genuinely clean
audit across every dimension checked this initiative, confirmed live
against the real GitHub API; no functionality lost; tool-specific
regression tests clean (21/21 across new + swept existing tests).
