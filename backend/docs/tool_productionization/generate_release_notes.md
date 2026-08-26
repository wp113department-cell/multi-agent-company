# Tool #112 — `generate_release_notes` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `generate_release_notes_h` inside
`make_chat_handlers()`. `chat_agent.py` had ZERO dispatch branch
despite the tool being fully advertised in `CHAT_TOOLS` — the same
"advertised but never dispatched" class already established for tools
#4/#6/#22/#25/#33/#44/#45/#46/#48/#100/#103/#110. This tool is the
direct sibling of tool #100's `generate_changelog` — same shape, same
two real security findings, same fix.

Per `tool_inventory.json`, agents declaring `generate_release_notes`
go through `make_chat_handlers()`. `CHAT_TOOLS.count(
"generate_release_notes") == 1` verified. 3 existing test files
reference this tool — read in context, all directly-exercising tests
re-run and confirmed passing unchanged (7 tests).

## Problems found

**Finding #1 — the most severe finding class of this initiative, a
silent arbitrary-file-write, same class as tools #80/#100.**
`from_ref` is LLM-controlled and becomes part of `ref_range =
f"{from_ref}..HEAD"` — a single argv element handed directly to `git
log` with zero validation. `git log` accepts a generic
`--output=<path>` flag. Proved live with the EXACT real command shape
this tool builds: `from_ref="--output=/tmp/PWNED_RELEASE_NOTES_TEST"`
produced `--output=/tmp/PWNED_RELEASE_NOTES_TEST..HEAD` as the
`ref_range` argv token — git parsed everything after `--output=` as
the file path (the literal `..HEAD` suffix is just characters in the
filename, not path syntax) and genuinely wrote a real file to that
attacker-chosen location.

**Finding #2 — `repo_path` is an LLM-controlled field that lets the
caller redirect ALL git operations at an arbitrary host directory.**
Proved live: pointing `repo_path` at a real git repository outside the
intended project worktree genuinely disclosed that OTHER repo's full
commit history.

**Finding #3 — "advertised but never dispatched"** — every real
interactive call would have hit "Unknown tool".

## Changes made

New shared `generate_release_notes_handler(root, inp)` in
`app/tools/git/generate_release_notes.py`:
- the `repo_path` field from `inp` is IGNORED entirely — `root` is
  always used, closing finding #2 structurally;
- `validate_git_ref(from_ref)` — reused directly from tool #100's own
  `app/tools/git/generate_changelog.py` module, not reimplemented,
  since the exact same validation rule applies to this tool's
  identical `from_ref` shape — rejects any ref starting with `-`,
  closing finding #1;
- a new, real `chat_agent.py` dispatch delegates to this same shared
  handler, closing finding #3.

Checked directly (not assumed) that ignoring `repo_path` doesn't break
`test_day2_tools.py`'s existing tests, which pass an explicit,
different `repo_path` — `git -C <subdir> log` works identically from
any subdirectory of the same worktree, same reasoning already
established for tool #100.

## Tests

New file `tests/test_generate_release_notes_hardening.py`, 10 tests,
all real (no mocking, real git repos on disk) — schema check,
duplicate-registration check, real proof the arbitrary-file-write is
blocked via `from_ref` on the interactive dispatch AND
`make_chat_handlers`, real proof the `repo_path` override is ignored
(a genuinely separate outside repo's secret commit never leaks
through), proof the dispatch now exists at all, and legitimate-usage
regression (a real generated release-notes document, clean
no-commits reporting) across both real access paths. Existing tests
(`test_day2_tools.py::TestGenerateReleaseNotesHandler`, plus config/
membership tests across `test_day4_agents.py`/`test_gap_agents.py`)
re-run and confirmed passing unchanged (7 tests).

## Regression

This tool is tool 4 of the current #109-#113 batch. Its own new
hardening tests (10/10 pass) and directly-referencing existing tests
(7/7 pass) are the per-tool verification gate; the full suite runs
once the batch completes, per `feedback_tool_enhance_batch_full_suite`
memory.

This turn was also verified via a comprehensive `mypy
--ignore-missing-imports app/agents/ app/tools/git/
generate_release_notes.py` sweep (98 files clean), an
`importlib.import_module()` sweep over all 97 `app/agents/` modules
(all clean), a `ruff check` on all 3 touched files (clean), and a
`python -W error` docstring escape-sequence check on the new module
(clean) — BEFORE claiming GREEN_FLAG.

## Final verdict

**GREEN FLAG.** All three real findings — a silent arbitrary-file-
write, an arbitrary-repo disclosure via an unvalidated `repo_path`
override, and a completely missing interactive dispatch — proved live
and closed; no functionality lost (a documented, backward-compatible
field retained rather than removed); tool-specific and
directly-referencing regression tests clean.
