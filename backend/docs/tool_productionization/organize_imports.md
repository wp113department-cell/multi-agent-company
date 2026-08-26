# Tool #115 — `organize_imports` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

Three real implementations:

1. `chat_agent.py`'s own interactive dispatch.
2. `organize_imports` inside `make_chat_handlers()`.
3. `cu_organize_imports` (`make_cleanup_agent_handlers`).

Per `tool_inventory.json`, agents declaring `organize_imports` go
through one of these. `CHAT_TOOLS.count("organize_imports") == 1`
verified. 3 existing test files reference this tool
(`test_chat_tools.py::TestOrganizeImports`,
`test_day3_agents.py::test_includes_organize_imports`,
`test_stage4_tier3_venv_activate_cross_platform.py`) — all re-run and
confirmed passing (the third required a small, expected update, see
below).

## Problems found

Three real, empirically-verified findings.

**Finding #1 (most severe) — a genuine, direct shell-injection
(arbitrary command execution) on `chat_agent.py`'s dispatch.** The
LLM-controlled `path` field was interpolated COMPLETELY UNQUOTED into
an f-string `shell=True` command:
```python
cmd_s = f"{activate} && python -m ruff check --select I --fix {str(oi_target)} 2>&1"
```
Proved live, in an isolated `/tmp` directory: a `path` value of
`"; touch <marker>; echo x"` genuinely created the marker file,
confirming arbitrary command execution.

**Finding #2 — worktree-boundary escape that is a genuine ARBITRARY
FILE MODIFICATION, not just a read, on both `chat_agent.py`'s dispatch
and `organize_imports` (`make_chat_handlers`).** Neither validated
`path` before `root / path` — an absolute path discards `root`
entirely (`pathlib` semantics). Because this tool's whole purpose is
running `ruff --fix`, which rewrites the target file in place, this is
a strictly more severe primitive than the disclosure-only
worktree-escape findings from tools #83/#111. Proved live, in an
isolated pair of `/tmp` directories (a fake "repo root" and an
"outside" file), that a file completely outside the intended worktree
was genuinely rewritten with its imports reorganized.

**Finding #3 — a real functionality-divergence bug:
`cu_organize_imports` used a completely different tool (`isort
--diff`) than the one the schema documents (`ruff`), and never
actually applied any change** — it only previewed what would change,
contradicting the schema's own promise ("Sort and organize... Also
removes unused imports"). This implementation's worktree-boundary
handling was already correct (`_is_protected_path(cu_path,
repo_path)`, which — given `worktree_path` — already performs full
worktree-containment checking, the same established pattern as tool
#11).

### Incident during live verification (fully resolved, disclosed in full)

The first attempt at reproducing finding #1 ran the constructed
(still-vulnerable) command directly, without pinning an isolated `cwd`
for the reproduction. The injected payload left `ruff --fix` with no
valid target argument, and — because the ambient shell's working
directory was the real project checkout — `ruff --fix` fell back to
recursively organizing imports across the entire `backend/` directory
(182 files, pure import reordering, no logic changes). This was caught
immediately via `git status`, the scope and nature of the change was
confirmed via `git diff --stat` and a sampled `git diff` (import-block
reordering only), and every affected file was reverted via `git
checkout -- <exact file list>` before any commit. Full restoration was
verified via `git status` (clean), syntax + `importlib.import_module()`
checks on the two touched god-files, and `git log --oneline -1`
confirming HEAD was still the prior legitimate commit. Both required
live proofs (finding #1 and finding #2) were then re-derived safely,
entirely within isolated `/tmp` directories with explicit `cwd=`
parameters. This established a new standing practice for this
initiative: any live-exploit reproduction for a tool whose underlying
mechanism can WRITE/MODIFY files must use a fully isolated `/tmp`
directory as both the simulated worktree and any "outside" location,
with `cwd=` always explicit — never the real project directory.

## Changes made

New shared `organize_imports_handler()` in
`app/tools/filesystem/organize_imports.py`:
- List-args `subprocess.run()` only — `shell=True` dropped entirely,
  closing finding #1 structurally (there is no shell to inject into).
- `path` validated via `check_path_in_worktree()` before any
  filesystem access, closing finding #2.
- Uses `ruff check --select I --fix <target>` (matching the schema's
  own documented mechanism and genuinely applying the fix), closing
  finding #3 by replacing `cu_organize_imports`'s diverging
  preview-only `isort --diff` implementation.

All three real call sites (`chat_agent.py`'s dispatch,
`organize_imports` in `make_chat_handlers`, `cu_organize_imports` in
`make_cleanup_agent_handlers`) now delegate to this one handler.
`app/agents/tools.py`'s `_ORGANIZE_IMPORTS_TOOL` now aliases the
shared `ORGANIZE_IMPORTS_TOOL` constant. No external direct-importers
of the old schema name were found.

A dangling `import subprocess as _sp` in `make_cleanup_agent_handlers`
(only used by the now-replaced `cu_organize_imports`) was removed as
part of this change — caught by `ruff check` (F401), not left in.

`tests/test_stage4_tier3_venv_activate_cross_platform.py` was updated:
this fix removes 1 more of the shell-snippet call sites counted by
that test's regression guard (7 real call sites now remain in
`app/agents/tools.py`, down from 8), matching the exact precedent set
by tool #101's `run_linter` fix.

## Tests

New file `tests/test_organize_imports_hardening.py`, 12 tests: schema
check, duplicate-registration check, shell-injection-blocked proof
(direct handler + `chat_agent.py` dispatch), worktree-escape-write-
blocked proof (parametrized across `make_chat_handlers`/
`make_cleanup_agent_handlers`, plus `chat_agent.py` dispatch) with an
assertion the outside file's content is genuinely untouched,
`cu_organize_imports`-now-genuinely-applies-the-fix proof (real file
content change, not just a status string), and legitimate-usage
regression across all three real access paths. All tests use
`tmp_path` exclusively — no real-project-directory exposure, applying
the safety lesson from the incident above.

Existing tests re-run and confirmed passing:
`test_chat_tools.py::TestOrganizeImports` (2/2),
`test_day3_agents.py::test_includes_organize_imports` (1/1),
`test_stage4_tier3_venv_activate_cross_platform.py` (3/3, after the
expected count update described above).

## Regression

This tool is tool 2 of the #114-#118 batch. Its own new hardening
tests (12/12 pass) and directly-referencing existing tests (6/6 pass)
are the per-tool verification gate; the full suite runs once the batch
completes, per `feedback_tool_enhance_batch_full_suite` memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/filesystem/
organize_imports.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all touched files (clean after removing
the dangling `_sp` import and an unused `asyncio` import in the new
test file), and a `python -W error` docstring escape-sequence check on
the new module (clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real, empirically-verified findings proved
live (safely, in isolated `/tmp` directories) and closed across all
three real implementations; `cu_organize_imports` now genuinely
matches its own documented contract instead of silently diverging from
it; no functionality lost — legitimate usage is proven to still work,
and now actually applies fixes on all three paths where before only
two of three did; tool-specific and directly-referencing regression
tests clean. A real incident occurred during verification (an
accidental 182-file mutation from an unsafely-run reproduction) and
was fully caught, reverted, verified, and disclosed before this tool
was advanced — see above for the complete account.
