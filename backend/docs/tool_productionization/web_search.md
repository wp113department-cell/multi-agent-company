# Tool #88 — `web_search` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

A single module-level `web_search()` function — NOT duplicated;
`make_research_handlers()` and `make_chat_handlers()` both wire the
exact same function object. Confirmed NOT in `CHAT_TOOLS` —
intentional, the interactive chat session never gets unrestricted live
web search; `chat_agent.py` correctly has no dispatch branch for it.

Per `tool_inventory.json`, 7 agents declare `web_search` in
`allowed_tools`. `RESEARCH_TOOLS.count("web_search") == 1` verified. 7
existing test files reference this tool — all wiring/contract/
manifest/prompt-injection-defense checks rather than direct calls to
the real handler (a live network search isn't something those earlier
tests attempt) — all re-run and confirmed passing unchanged (194
tests).

## Problems found

**No security vulnerability.** `query` is a plain search string passed
to the `duckduckgo_search` library's `DDGS().text()` call — no
subprocess, no shell, no file-path handling, so none of this
initiative's established finding classes (flag-collision, worktree
escape, shell injection) apply. `DDGS()`'s own default `timeout=10`
(verified via `inspect.signature`) already bounds the outbound HTTP
call — no unbounded-timeout risk, unlike tool #86's `fetch_url` before
its fix. `max_results=5` is a fixed literal, not LLM-controlled, so no
resource-exhaustion angle via requesting an enormous result count.
Already wrapped in a broad `try/except Exception`, so no
uncaught-exception class either. Real search-result CONTENT already
gets wrapped as untrusted data and scanned for prompt-injection markers
by a separate, pre-existing defense layer
(`test_phase63_prompt_injection_defense.py`) — unrelated to this
tool's own code, left untouched.

**Out-of-scope observation, documented but not acted on.** The
installed `duckduckgo_search` PyPI package emits a real
`RuntimeWarning` at call time — it has been renamed to `ddgs`
upstream. Verified live: every real call in this audit triggered the
warning. This is a genuine future-maintenance risk (the old package
name may stop receiving updates), but changing a project dependency is
outside this security-hardening pass's scope and risks its own
regression; logged here for a future, deliberate dependency-upgrade
decision.

## Changes made

Extracted verbatim (no behavior change) into
`app/tools/integrations/web_search.py`, purely for modularization —
matches this initiative's mandatory per-tool modularization rule even
when no vulnerability was found (same precedent as tool #85's
`submit_docs`). `app/agents/tools.py`'s `_WEB_SEARCH_TOOL` now aliases
the shared `WEB_SEARCH_TOOL` constant via a plain module-level
assignment (not a renaming `as` import) — applied proactively, since 5
external agent files (`spike_agent.py`, `mcp_developer_agent.py`,
`agentic_ai_architect.py`, `prompt_engineer_agent.py`,
`tech_advisor_agent.py`) import this name directly, the same mypy
`--strict` "not explicitly exported" class caught and fixed in tool
#86.

**Real regression caught by the full-suite run, not shipped
silently.** Removing the old module-level `web_search()` function
broke `app/agents/agent_performance_reviewer.py`, which imported it
directly by name (`from app.agents.tools import (..., web_search)`) —
missed by an initial grep because the import spans multiple lines.
The first full-suite run genuinely failed 21 tests, all tracing to one
root cause (`ImportError: cannot import name 'web_search'`). Fixed by
updating that file's import and its one usage site to
`web_search_handler`, then verified via three independent methods
before re-trusting the fix: (1) a direct
`importlib.import_module()` sweep of every file in `app/agents/`
(not just grep), (2) a **comprehensive** `mypy app/agents/` run
(previously this initiative had only run mypy against the single new
module in isolation, which doesn't follow imports to a file's own
external CONSUMERS) — this surfaced `web_search_handler` itself
needing the `X as X` self-alias idiom (a second, narrower instance of
tool #86's export-visibility class, this time for the handler function
rather than the schema constant), AND three more PRE-EXISTING
instances from even earlier turns: `_SUBMIT_DOCS_TOOL` (tool #85),
`_GIT_TAG_TOOL` (tool #22), `_SEMVER_BUMP_TOOL` (tool #25) — all fixed
together here rather than left for a future turn to rediscover one at
a time, and (3) a full `mypy app/` run (323 files, clean) plus a
complete full-suite re-run (see Regression below).

## Tests

New file `tests/test_web_search_hardening.py`, 10 tests — schema
check, confirmation this tool is intentionally absent from
`CHAT_TOOLS`, empty/whitespace/missing-query rejection, graceful
handling of a simulated library failure (`monkeypatch`, no real
network call needed for that path), output-truncation verification,
and legitimate-usage regression via a real, live DuckDuckGo search on
both real access paths (`make_research_handlers()`,
`make_chat_handlers()`) — matching this test suite's own established
pattern of hitting real external services (tool #86's
`test_fetch_url_hardening.py`) rather than mocking the network
entirely.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed. **First run: 21 failed** (the `agent_performance_
reviewer.py` import regression above — all 21 traced to that one root
cause, confirmed by reading the failures rather than assuming they
were unrelated flakiness). Fixed, re-verified via the three methods
above, then the full suite was **re-run from scratch** (not just the
previously-failing subset) — clean.

## Final verdict

**GREEN FLAG.** No vulnerability found by a real audit (not assumed
clean) — the library's own default timeout, the fixed result cap, and
the existing broad exception handling were each individually checked,
not just read and trusted; a real dependency-deprecation risk was
found and documented rather than silently ignored or fixed out of
scope. A real regression was introduced by this turn's own refactor,
caught by the full-suite run (not shipped), root-caused precisely, and
fixed together with three more pre-existing instances of the same
underlying class from earlier turns. No functionality lost; full
regression clean on re-run.
