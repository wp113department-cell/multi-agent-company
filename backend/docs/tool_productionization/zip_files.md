# Tool #209 — `zip_files` — production hardening report

Per `bhaskar_next/tool_enhance.md`'s workflow: AUDIT → RESEARCH →
REQUIREMENTS → DESIGN → IMPLEMENT → TEST → REAL EXECUTION → REGRESSION →
AGENT ALIGNMENT → FINAL VERIFICATION → GREEN/YELLOW/RED FLAG.

## Current implementation (audit)

One real implementation: `zip_files_h` inside `make_chat_handlers()`.
Exclusively a `CHAT_TOOLS` entry (membership count confirmed = 1);
grepped all other agent files — none reference `"zip_files"` in their
own `allowed_tools`.

Separately, `app/agents/base_graph.py::_policy_check()`'s generic
`write_repo`-permission path-field check (`check_path()`, a
denylist-only check — NOT worktree confinement) already covers
`zip_files`'s `output` field for `run_agent_graph`-based agents. But
since zero real agents actually dispatch this CHAT_TOOLS-only tool
through that path, that coverage was structurally present but
practically unreachable for this tool — and even reachable, it would
not have caught the arbitrary-absolute-path escape below, since
`check_path()` only denies a fixed set of protected filenames (`.git`,
SSH keys, etc.), not worktree confinement.

## Problems found

Three real, empirically-verified findings — the write-side finding is
a severe "arbitrary file write with real, attacker-chosen content"
primitive, the same severity tier as sibling tool #206's
(`unzip_files`) `dest` finding.

1. **`output` had zero worktree-boundary validation — a genuine
   content-exfiltration primitive, not just a write-location bug.**
   `out_path = root / output` silently discards `root` when `output`
   is absolute. Proved live: `zip_files({"source": "secret_config.py",
   "output": "<absolute path outside repo>"})` genuinely wrote a real
   zip archive containing the real file's full content to that
   arbitrary absolute path — confirmed by reading the exfiltrated
   archive back and finding the real secret string inside it,
   completely outside the intended worktree.
2. **`source` had zero worktree-boundary validation.** Same
   discard-on-absolute behavior; while `f.relative_to(root)` prevents
   pure content disclosure through `source` alone, it's real
   LLM-controlled, unvalidated behavior with real side effects
   (leaves junk `.zip` files at arbitrary locations derived from an
   absolute source).
3. **Advertised but never dispatched, on the interactive chat agent —
   same class as tools
   #100/#103/#110/#112/#118/#120/#122/#126/#129/#130/#131/#132/#133/#134/#135/#136/#137/#138/#139/#140/#141/#142/#144/#202/#203/#204/#206/#207/#208.**
   `zip_files` is in `CHAT_TOOLS` and registered in
   `make_chat_handlers()`'s handlers dict, but
   `app/agents/chat_agent.py`'s `_execute_tool()` had NO dispatch
   branch for it — every real interactive-chat call fell through to
   `"[ERROR] Unknown tool: zip_files"`.

## Changes made

Extracted into `app/tools/filesystem/zip_files.py` (`ZIP_FILES_TOOL`,
`zip_files_handler`): both `source` and `output` are validated with
`check_path_in_worktree()` before either is used, closing findings #1
and #2. A new `chat_agent.py` `_execute_tool()` dispatch delegates to
this same shared handler, closing finding #3.

## Tests

`tests/test_batch11_policy_check_structural_chokepoint.py::test_zip_files_protected_output_denied`
exercises the unrelated, already-existing `_policy_check()` denylist
coverage directly — unaffected by this change, re-run and confirmed
passing. `tests/test_new_tools.py::test_zip_unzip` uses only
in-worktree relative paths — unaffected.

New file `tests/test_zip_files_hardening.py`, 15 tests: schema check,
`CHAT_TOOLS` single-registration check, content-exfiltration-blocked
proof on all 3 real access paths, proof a real absolute output path
inside the worktree is still allowed, source worktree-escape blocked,
dispatch no longer "Unknown tool", and legitimate-usage regression
(real single-file and directory zipping with archive-content
verification, missing-source error) verified through both real access
paths.

## Regression

This tool's own new hardening tests (15/15 pass) plus
`tests/test_new_tools.py` + `tests/test_batch11_policy_check_structural_chokepoint.py`
(59 total across all three files). Also ran a broader chat_agent
regression sweep (`test_audit_q_batch10_chat_agent_dispatch.py`,
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

**GREEN FLAG.** Three real findings (a content-exfiltration primitive
via unvalidated `output`, a worktree-escape on `source`, and a
completely non-functional interactive-chat dispatch) identified and
fixed. No functionality lost, legitimate usage verified end-to-end
(including real archive-content correctness) on both real access
paths. Tool-specific and broader chat_agent regression tests clean.
Agent alignment verified: PASS (`chat_agent.py`'s dispatch and
`make_chat_handlers()`'s handler both now route through the one
shared, worktree-validated implementation).
