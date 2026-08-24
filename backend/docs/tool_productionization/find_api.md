# Tool #89 — `find_api` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Four real implementations:

1. `sec_find_api` (`make_security_reviewer_handlers`) — `.py` only, no
   directory exclusions.
2. `ad_find_api` (`make_api_docs_agent_handlers`) — same shape as #1.
3. `find_api_h` (inside `make_chat_handlers()`, ~35 one-shot agents) —
   `.py` + `.ts`, excludes `node_modules`/`.venv`/`__pycache__`.
4. `app/agents/chat_agent.py`'s separate interactive dispatch — same
   scope as #3, built on a shell string with `name` passed through
   `shlex.quote()`.

Per `tool_inventory.json`, 5 agents declare `find_api` in
`allowed_tools`. `CHAT_TOOLS.count("find_api") == 1` verified. 2
existing test files reference this tool, both exercising the real
handler — re-run and confirmed passing unchanged (4 tests).

## Problems found

**Finding — the same "an external program's own flag parser accepts
an LLM-controlled positional field" class first found in tool #59
(`run_make`)/tool #69 (`search_code`), on ALL FOUR real
implementations.** `name` was placed as a bare positional argv element
with no `--` separator in every one. Critically, `chat_agent.py`'s
`shlex.quote()` does NOT protect against this — quoting only stops the
SHELL from misinterpreting the string; the shell still hands grep the
exact same single argv token, and grep's own argument parser still
treats a leading `-` as one of its own options. Proved live, first at
the raw `grep` CLI level, then through all four real dispatch paths:

```python
await agent._execute_tool("find_api", {"name": "-l"})
```

silently returned `"(no output)"` — grep's real `-l` flag (list
matching filenames only) consumed the value instead of searching for
the literal string `"-l"`, producing a misleadingly-confident "no
results" answer rather than either a genuine match or an honest "no
matches" for the right reason — the same correctness-bug shape as
tool #69's `search_code` finding. No maximally severe grep flag (e.g.
one with an arbitrary-file-write side effect, like tool #80's `git
show --output`) was found reachable through a bare `name` value alone,
but per this initiative's consistent policy, flag-shaped values are
rejected outright regardless of the specific worst-case flag found for
this tool.

**A secondary, non-security finding.** Implementations #1/#2 search
only `.py` files with no directory exclusions; #3/#4 also search `.ts`
and exclude `node_modules`/`.venv`/`__pycache__` — a real
functionality divergence, with #3/#4's behavior being strictly more
complete/correct (proved live: a real file under `node_modules/` was
returned by #1/#2 but correctly excluded by #3/#4 before the fix).

## Changes made

Extracted `validate_find_api_name()` + `find_api_handler()` in
`app/tools/filesystem/find_api.py`, adopted by all four real call
sites: the validator rejects any `name` starting with `-` outright,
matching the `search_code`/`git_show`/`git_blame` precedent, closing
the flag-injection finding; the shared handler adopts the more
complete search scope (`.py` + `.ts`, three directory exclusions) for
all four real call sites, closing the secondary finding.

`app/agents/tools.py`'s `_FIND_API_TOOL` now aliases the shared
`FIND_API_TOOL` constant (no external direct-importers found, verified
before wiring — the simpler `as`-rename import was safe to use here).

## Tests

New file `tests/test_find_api_hardening.py`, 17 tests, all real (no
mocking) — schema check, `validate_find_api_name()` direct unit
checks, the flag-shaped-`name` rejection verified closed on all four
real dispatch paths (parametrized where applicable), the
`node_modules` exclusion fix verified closed on the two previously-
incomplete implementations, and legitimate-usage regression (named
search, empty-name "all routes" search, clean no-match message) across
all four real access paths. The two existing test files
(`test_day1_tools.py::TestFindApi`, `test_day2_agents.py`) re-run and
confirmed passing unchanged.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change. Per the standing lesson from tool #88, this turn was
also verified via a comprehensive `mypy app/agents/` sweep (98 files
clean) and an `importlib.import_module()` sweep of every file in
`app/agents/` (all clean) BEFORE claiming GREEN_FLAG, not just after
the full-suite run happened to catch anything.

## Final verdict

**GREEN FLAG.** The real flag-injection finding proved live and closed
across all four real implementations; the functionality divergence
unified onto the more complete, more correct behavior; no
functionality lost; full regression clean; the tool #88 lesson applied
proactively this turn rather than reactively.
