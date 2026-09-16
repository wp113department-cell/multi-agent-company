# Tool #204 — `template_render` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `template_render_h` inside
`make_chat_handlers()`. Exclusively a `CHAT_TOOLS` entry (membership
count confirmed = 1); grepped all other agent files — none reference
`"template_render"` in their own `allowed_tools`.

## Problems found

Three findings — two real and empirically-verified today, one a real
latent risk verified NOT currently reachable in this deployment
(documented honestly rather than glossed over, per tool_enhance.md's
real-execution rules).

1. **Worktree-boundary escape — a genuine FULL FILE CONTENT disclosure
   oracle, on BOTH real code paths.** `root / str(path)` was built in
   two places (the jinja2-present `try` branch and the jinja2-absent
   `except ImportError` fallback) with zero validation — the same
   class already documented for tools
   #99/#107/#116/#120/#122/#127/#129/#132/#134/#135/#137/#138/#139/#141/#142/#143/#144/#202/#203,
   but WORSE here: with no matching `{{ var }}` placeholders, the
   naive fallback returns the file's content completely unchanged —
   full, verbatim disclosure. Proved live: a real secret string in a
   file outside the worktree was returned byte-for-byte.
2. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203.**
   `template_render` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: template_render"`.
3. **Real Jinja2 Server-Side Template Injection surface — checked
   directly, confirmed NOT currently reachable in this deployment.**
   The `try` branch passed an LLM-controlled template string straight
   into Jinja2's plain, non-sandboxed `Template(...).render(...)` — a
   classic SSTI class (attribute-chain payloads can reach arbitrary
   Python objects in an unsandboxed environment). Verified directly:
   `jinja2` is not installed in this project's venv, not declared in
   `requirements.txt`/`requirements-dev.txt`, and not pulled in
   transitively (confirmed via `pip list` and a real
   `ModuleNotFoundError` on `import jinja2`) — so the `try` branch's
   `import jinja2` always raises `ImportError` in this actual deployed
   environment, and every real call takes the naive-substitution
   fallback instead. Not an active, currently-exploitable finding, but
   hardened as defense in depth anyway (near-zero cost, real severity
   class if jinja2 is ever added to dependencies later).

## Changes made

Extracted into `app/tools/filesystem/template_render.py`
(`TEMPLATE_RENDER_TOOL`, `template_render_handler`): `path` is
validated with `check_path_in_worktree()` before either read, closing
finding #1 on both code paths. A new `chat_agent.py` `_execute_tool()`
dispatch branch delegates to this same shared handler, closing
finding #2. The `try` branch now imports
`jinja2.sandbox.SandboxedEnvironment` in place of the plain `Template`,
closing finding #3 as defense in depth. All other behavior (template
string vs. file path, `vars` injection, naive-substitution fallback
when jinja2 is absent) preserved verbatim.

## Tests

`tests/test_new_tools.py`'s two existing tests
(`test_template_render_string`, `test_template_render_file`) use only
in-worktree relative paths / inline templates — unaffected by the new
worktree-boundary check, re-run and confirmed passing unchanged (47
tests total across both files).

New file `tests/test_template_render_hardening.py`, 15 tests: schema
check, `CHAT_TOOLS` single-registration check, escape-blocked proof on
all 3 real access paths, proof the dispatch no longer returns "Unknown
tool", an explicit confirmation that `jinja2` is genuinely not
installed in this deployment (the premise behind treating finding #3
as currently unreachable), and legitimate-usage regression (inline
template rendering, file-based template rendering, missing-input
error) verified through both real access paths.

## Regression

This tool's own new hardening tests (15/15 pass) plus
`tests/test_new_tools.py` (47 total across both files). Also ran a
broader chat_agent regression sweep
(`test_audit_q_batch10_chat_agent_dispatch.py`,
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
`tests/test_final_session.py` tool-count regression tests (25/25
pass) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** Two real findings (a full-file-content worktree-escape
disclosure oracle and a completely non-functional interactive-chat
dispatch) identified and fixed; a third, real-severity-class but
currently-unreachable SSTI risk hardened as defense in depth. No
functionality lost, legitimate usage verified end-to-end on both real
access paths. Tool-specific and broader chat_agent regression tests
clean. Agent alignment verified: PASS (`chat_agent.py`'s dispatch and
`make_chat_handlers()`'s handler both now route through the one
shared, worktree-validated, sandboxed implementation).
