# Audit 15: Self-Improvement & Meta-Agents

**Date:** 2026-10-06 · **Scope (owner request):** Fleet Directory §5.1 (barot_agent, bhaskar_agent / bhaskar_tool, bhaskar_sandbox, temporary_agent) and §5.10 (the 5 self-improvement agents, enhancement requests, `/fleet` approval, APPLY, rollback). These are the systems meant to keep the project working when no agent or tool fits a task, and to make it better day by day.

**Method:** every claim in the owner's fleet description was traced in code, then proven by a real run. All of these were real: Postgres, git, Docker containers, sandbox subprocesses, pytest runs and the `/fleet` endpoints. **No Anthropic API call was made.** Where an agent needed a model answer, an in-process mock of the client played its turns, as the project's own test suite does. Every bug found was fixed with a test that fails on the old code.

## Result

🟢 **GREEN after fixes.** The systems are real and now work end to end. Before this audit:
- one critical security hole and three real bugs existed;
- barot could not be reached for its stated purpose;
- the self-improvement loop edited the owner's working copy directly.

## Verdict per component

| Component | Claim | Verdict | Evidence |
|---|---|---|---|
| **bhaskar_sandbox** | Isolated runner; scripts can't touch the project or secrets | 🔴 → 🟢 | A real attack script **read `backend/.env` (API keys)** through `_io.FileIO` and `ctypes`. The file guard was Python-level only, and network is on by default. **Fixed:** scripts now run in a throwaway Docker container (details under bug 1). All 17 attacks were re-run: blocked. `test_bhaskar_sandbox_docker.py` (10 real-container tests) |
| **bhaskar_tool / bhaskar_agent** | Writes a script, tests it in the sandbox, returns verified output; cached for reuse; no recursion | 🟡 → 🟢 | End to end: a tested script is **independently re-run** before it is trusted; a script reaching for `.env` is neither successful nor trusted; the recursion guard holds. **The cache never stored anything** (UUID query bug). **Fixed:** cached scripts now replay in the sandbox without asking the model again. `test_bhaskar_e2e_docker.py` |
| **barot_agent** | Fills a capability gap no agent covers by spawning a temporary agent | 🟡 → 🟢 | Wiring was real, but **unreachable for a real gap**: the delegation allow-list only named capabilities that already had an agent, so barot only ever stood in for a busy agent. **Fixed:** with a `*new*` entry, `backend_dev`, `frontend_dev` and `bug_fix` can ask for a capability nobody has. Proven end to end: plan → spawn (a requested `write_file` is refused: read-only only) → run → result → teardown. `test_barot_gap_fill_e2e.py` |
| **temporary_agent** | Short-lived, bounded, cleaned up | 🟢 | Existing real tests: capacity limit (3), TTL reaping loop, recursion guard, tool denylist; teardown also shown in the barot end-to-end test |
| **Daily scans (5 agents + 3)** | Agents scan the platform and file proposals | 🟠 → 🟢 | All **8** scans the loop runs file a real pending request (`test_fleet_agents_scan_and_curate_e2e.py`). **Cost problem fixed:** scans ran **every 4 h (~48 LLM runs/day with nobody using the app)** and shared the daily cap with the owner's tasks. Now **daily by default**, and only while today's spend is below **half the cap** (`FLEET_SCAN_BUDGET_FRACTION`) |
| **Approve → APPLY → commit** | On approval the agent fixes it, runs tests, commits | 🟠 → 🟢 | APPLY **edited and committed directly in the live working copy** on the owner's branch, next to their uncommitted work. **Fixed:** each APPLY runs in its own worktree on `fleet/enh-<id>`, then merges back. Git refuses a merge that would touch uncommitted work; the branch is then kept and the request says so. Guards proven: **no commit before tests ran**, and an edit re-arms that. Full cycle: `test_self_improvement_cycle_e2e.py`; workspace: `test_enhancement_workspace.py` |
| **Automatic rollback** | A change that makes an agent worse is reverted | 🟢 | Proven on a real repo: a measured decline → `git revert` → the bug is back, and `rolled_back` plus the revert SHA are recorded. Only a change that actually landed is monitored |
| **knowledge_curator** | Curates memory: promote/merge lessons | 🟢 | APPLY promotes a draft lesson to `published` (test above). Merge-on-conflict was proven live earlier (L3, `evidence/live_lesson_merge.py`) |
| **agent_advisor** (+ architecture_reviewer, dependency_security_agent, monitoring_agent) | Advisory | 🟢 by design | No APPLY phase. `/fleet` shows **"Acknowledged — no automated apply phase, so no code was changed"**. Honest; not a bug |

## Bugs found and fixed (all with tests that fail on the old code)

1. 🔴 **Sandbox escape: synthesized scripts could read `backend/.env` (API keys).** Network was on by default, and bhaskar also has web search, so a prompt-injected script could have sent the keys out. Fix: a Docker backend, now the default:
   - no host path mounted, code arrives on stdin;
   - non-root, read-only root, all capabilities dropped, `no-new-privileges`;
   - kernel memory, pid and CPU limits;
   - a size-capped tmpfs, so the disk quota is hard (a fast 200 MB burst used to get past the polled quota);
   - it **refuses** to run without Docker. The old in-process mode is an explicit opt-in. (`162f0658`)
2. 🟠 **Background scans could use up the owner's budget.** They ran every 4 h and shared the cap with the owner's tasks. Now daily, and capped at half the budget. (`b830b77f`)
3. 🟠 **APPLY edited the live working copy directly.** Now an isolated worktree plus merge, refused safely on conflict. A real bug in the first version of this fix (the routing was set inside a worker thread, so it was invisible to the agent) was caught by the existing tests and fixed. (`cc4f1e4b`)
4. 🟡 **barot unreachable for real gaps.** Fixed with `*new*` delegation. (`f7006e9d`)
5. 🟡 **bhaskar cache never stored anything.** The scratchpad write looked up a UUID column with the id `"__bhaskar_tool__"`. Fixed. (`6a2c2076`)

## Known limits (documented, not hidden)

- **bhaskar verification proves a script runs, not that its answer is right.** The calling agent sees the output and must judge it. An LLM-graded check would cost a call per script.
- **Temporary agents are read-only.** Write and bash scope (`barot_agent_default_tool_scope="full"`) is accepted by config but not implemented; it would need a worktree like APPLY now has.
- **Only 4 of the 8 scanners can apply.** The other 4 are advisory by design.
- **Model quality is untested here.** These runs prove the machinery with a scripted model; how good real proposals are was measured separately (audit 07 evals).

## Next tasks (owner's enhancement backlog)

| # | Task | Why |
|---|---|---|
| 1 | Temporary agents with **write scope** in their own worktree (reuse `enhancement_workspace.py`) | Lets barot fill gaps that need code changes, not just analysis |
| 2 | **Semantic check of bhaskar outputs** (one cheap judge call, like the eval judge) | Closes the "runs ≠ correct" limit |
| 3 | **APPLY phase for agent_advisor**: routing changes as config edits through the same approve → worktree → merge path | Turns advice into one-click changes |
| 4 | **Skip unchanged scans** (no new commits/runs since the last scan → no LLM call) | Further cuts daily cost |
| 5 | **Dashboard: show the kept branch** when an automatic merge was refused, with a one-click merge | Today the request's error text explains it |
| 6 | **Network allow-list for bhaskar scripts** (per-domain) | Today network is all-or-nothing, behind the IP guard |

## Files

- Fixes: `backend/app/agents/bhaskar_sandbox.py`, `backend/app/fleet/enhancement_workspace.py` (new), `backend/app/api/fleet_dashboard.py`, the 4 APPLY agents, `backend/app/agents/delegation.py`, `backend/app/tools/agents/delegate.py`, `backend/app/fleet/scratchpad.py`, `backend/app/main.py`, `backend/app/config.py`
- Tests:
  - `test_bhaskar_sandbox_docker.py`
  - `test_bhaskar_e2e_docker.py`
  - `test_barot_gap_fill_e2e.py`
  - `test_enhancement_workspace.py`
  - `test_self_improvement_cycle_e2e.py`
  - `test_fleet_agents_scan_and_curate_e2e.py`
  - `test_fleet_scan_budget_guard.py`
