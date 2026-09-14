# Tool #152 — `github_inspect_repo` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `github_inspect_repo_h` inside
`make_chat_handlers()`.

`owner`, `repo`, and `path` reach a `https://api.github.com/...` URL
this tool builds itself — not a local filesystem path, so the usual
worktree-boundary-escape class doesn't apply in its usual form.

`github_inspect_repo` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see the finding
below.

Existing tests referencing this tool: `tests/
test_audit_q_batch09_large_project_file_tech.py`'s
`TestGithubInspectRepo` (4 tests, 1 marked `slow` for the real network
call), plus an unrelated manifest-metadata assertion in `tests/
test_stage4_tier3_tool_level_retry.py` — confirmed via grep and
re-run.

## Problems found

Checked and CONFIRMED already safe (no fix needed): `owner`/`repo` are
validated against `^[A-Za-z0-9._-]+$`, rejecting `/`, `@`, `:`, and
every other URL-structural character — no host-confusion/SSRF-style
redirection to a different API host is possible — and `path` segments
are validated the same way plus explicitly reject `.`/`..` segments.
Proved live: `owner="evil.com/x#"` and `path="../../etc"` were both
rejected with a clear `[ERROR]`.

One real, empirically-verified finding.

**Advertised but never dispatched on the interactive chat agent, same
class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151.**
`github_inspect_repo` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch (`owner="octocat"`,
`repo="Hello-World"`, a real public GitHub repo) returned `"[ERROR]
Unknown tool: github_inspect_repo"` instead of the real repo metadata
that the canonical `make_chat_handlers()` implementation genuinely
returns for the same input, confirmed live against the real,
unauthenticated GitHub REST API.

## Changes made

New shared `github_inspect_repo_handler()` in
`app/tools/integrations/github_inspect_repo.py`, containing the
unchanged validation and API-call logic. A new `chat_agent.py`
dispatch branch delegates to this shared handler, closing the
finding — `github_inspect_repo` is now genuinely reachable from
interactive chat for the first time. `app/agents/tools.py`'s
`_GITHUB_INSPECT_REPO_TOOL` now aliases the shared
`GITHUB_INSPECT_REPO_TOOL` constant. No external direct-importers of
the old names were found.

## Tests

New file `tests/test_github_inspect_repo_hardening.py`, 9 tests (3
marked `slow`, making a real, unauthenticated network call to the
real GitHub REST API): schema check, duplicate-registration check,
re-confirmation the existing owner/repo/path validation still rejects
injection and path-traversal attempts (including through the new
`chat_agent.py` dispatch), a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression against a real public
repo on both real access paths.

Existing tests (`tests/test_audit_q_batch09_large_project_file_tech.py`'s
`TestGithubInspectRepo`, 4 tests including its own `slow` real-network
test, plus the unrelated manifest-metadata test in `tests/
test_stage4_tier3_tool_level_retry.py`) re-run clean.

## Regression

This tool is tool 4 of the #149-#153 batch. Its own new hardening
tests (9/9 pass) plus the 5 pre-existing tests (5/5 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/integrations/
github_inspect_repo.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("github_inspect_repo") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** The one real finding was proved live and closed; the
tool is now genuinely reachable from interactive chat for the first
time — a strict capability increase, not a narrowing; existing
input-validation confirmed intact; no functionality lost;
tool-specific regression tests clean (14/14 across new + swept
existing tests).
