# Fleet Day 7 Test Report — VerificationConfig Hardening + Day 0–6 Gap-Closure Audit
Date: 2026-07-20

## Why this report covers more than "Day 7"

`PROJECT.md` and `docs/PROJECT_CONTROL_CENTER.md` had not been updated since Day 5A
(2026-07-17), despite Day 5B, Day 6, the v2.0 role-prompt overhaul, and an undocumented
commit (`dc27e1e`, "enhanced") all landing since. Before touching Day 7, this session
re-verified actual code state against the plan — via a real `pytest`/`mypy` run and a
mechanical audit of all 68 agents — rather than trusting the stale docs. Real gaps were
found and fixed (user-approved before any implementation began). Day 7 was then completed
on top of a genuinely clean baseline.

## Commands run (real output, not assumed)

```bash
cd backend && source .venv/bin/activate
python -m pytest tests/ -q -p no:cacheprovider
python -m mypy app/ --strict
```

## Before this session (ground truth, not the stale docs)

```
6 failed, 2261 passed, 55 skipped, 4 deselected, 3 warnings in 80.16s
mypy app/ --strict → 47 errors across 13 files
```
Plus: full-suite runs intermittently **hung indefinitely** (confirmed via a bounded/verbose
repro — root-caused below), which the stale docs had no record of.

## Gaps found and fixed (see PROJECT.md 2026-07-20 session log for full detail)

1. `chat_agent` silently skipped in Day 5B (commit did 8/9 planned agents) — no
   `AGENT_CONTRACT`/`_register()`/`VerificationConfig`, missing from `capability_registry`
   (66/68). **Fixed**: added all three; now 67/67 real agents registered.
2. `groq_adapter` had zero registry entry (plan requires at least one). **Fixed**: added a
   lightweight `agent_registry` registration (no `AGENT_CONTRACT` — it's infra, not a task
   agent, per the plan's own note).
3. Undocumented commit `dc27e1e` added a Groq-bypass block in `run_agent_graph()` that broke
   the Day 0 Gap-7 Sleep-wiring exit criterion (2 tests failing) **and**, more seriously, was
   root cause of the suite hangs: `tests/conftest.py` never overrode `USE_GROQ`, so the whole
   unit suite silently inherited `USE_GROQ=true` from `.env` and started making real,
   unmocked network calls to Groq for every `run_agent_graph()` call. **Fixed**: (a) narrowed
   the bypass's fallback to `FileNotFoundError` only — every other exception still raises
   exactly as before, so it can't mask a real error or hang on a fallback network call; (b)
   forced `USE_GROQ=false` in `conftest.py` for the general suite (the dedicated Groq
   integration test already sets/unsets it around its own fixture, unaffected).
4. Real-LLM Groq tests (`test_day0_groq_integration.py`) 429 under full-suite load on the
   free tier. **Fixed**: marked `pytestmark = pytest.mark.slow`, excluded by `pytest.ini`'s
   existing `-m "not slow"` default (same convention already used elsewhere). Run explicitly:
   `pytest tests/test_day0_groq_integration.py -v -m slow`. **Pending Anthropic key**, per
   user instruction — see memory `pending_anthropic_tests`.
5. `memory_hook_node`'s repo-context injection (Fleet OS capability #15, Architecture
   Awareness) has been silently broken since it was written — called
   `scanner.build_repo_index`, which doesn't exist (real function: `index_repository`),
   swallowed by a broad `except Exception`. **Fixed** the function name.
6. Duplicate capability tags (violates CLAUDE.md rule #6): `business_analyst` /
   `user_story_generator` both claimed `user_story_generation`; `changelog_agent` /
   `release_notes_agent` both claimed `version_documentation`. **Fixed** — renamed the
   less-central owner's tag in each pair.
7. Test-order pollution: `TestFleetManagerSelection` depended on `coder`/`backend_dev`/
   `frontend_dev` being `SLEEP` in the process-wide `agent_registry` singleton; another test
   elsewhere left one in a non-available state. **Fixed** with an autouse `recover()` fixture.
8. Real bug (not flakiness): `test_day1_agent_flags.py` called
   `importlib.reload(app.agents.reviewer)` inside a test, creating a **new** `ReviewResult`
   class object; `test_session3_migration.py` (collected later) had imported the **old**
   class reference at module-load time, so `isinstance(result, ReviewResult)` failed
   depending on run order. **Fixed** — removed the 3 superfluous `importlib.reload()` calls
   (reviewer/devops/docs); they served no purpose since the modules were already imported.
9. `chat_agent.py`'s `run_background`/`read_output` tools imported
   `app.agents.tools._BACKGROUND_PROCESSES`, which was intentionally removed and made
   per-session inside `make_chat_handlers()` — `ChatAgent` was never updated, so both tools
   would `ImportError` at runtime for real chat users. **Fixed** with a per-instance
   `self._background_processes` dict (pre-existing bug, unrelated to the fleet plan, fixed
   opportunistically while already in this file).
10. mypy `--strict`: 47 → 34 errors. Fixed 5 unused `type: ignore`s, a missing SSE-generator
    return type, 4 `no-any-return`s in Day 1 agents, and the `_BACKGROUND_PROCESSES`
    attr-errors. Remaining 34 are pre-existing debt unrelated to fleet work (18 in
    `browser_driver.py` from 2026-07-16, 7 known LangGraph `StateGraph` typing-stub
    limitations already flagged in this file's own Open Issues, rest scattered/minor).

## After fixes — ground truth

```
pytest tests/ -q -p no:cacheprovider
→ 2254 passed, 0 failed, 55 skipped, 17 deselected, 3 warnings in 41.77s

mypy app/ --strict
→ 34 errors, all pre-existing / unrelated to fleet work, 0 new
```

## Day 7 — VerificationConfig Hardening: success criteria met

Plan's stated success criterion: **`verify_agent_contract()` returns 0 violations for all
agents; tests pass.** Checked against the *real* `verify_agent_contract()` in
`app/fleet/tool_manifest.py` (not the plan document's illustrative pseudocode snippet, which
uses a placeholder tool name — `execute_tests` — that doesn't match the codebase's actual
`run_tests`/`bash` convention; confirmed by cross-checking against PROJECT.md's prior "0
issues" audit history for Days 0–4, which used the real function).

- **67/67 real agents** have non-empty, real `set_by`/`enforce_in_result` in their
  `VerificationConfig` (`chat_agent` was the only gap — closed this session).
- **`executive` and `manager`** are the only agents with no `VerificationConfig` — both
  legitimate and unchanged: `executive` calls zero tools (pure LLM), `manager` is a pure
  orchestrator that never calls `run_agent_graph`. Both have full `AGENT_CONTRACT` +
  `_register()`.
- **0 dead `enforce_in_result` keys** — verified no agent enforces a verification key that no
  tool in its own `set_by` ever sets (checked all 67 programmatically).
- **0 duplicate capability tags** fleet-wide (2 found, fixed — see gap #6 above).
- **0 `verify_agent_contract()` violations** against the real implementation.
- ~22 "read-only auditor" agents (debugger_agent, code_quality_agent, test_coverage_agent,
  dependency_security_agent, etc.) deliberately share a minimal `read_file→read` /
  `enforce_in_result={"read":"read"}` pattern. Verified this is intentional and uniform —
  `backend/gridiron_production_prompts_v2/UPGRADE_REPORT.md` explicitly labels these agents
  "read-only auditor" as a category, not a per-agent oversight. Left as-is: forcing a
  stronger fake signal onto agents with no tool to actually produce it would fight the
  established design rather than fix a real gap.

## Verdict

✅ **GREEN FLAG — DAY 7 COMPLETE**: 2254 tests pass, 0 failed. All Day 0–6 gaps found during
this audit are closed. `verify_agent_contract()` returns 0 violations across all 67 real
agents. Ready for Day 8.
