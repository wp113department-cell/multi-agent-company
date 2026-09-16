# Tool #208 — `xml_validate` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `xml_validate_h` inside
`make_chat_handlers()`. Same shape as sibling tool #175
(`read_notebook`).

## Problems found

Two real, empirically-verified findings.

1. **Worktree-boundary escape — a well-formedness/error-message
   disclosure oracle.** `root / path` was never validated — same class
   already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#146/#154/#158/#166/#169/#170/#171/#174/#175/#202/#203/#204/#206.
   Proved live: an out-of-worktree XML file's well-formedness (and
   parse-error detail, for malformed files) was genuinely disclosed —
   confirming existence and structural shape of an arbitrary host
   file.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#146/#150/#151/#152/#153/#154/#156/#157/#158/#159/#160/#161/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#202/#203/#204/#206.**
   `xml_validate` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: xml_validate"`.

**Investigated and REFUTED, not treated as a finding**: XXE (XML
External Entity) injection via a crafted `<!DOCTYPE>`/`<!ENTITY ...
SYSTEM "file://...">` payload. Proved live against this project's real
`xml.etree.ElementTree.parse()`: a real XXE payload targeting a real
secret file raised `ParseError: undefined entity &xxe;` — CPython's
`ElementTree` (built on `expat`) does not expand external entities by
default. Not a real vulnerability on this real runtime; not fixed
because there was nothing real to fix.

## Changes made

Extracted into `app/tools/filesystem/xml_validate.py`
(`XML_VALIDATE_TOOL`, `xml_validate_handler`): `path` is validated with
`check_path_in_worktree()` before the file is ever parsed, closing
finding #1. A new `chat_agent.py` `_execute_tool()` dispatch branch
delegates to this same shared handler, closing finding #2.

## Tests

`tests/test_audit_q_batch09_large_project_file_tech.py` passes only
in-worktree relative paths — unaffected, re-run and confirmed passing
unchanged.

New file `tests/test_xml_validate_hardening.py`, 12 tests: schema
check, `CHAT_TOOLS` single-registration check, escape-blocked proof on
all 3 real access paths, proof the dispatch no longer returns "Unknown
tool", an XXE regression guard confirming the refuted finding stays
refuted, and legitimate-usage regression (well-formed file, malformed
file with real parse-error detail, missing-file error) verified
through both real access paths.

## Regression

This tool's own new hardening tests (12/12 pass) plus
`tests/test_audit_q_batch09_large_project_file_tech.py` (50 total
across both files, 1 deselected unrelated to this change). Also ran a
broader chat_agent regression sweep
(`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_gap16_chat_agent_verification_gate.py`) — **19 passed**, 0
failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (a worktree-escape disclosure oracle
and a completely non-functional interactive-chat dispatch) identified
and fixed; XXE investigated and empirically refuted rather than
assumed safe or assumed vulnerable. No functionality lost, legitimate
usage verified end-to-end on both real access paths. Tool-specific and
broader chat_agent regression tests clean. Agent alignment verified:
PASS (`chat_agent.py`'s dispatch and `make_chat_handlers()`'s handler
both now route through the one shared, worktree-validated
implementation).
