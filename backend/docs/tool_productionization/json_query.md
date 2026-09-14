# Tool #158 — `json_query` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `json_query_h` inside `make_chat_handlers()`.

`json_query` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #3.

Zero existing tests referenced this tool — confirmed via grep, no
sweep needed.

## Problems found

Three real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
ARBITRARY FILE CONTENT DISCLOSURE oracle, the most severe class this
initiative tracks (same severity class as tools #80/#100/#112).**
`json_query_h` built `root / path` without ever validating it stayed
inside the worktree. Proved live: `json_query({"path": "/tmp/<outside
file>", "query": "."})` genuinely returned the REAL, FULL, raw JSON
content of a file entirely outside the intended worktree — not just a
name, hash, or metadata, but the actual data (in the proof, a real
secret/API-key-shaped value).

**Finding #2 — a flag-collision bug on `query`, same class as tools
#5/#32/#148/#149.** `["jq", query, str(fpath)]` never validated that
`query` isn't itself a jq CLI flag. Proved live: `query="-n"` caused
jq to genuinely misinterpret its own arguments — `-n` was consumed as
jq's "null input" flag, and the real file path (intended as the file
to query) was then fed to jq as the FILTER EXPRESSION instead,
producing a jq syntax error. Closed defensively before any more
specific jq flag (e.g. `-f`, "read the filter FROM a file") could be
explored for a worse effect.

**Finding #3 — advertised but never dispatched on the interactive
chat agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157.**
`json_query` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch at all. Proved live: a real
call through the real `chat_agent.py` dispatch returned `"[ERROR]
Unknown tool: json_query"`.

## Changes made

New shared `json_query_handler()` in `app/tools/filesystem/json_query.py`:
`path` is now validated with `check_path_in_worktree()` before the
file is ever read, closing finding #1. `query` is rejected outright
with a clear `[ERROR]` whenever it starts with `-`, closing finding
#2. A new `chat_agent.py` dispatch branch delegates to this same
shared handler, closing finding #3 — `json_query` is now genuinely
reachable from interactive chat for the first time.

`app/agents/tools.py`'s `_JSON_QUERY_TOOL` now aliases the shared
`JSON_QUERY_TOOL` constant. No external direct-importers of the old
names were found.

## Tests

New file `tests/test_json_query_hardening.py`, 13 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(absolute and relative traversal, across all 3 real access paths)
with an assertion the outside file's secret content never leaks into
the result, flag-collision-blocked proof (`-n`, `-f`), a proof the
new dispatch no longer returns "Unknown tool", and legitimate-usage
regression (real jq queries against real in-worktree JSON, missing-
file error).

Zero existing tests referenced this tool — confirmed, no sweep
needed.

## Regression

This tool is tool 5 of the #154-#158 batch — the batch is now
complete. Its own new hardening tests (13/13 pass) are the per-tool
verification gate; the full batch suite runs next, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
json_query.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("json_query") == 1` check (clean) —
BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings proved live and closed —
including the most severe finding class this initiative tracks
(arbitrary file content disclosure); the tool is now genuinely
reachable from interactive chat for the first time — a strict
capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (13/13).
