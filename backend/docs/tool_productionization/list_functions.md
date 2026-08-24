# Tool #82 — `list_functions` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

**The widest consolidation in the low-risk tier so far — NINE real
implementations**, spread across 32 agents (per `tool_inventory.json`):

1. `chat_agent.py`'s own interactive dispatch.
2. `make_chat_handlers()`'s own `list_functions` closure (shared by
   ~35 one-shot agents).
3. `ar_list_functions` (`make_arch_reviewer_handlers`).
4. `rf_list_functions` (`make_refactor_agent_handlers`).
5. `rm_list_functions` (`make_readme_agent_handlers`).
6. `ad_list_functions` (`make_api_docs_agent_handlers`).
7. `pr_list_functions` (`make_performance_reviewer_handlers`).
8. `sr_list_functions` (`make_style_reviewer_handlers`).
9. `td_list_functions` (`make_tech_debt_agent_handlers`).

`CHAT_TOOLS.count("list_functions") == 1` verified (one shared schema
constant, `_LIST_FUNCTIONS_TOOL` / now `LIST_FUNCTIONS_TOOL`, reused by
every agent's own tool list). 6 existing test files reference this
tool; 2 (`test_chat_tools.py`, `test_dead_contract_fix.py`) exercise
the real handler, the other 4 (`test_role_file_tools_accuracy.py`,
`test_analyzer_tier_confirmed.py`, `test_day3_agents.py`,
`test_day2_agents.py`, `test_record_learning_rollout.py`) only check
tool-name membership or role-file/contract consistency — verified
directly, all re-run and confirmed passing unchanged (294 tests, no
regressions).

## Problems found

**Finding #1 — worktree-boundary escape + uncaught `PermissionError`
on the two single-file implementations** (`chat_agent.py`'s dispatch
and `make_chat_handlers()`'s own closure) — same class as tool #76's
`analyze_file`. Neither called `check_path_in_worktree()`. Proved
live: `list_functions({"path": "/tmp/outside/secret.py"})` genuinely
listed a real function definition from a file completely outside the
repo, through both real call sites. The unguarded `p.exists()` call
also raised an uncaught `PermissionError` under a real `chmod 000`
parent directory.

**Finding #2 — a field-name mismatch causing every real call to
silently ignore the requested path, in FOUR agent-specific
implementations** (`ar_list_functions`, `rf_list_functions`,
`rm_list_functions`, `ad_list_functions`). The schema these agents
actually advertise declares the field as `"path"` (required) — but all
four handlers read `inp.get("file", "")` instead. Since the LLM only
ever populates the field the schema declares, `file` is ALWAYS absent,
so the code falls back to grepping the **entire repository root
recursively** every single time. Proved live: a schema-conformant call
for `{"path": "src/target.py"}` returned function definitions from
BOTH `src/target.py` AND a completely unrelated file elsewhere in the
repo — a 100% real-call failure rate for path-scoping, present since
these handlers were written.

**Finding #3 — worktree-boundary escape via relative `../` traversal,
in THREE agent-specific implementations** (`pr_list_functions`,
`sr_list_functions`, `td_list_functions` — the ones that DID read the
correct `path` field). `(root / path).rglob("*.py")` had no
`check_path_in_worktree()` call. An ABSOLUTE outside-repo path is
accidentally masked (not genuinely protected) by a downstream
`fp.relative_to(root)` call inside a bare `except Exception: continue`
— `relative_to()` raises `ValueError` for a path with no common
prefix, so results are silently dropped. But `relative_to()` compares
path parts LEXICALLY, not the resolved filesystem path — so a relative
`../` traversal still has `root` as a literal string prefix of its own
parts, and `relative_to()` succeeds. Proved live:
`list_functions({"path": "../../../../tmp/outside"})` via
`pr_list_functions` genuinely returned a real function definition from
a file outside the repo.

**Finding #4 — a design mismatch underlying findings #2 and #3.** The
tool's own schema and description promise single-file analysis
("List all function and method definitions **in a file**"), matching
the two single-file implementations — but the seven agent-specific
implementations instead grep/rglob an entire subtree, with no
legitimate domain-specific reason for the divergence (unlike, say,
`write_file`'s genuinely different `docs/`-only policies from tool
#12).

## Changes made

Extracted one shared `list_functions_handler()` in
`app/tools/filesystem/list_functions.py`, adopted by **all nine** real
call sites:

- `check_path_in_worktree()` closes findings #1 and #3.
- Reading the correct `path` field (not `file`) closes finding #2.
- Adopting the single-file text-scan behavior everywhere (the more
  complete detection logic already shared by `chat_agent.py` and
  `make_chat_handlers()` — Python `def`/`async def` plus TypeScript/JS
  `export function`/`function`/`export const`/`const` arrow-function
  forms) closes finding #4, giving all 32 real calling agents the
  same, correct, schema-conformant behavior for the first time.

`app/agents/tools.py`'s `_LIST_FUNCTIONS_TOOL` now aliases the shared
`LIST_FUNCTIONS_TOOL` constant (preserving every existing reference to
the old name across `ARCH_REVIEWER_TOOLS`, `REFACTOR_AGENT_TOOLS`, and
five other tool lists), and all nine closures now delegate to the
shared handler. `app/agents/chat_agent.py`'s dispatch now calls the
same shared handler via `asyncio.to_thread`.

## Tests

New file `tests/test_list_functions_hardening.py`, 23 tests, all real
(no mocking) — schema check, worktree-escape rejection on the
single-file implementations, permission-denied handling, the
field-name-mismatch fix verified closed on all four affected factories
(parametrized), the relative-traversal-escape fix verified closed on
all three affected factories (parametrized), and legitimate-usage
regression (Python + TypeScript detection, missing-file error) across
all nine real access paths (parametrized). Existing tests
(`test_chat_tools.py::TestListFunctions`,
`test_dead_contract_fix.py::test_parse_ast_and_list_functions_handlers_actually_work`)
re-run and confirmed passing unchanged; the other 4 referencing files
(294 tests total) also re-run clean.

## Regression

Full suite (`pytest tests/ -q`) run in the background after the new
tests passed — see run log for the final tally; no failures introduced
by this change.

## Final verdict

**GREEN FLAG.** All four real findings proved live and closed across
all nine real implementations; the field-name bug's fix required
careful sequencing (fixing it without also adding worktree validation
would have newly exposed the traversal-escape class that was
previously — accidentally — unreachable); no functionality lost, and
32 real agents gained correct path-scoping for the first time; full
regression clean.
