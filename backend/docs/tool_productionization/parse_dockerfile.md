# Tool #171 — `parse_dockerfile` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `parse_dockerfile_h` inside
`make_chat_handlers()`.

`parse_dockerfile` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/
test_audit_q_batch09_large_project_file_tech.py`'s
`TestParseDockerfile` (3 tests) — confirmed via grep and re-run.

Same finding shape as sibling tool #170 (`parse_docker_compose`),
fixed the same day.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
STRUCTURED FILE CONTENT DISCLOSURE oracle.** `parse_dockerfile_h`
built `root / path` without ever validating it stayed inside the
worktree — the same `pathlib`-silently-discards-`root`-for-an-
absolute-right-operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170.
Proved live: `parse_dockerfile({"path": "/tmp/<outside Dockerfile>"})`
genuinely disclosed a real base image reference from a private
registry (`internal-registry.example.com/secret-base:latest`), an
exposed port (`9999`), and a build instruction
(`RUN echo SECRET_BUILD_STEP`) from a Dockerfile entirely outside the
intended worktree.

**Finding #2 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170.**
`parse_dockerfile` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: parse_dockerfile"`.

## Changes made

New shared `parse_dockerfile_handler()` in `app/tools/filesystem/
parse_dockerfile.py`: `path` is now validated with
`check_path_in_worktree()` (checked for both relative traversal and
absolute-path escapes) before the file is ever read, closing finding
#1. A new `chat_agent.py` dispatch branch delegates to this same
shared handler, closing finding #2 — `parse_dockerfile` is now
genuinely reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_PARSE_DOCKERFILE_TOOL` now aliases the
shared `PARSE_DOCKERFILE_TOOL` constant. No external direct-importers
of the old names were found.

## Tests

New file `tests/test_parse_dockerfile_hardening.py`, 13 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(absolute and relative traversal, across all 3 real access paths)
with an assertion the outside Dockerfile's real base image/build
instructions never leak into the result, a proof the new dispatch no
longer returns "Unknown tool", and legitimate-usage regression (real
Dockerfile parsing including the default-path behavior, missing-file
error, empty file, and multi-stage line-continuation handling).

Existing tests (`tests/test_audit_q_batch09_large_project_file_tech.py`'s
`TestParseDockerfile`, 3 tests) re-run clean.

## Regression

This tool is tool 3 of the #169-#173 batch. Its own new hardening
tests (13/13 pass) plus the 3 pre-existing tests (3/3 pass) are the
per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
parse_dockerfile.py` sweep (102 files clean), an `importlib`-reload
sweep over all `app.agents.*` modules (all clean), a `ruff check` on
all touched files (clean), a compile()-based source escape-sequence
check on the new module (clean), and a
`CHAT_TOOLS.count("parse_dockerfile") == 1` check (clean) — BEFORE
claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool
is now genuinely reachable from interactive chat for the first time —
a strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (16/16 across new + swept
existing tests).
