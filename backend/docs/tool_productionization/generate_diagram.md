# Tool #146 — `generate_diagram` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `generate_diagram_h` (plus its private
helpers `_real_class_diagram` / `_real_call_flowchart`) inside
`make_chat_handlers()`.

`generate_diagram` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had zero dispatch branch for it — see finding #2.

Existing tests referencing this tool: `tests/test_new_tools.py` (2),
`tests/test_audit_q_batch14_extensibility_enterprise.py`'s
`TestRealDiagramGeneration` (4) — all use relative in-worktree paths,
confirmed via grep and re-run.

## Problems found

Two real, empirically-verified findings.

**Finding #1 — a worktree-boundary escape that is a genuine
CLASS/METHOD/FUNCTION-NAME disclosure oracle.** Both
`_real_class_diagram` and `_real_call_flowchart` built `root /
file_path` without ever validating it stayed inside the worktree —
the same `pathlib`-silently-discards-`root`-for-an-absolute-right-
operand class already documented for tools
#99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144
this initiative. Proved live: `generate_diagram({"description": "x",
"kind": "classDiagram", "path": "/tmp/<outside file>"})` genuinely
disclosed a real class's name AND its method name from a file entirely
outside the intended worktree; `kind="flowchart"` against the same
outside file likewise disclosed real function names and call edges —
a real structure-disclosure primitive, even though it is not full raw
file content.

**Finding #2 — advertised but never dispatched on the interactive chat
agent, same class as tools
#100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144.**
`generate_diagram` is in `CHAT_TOOLS` and registered in
`make_chat_handlers()`'s handlers dict, but `chat_agent.py`'s
`_execute_tool()` had no dispatch branch — every real interactive-chat
call fell through to `"[ERROR] Unknown tool: generate_diagram"`.

## Changes made

New shared `generate_diagram_handler()` in
`app/tools/filesystem/generate_diagram.py`: when `path` is given, it
is now validated via `check_path_in_worktree()` before either AST
helper ever touches the filesystem, closing finding #1 — an
out-of-worktree path now returns `[POLICY DENIED] ...` instead of a
real diagram derived from outside code. A new `chat_agent.py` dispatch
branch delegates to this same shared handler, closing finding #2 —
`generate_diagram` is now genuinely reachable from interactive chat for
the first time. When no `path` is given (or the derivation legitimately
finds nothing), behavior is unchanged: the existing labeled starter
template is returned.

`app/agents/tools.py`'s `_GENERATE_DIAGRAM_TOOL` now aliases the shared
`GENERATE_DIAGRAM_TOOL` constant. No external direct-importers of the
old names were found.

## Tests

New file `tests/test_generate_diagram_hardening.py`, 11 tests: schema
check, duplicate-registration check, worktree-escape-blocked proof
(across `make_chat_handlers`, the new `chat_agent.py` dispatch, and a
direct handler call, for both `classDiagram` and `flowchart` modes)
with an assertion the outside file's class/method/function names never
leak into the result, a proof the new dispatch no longer returns
"Unknown tool", and legitimate-usage regression (real class-hierarchy
diagram, real call-edge flowchart via the chat dispatch, no-path
template fallback, no-classes-found fallback).

Existing tests (`tests/test_new_tools.py`'s 2 + `tests/
test_audit_q_batch14_extensibility_enterprise.py`'s
`TestRealDiagramGeneration`'s 4 = 6 tests) re-run clean — all use
relative in-worktree paths, unaffected by the fix.

## Regression

This tool is tool 3 of the #144-#148 batch. Its own new hardening tests
(11/11 pass) plus the 6 pre-existing tests (6/6 pass) are the per-tool
verification gate; the full suite runs once the batch completes, per
`feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
generate_diagram.py` sweep (102 files clean), an
`importlib.import_module()` sweep over all `app/agents/` modules (all
clean), a `ruff check` on all touched files (clean), a
`python -W error` docstring escape-sequence check on the new module
(clean), and a `CHAT_TOOLS.count("generate_diagram") == 1` check
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Both real findings proved live and closed; the tool is
now genuinely reachable from interactive chat for the first time — a
strict capability increase, not a narrowing; no functionality lost;
tool-specific regression tests clean (17/17 across new + swept
existing tests).
