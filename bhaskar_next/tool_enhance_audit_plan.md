# 190-Tool Productionization — Initial Audit & Plan

Per `bhaskar_next/tool_enhance.md` §28: this is the audit-only planning
pass. **No tool implementation has been changed.** Everything below is
generated from real, programmatic inspection of the repository — the
generator script and its raw output (`tool_inventory.json`) are committed
alongside this doc so every number here is independently reproducible, not
asserted.

Prepared: 2026-08-15

---

## A. Exact tool count

**274 tool specs** discovered by `backend/scripts/generate_tool_inventory.py`
— an AST walk (not regex, not grep) over every `.py` file under `backend/app/`
for dict literals containing both `"name"` and `"input_schema"` keys, the one
tool-spec shape used consistently everywhere in this codebase. This is
higher than the doc's own "approximately 190" estimate — the real count
includes ~50 agent-local `submit_*` result tools (one per specialized agent,
e.g. `submit_subtasks` in `decomposer.py`, `submit_brief` in `pm.py`) that
live outside the shared `app/agents/tools.py` file and would be missed by
inspecting that one file alone.

**212 entries** exist in `app.fleet.tool_manifest.TOOL_MANIFEST` (the
existing structured-metadata system — see §E). **211 of those match a real
discovered tool spec; 1 does not** (`"type"` — purpose text says "Return the
inferred type of a variable or expression"; no tool by that name or matching
that description exists anywhere in the codebase today, confirmed by grep. A
real, if minor, stale-entry finding — see §I).

## B. Tool inventory

Generated: `backend/tool_inventory.json` (274 entries). Each entry has:
`name`, `source_file`, `line`, `has_manifest_entry`, `manifest` (purpose/
permissions/timeout_s/retry_policy/verification_required/risk_level/notes,
when present), `agents` (real, live-imported `AGENT_CONTRACT["allowed_tools"]`
membership — not grepped), `agent_count`, `test_files` (coarse: test files
whose source text contains the tool name as a quoted string literal),
`test_file_count`, `registered`, `reachable_by_any_agent`.

Regenerate any time with: `python backend/scripts/generate_tool_inventory.py`

## C. Current classifications

The doc's six-value classification (`PRODUCTION_READY` / `GOOD_NEEDS_
HARDENING` / `BROKEN` / `UNUSED` / `DUPLICATE` / `PLACEHOLDER`) requires
per-tool inspection — that is the tool-by-tool work itself, not something
this audit pass fabricates in bulk. What IS available programmatically
right now, as real signal to prioritize that work:

- **Risk level** (from the existing, already-real `TOOL_MANIFEST`):
  low=147, medium=53, high=11, no manifest entry=63.
- **Agent reachability**: 3 tools have `agent_count=0` (declared in a spec
  but not in any live `AGENT_CONTRACT["allowed_tools"]` list) — candidates
  for the `UNUSED` classification, to be confirmed per rule §24 (registration
  + agent mappings + call sites + dynamic discovery, not grep alone) before
  labeling them that way.
- **Test coverage signal**: 54 tools have zero test files mentioning their
  name at all (coarse — a per-tool audit may still find indirect coverage
  through an agent-level integration test that never names the tool
  literally, or conversely find that a "test file" hit is unrelated). This
  is a starting signal, not a verdict.

## D. Tool categories

Real categories already exist as risk_level in `TOOL_MANIFEST`
(low/medium/high) plus `permissions` lists (e.g. `["read_repo"]`,
`["write_repo"]`, `["execute"]`, `["execute", "network"]`, `["write_db"]`,
`["read_env"]`, `["docker"]`, `["browser"]`, `["write_remote"]`,
`["write_pipeline_state"]`) — this IS effectively the doc's suggested
`READ_ONLY / LOW_RISK_WRITE / EXECUTION / NETWORK / DATABASE /
SECURITY_SENSITIVE / DEPLOYMENT / DESTRUCTIVE` taxonomy, already present as
data, just not labeled with those exact category names. Mapping permissions
→ the doc's category names is mechanical and will be done as each tool is
processed, not invented wholesale now.

## E. Existing architecture

- **`backend/app/agents/tools.py`** — 14,694 lines. The dominant, shared
  tool-definition file: most cross-agent tools (`read_file`, `write_file`,
  `bash`, git operations, etc.) and their handler factories
  (`make_read_only_handlers`, `make_coder_handlers`, etc.) live here.
- **~50 agent-specific files** (`app/agents/*.py`) each define their own
  local `submit_*` tool (their one way to return structured output) inline,
  not in `tools.py`.
- **`backend/app/tools/`** already exists as a directory, but is NOT the
  modularization the doc's §7 describes — it currently contains exactly one
  file, `git_push_tool.py` (a Day-14-era GitHub-PR-creation module, unrelated
  to any deliberate tools.py-splitting effort) plus an empty `__init__.py`.
  No real migration has started.
- **Real, existing production infrastructure already in place** (confirmed
  by direct inspection, not assumed):
  - `app/policy/engine.py::check_path_in_worktree()` — real workspace-
    boundary enforcement using `realpath` (not `normpath`), specifically so
    a symlink inside the worktree pointing outside it cannot be used to
    escape the sandbox. Wired into `read_file`/`write_file`/etc. via
    `make_read_only_handlers`/`make_coder_handlers`.
  - `app.fleet.tool_manifest.TOOL_MANIFEST` — already a real, structured
    per-tool metadata store (the doc's own "ToolMetadata" concept), consumed
    at runtime by `app.fleet.tool_discovery.filter_runtime_tools()` (plan14
    Day 1's dynamic tool selection: a high-risk tool absent from an agent's
    own capability contract gets silently filtered out of that agent's
    runtime tool list — a real, live enforcement mechanism, not decorative
    metadata).
  - File-size folding (`app.repo_tools.file_folding`, gated by
    `settings.file_fold_enabled`/`file_fold_line_threshold`) — a real,
    config-driven resource-limit pattern already present on `read_file`.
- **No `tool_inventory.json` or `PRODUCTION_TOOL_AUDIT.md` existed before
  this pass** — this is a genuinely fresh start for the inventory/audit
  layer the doc asks for, even though a meaningful amount of the underlying
  production infrastructure (manifest, path-boundary policy, dynamic
  filtering) already exists and works.

## F. Modularization plan

Given E above, the doc's own §7 instruction applies directly: *"Do not
force this exact structure if the existing architecture requires another
design."* Recommendation: **do not attempt a wholesale `tools.py` split as
a standalone project phase.** Instead, extract a tool into its own module
under `app/tools/<category>/` **only as a side effect of that specific
tool's own enhancement pass**, when the enhancement genuinely benefits from
isolation (e.g. a tool getting substantial new logic, or one that's
currently tangled with an unrelated tool's code in the same function).
Every extraction gets a full `TOOL PATH MIGRATION REPORT` (doc §8) at the
time it happens — not a separate, disconnected "migrate everything" pass
that risks exactly the kind of silent agent-misalignment the doc's §8/§10/
§20 explicitly warn about. This keeps blast radius scoped to one tool at a
time, consistent with how every prior initiative in this repo (plan14) was
run successfully.

## G. Agent/path dependencies

Fully captured in `tool_inventory.json`'s `agents` field per tool — derived
by live-importing every module in `app/agents/*.py` and reading its real
`AGENT_CONTRACT["allowed_tools"]` list (91 agent modules import cleanly,
confirmed by this same script running with zero import errors). This is the
authoritative source for "which agents can use this tool" (doc question F),
not a manual list.

## H. Reference repository findings

All 11 repos the doc names as primary references are present under
`/home/pc-117/Documents/CRR2906/repos/`: `aider`, `autogen`, `cline`,
`composio`, `continue`, `langgraph`, `opencode`, `open-hands`, `roo-code`,
`swe-agent`, `andrej-karpathy-skills`. Deep per-repo research is deliberately
deferred to each tool's own STEP 4 (Research references) — reading 11 full
repos generically now, before knowing which specific tool is being worked
on, would produce exactly the kind of un-grounded "reference dump" the doc's
§4/§23 warn against ("Do not automatically copy behavior... The question is
NOT 'Does another repository have this tool?'"). Note: this codebase already
demonstrates the correct citation discipline in practice —
`app/tools/git_push_tool.py`'s own module docstring cites two specific real
files it drew a pattern from (`repos/open-hands/.../prs.py`,
`repos/aider/aider/repo.py`) and explains what was reused vs. reimplemented.
That is the standard every tool's enhancement pass will follow.

## I. Production gaps (real, evidence-backed findings from this pass)

1. **63 tools have no `TOOL_MANIFEST` entry at all** — no declared
   permissions/timeout/risk_level/retry_policy. These need a manifest entry
   created as part of their own enhancement pass (not bulk-generated
   blindly — permissions/risk_level must reflect what the tool actually
   does, verified per rule §2).
2. **1 stale manifest entry** (`"type"`) with no matching real tool —
   needs investigation (was it renamed? removed? never implemented?) before
   any action; not touched during this audit pass per the "no implementation
   during audit" rule.
3. **3 tools with zero agent reachability** (`agent_count=0`) — candidates
   for `UNUSED`, pending the fuller verification §24 requires (dynamic
   discovery, runtime traces) before that label is applied.
4. **54 tools with zero test-file references** — a coarse signal; the real
   test-adequacy determination happens per tool during its own audit
   (doc §13's actual minimum-test checklist), not from this count alone.
5. **`app/tools/` package structure is aspirational, not real** — see §E.

## J. Day-by-day / batch execution plan

274 tools individually audited-to-GREEN-FLAG is roughly **20x the scope**
of the entire prior plan14 initiative (14 items, multiple real working
sessions). Attempting all 274 in one unverified pass would directly violate
the doc's own rules 1/2/7/9 (zero hallucination, zero blind assumptions,
real testing only, no premature green flags) — there is no way to give 274
tools genuine individual audit + real execution + real tests in a single
pass without that rigor collapsing under the volume.

**Recommended pacing**: process tools in the priority order from §K, in
batches — a natural batch size is 3-6 tools per working session (similar
throughput to plan14's own per-day scope), each batch getting:
- individual STEP 1-11 treatment per tool (doc §6),
- a batch-level regression run (`pytest` targeted sweep + periodic full
  suite, matching the standing convention already established this session),
- an update to the tracking list (`bhaskar_next/tool_enhance_tracking.md`)
  and this repo's evidence trail.

No fixed total day-count is asserted here — that would be a guess dressed
as a plan. Batches continue until every tool in `tool_inventory.json` has
a real classification and, where applicable, a GREEN FLAG (or a
documented, evidence-backed reason it cannot yet receive one, per doc §26).

## K. Tool-by-tool execution order (generated, not manual)

Sort key: `risk_level` (high → medium → low → no-manifest-entry), then
`agent_count` descending (most-used tools fixed first — highest leverage,
since a hardening fix benefits every agent that already depends on the
tool), then name for determinism. Full list: `bhaskar_next/
tool_enhance_tracking.md` (274 rows, generated from `tool_inventory.json`).

Top of the queue (the real, generated order — first 11 rows are every
`risk_level=high` tool in the manifest):

| Order | Tool | Risk | Agents | Manifest | Test files |
|---|---|---|---|---|---|
| 1 | `bash` | high | 23 | yes | 31 |
| 2 | `create_pr` | high | 1 | yes | 2 |
| 3 | `delegate_to_agent` | high | 1 | yes | 0 |
| 4 | `git_push` | high | 1 | yes | 9 |
| 5 | `git_reset` | high | 1 | yes | 1 |
| 6 | `github_create_pr` | high | 1 | yes | 1 |
| 7 | `propose_subtask` | high | 1 | yes | 0 |
| 8 | `run_migration` | high | 1 | yes | 3 |
| 9 | `run_parallel_commands` | high | 1 | yes | 1 |
| 10 | `seed_database` | high | 1 | yes | 2 |
| 11 | `undo_changes` | high | 1 | yes | 3 |

Then medium-risk tools ordered by agent_count, starting with `write_file`
(60 agents, 35 test files) and `edit_file` (19 agents, 14 test files) — the
two most-depended-on write tools in the entire fleet.

## L. Testing strategy

Reuses the exact real-execution-only convention already proven across the
whole plan14 initiative (real temp files for filesystem tools, real
`git init` + real commands for git tools, real Postgres for DB tools, real
subprocess execution for bash/test-runner tools; mocked only at the
`anthropic.Anthropic` LLM boundary and genuinely external network
boundaries) — this already satisfies the doc's own §13/§14 minimums
(happy path, invalid input, missing input, permission failure, security
boundary, tool error, output contract, regression; plus timeout/adversarial-
input/injection/path-traversal/secret-leakage/destructive-op protection
where applicable) without inventing a new testing philosophy.

## M. GREEN FLAG acceptance criteria

Adopted verbatim from `tool_enhance.md` §3/§17 — no modification. A tool
gets GREEN FLAG only once every applicable box in that checklist is
independently verified, with the SAME "verify before declaring green" bar
plan14 held for all 14 of its items with zero exceptions.

## N. Risk analysis

- **Scope risk (the dominant one)**: 274 tools is large enough that
  pacing/consistency discipline matters more than speed. Mitigation: fixed
  batch size, the generated tracking list as the single source of truth for
  "what's pending," and periodic full-suite regression runs exactly as
  plan14 already established.
- **Regression risk**: `app/agents/tools.py` is 14,694 lines with dense
  interdependency (shared handler factories used by ~90 agents). Mitigation:
  the doc's own §21 (do not silently modify unrelated systems) plus this
  session's own established habit of a targeted regression sweep after every
  change and a full-suite run before declaring green flag.
- **False-precision risk**: the 54-tool "zero test files" and 3-tool
  "zero agents" signals are coarse and must be re-verified per tool (per
  §24/§25's own explicit instruction not to conclude UNUSED/DUPLICATE from
  grep alone) — not treated as final verdicts by this audit pass.
- **Modularization risk**: forcing the doc's suggested `app/tools/` package
  structure wholesale, disconnected from real per-tool work, risks exactly
  the "moved tool with an agent still pointing at the old location" failure
  mode §8/§10 warn about. Mitigation: §F's decision to extract only as a
  side effect of a tool's own enhancement pass, each with its own migration
  report.

---

## Next step

Per the master prompt's own §28/§29: this audit pass stops here. Awaiting
confirmation before starting STEP 1 (Locate) on tool #1 (`bash`) — the
highest-priority tool by the generated execution order in §K.
