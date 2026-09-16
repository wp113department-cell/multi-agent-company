# Tool #203 — `summarize_repo` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `summarize_repo_h` inside
`make_chat_handlers()`. Exclusively a `CHAT_TOOLS` entry (membership
count confirmed = 1); grepped all other agent files — none reference
`"summarize_repo"` in their own `allowed_tools`.

This is the exact deferred item logged in tool #100's
(`generate_changelog`) own docstring: *"The sibling tool
`summarize_repo_h`, right next to this one in tools.py, has the
identical unvalidated `repo_path`-override pattern reaching
`os.walk()` — out of scope for this turn, logged in
`tool_enhance_tracking.md` for its own future turn."* This turn closes
that deferred item.

## Problems found

Two real, empirically-verified findings.

1. **`repo_path` is an LLM-controlled field that lets the caller
   redirect the ENTIRE summary at an arbitrary host directory,
   completely outside the intended worktree.** `summarize_repo_h`'s
   original body did `_rp = str(inp.get("repo_path", repo_path))` and
   passed `_rp` directly to `os.walk()` and to a raw `os.path.join()`
   + `open()` for the README excerpt — zero validation. Proved live:
   pointing `repo_path` at an arbitrary host directory outside the
   intended project worktree genuinely disclosed that OTHER
   directory's real file tree, file-extension breakdown, and (when
   present) README content. There is no legitimate use case for
   letting the LLM redirect a repo-summary tool at an unrelated host
   directory — pure scope-escape, exactly the same reasoning already
   applied to `generate_changelog`'s finding #2.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202.**
   `summarize_repo` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: summarize_repo"`.

## Changes made

Extracted into `app/tools/filesystem/summarize_repo.py`
(`SUMMARIZE_REPO_TOOL`, `summarize_repo_handler`), mirroring
`generate_changelog_handler`'s exact precedent (tool #100): the
`repo_path` field from `inp` is **ignored entirely** — the handler
always operates on `root` (the handler factory's own configured
worktree), closing finding #1 structurally rather than trying to
validate an arbitrary-directory override. The schema keeps the
`repo_path` field (documented as ignored, for backward compatibility
with existing callers) rather than removing it, matching
`generate_changelog`'s own schema treatment. A new `chat_agent.py`
`_execute_tool()` dispatch branch delegates to this same shared
handler, closing finding #2. All other behavior (3-level directory
tree, extension breakdown, README excerpt, output formatting)
preserved verbatim.

## Tests

`tests/test_day2_tools.py` checks tool-list membership and handler
callability only — no test ever passed an explicit `repo_path`
override, so ignoring it structurally changes no existing test's
observed behavior; re-run and confirmed passing unchanged.

New file `tests/test_summarize_repo_hardening.py`, 13 tests: schema
check, `CHAT_TOOLS` single-registration check, proof the `repo_path`
override is ignored on all 3 real access paths (`make_chat_handlers()`'s
handler, `chat_agent.py`'s real dispatch, and the shared handler
called directly), proof the dispatch no longer returns "Unknown tool",
and legitimate-usage regression (real repo summary with correct file
count/extension breakdown/README excerpt/directory-tree exclusions).

## Regression

This tool's own new hardening tests (13/13 pass) plus
`tests/test_day2_tools.py` (98 total across both files, 1 pre-existing
skip unrelated to this change). Also ran a broader chat_agent
regression sweep (`test_audit_q_batch10_chat_agent_dispatch.py`,
`test_batch11_chat_agent_bash_sandbox.py`,
`test_batch11_chat_agent_policy_chokepoint.py`,
`test_chat_agent_memory_wiring.py`, `test_chat_tools.py`,
`test_gap16_chat_agent_verification_gate.py`) — **158 passed**, 0
failed.

This turn was also verified via a comprehensive `mypy app/agents/`
sweep (101 files clean), an `importlib`-reload sweep over
`app.agents.chat_agent` and `app.agents.tools` (both clean), a `ruff
check` on all touched files (clean), a `CHAT_TOOLS`
duplicate-registration check (clean), and
`tests/test_new_tools.py` + `tests/test_final_session.py` tool-count
regression tests (61/61 pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (an arbitrary-host-directory
disclosure oracle and a completely non-functional interactive-chat
dispatch) identified and fixed; no functionality lost, legitimate
usage verified end-to-end on both real access paths. Tool-specific and
broader chat_agent regression tests clean. Agent alignment verified:
PASS (`chat_agent.py`'s dispatch and `make_chat_handlers()`'s handler
both now route through the one shared, repo_path-override-ignoring
implementation).
