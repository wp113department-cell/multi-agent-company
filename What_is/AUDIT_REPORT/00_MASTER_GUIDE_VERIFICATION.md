# Master Guide Verification: Is `PROJECT_MASTER_GUIDE.md` true?

**Question from the owner:** does everything `What_is/PROJECT_MASTER_GUIDE.md` describes really exist, and what is the proof?
**Method:** each claim was checked against the running code, the live database, the installed packages or an executed probe, not against other documentation. Every number below comes from a script in `evidence/` that anyone can re-run.
**Date / commit:** 2026-09-29, baseline `ef982bf8`

## Verdict

🟡 **YELLOW: the system the guide describes is real, but many specific numbers and details are out of date or overstated.**

Every agent, module, file and page the guide names exists. None of the architecture it describes is invented. But about a dozen specific statements are wrong: counts that have grown, model names from an older generation, sandbox limits and a "7-rung" recovery ladder that don't match the code, and one pipeline step (the Docs agent) that isn't wired in. §3 lists each correction; the guide was updated to match the code as part of this audit.

## 1. Claims that are TRUE (with proof)

| Guide claim | Proof |
|---|---|
| All named agents exist (§5, 78 names) | Every one has a module in `backend/app/agents/`. 75 are registered in the live fleet registry; the other 3 (`bhaskar_agent`, `bhaskar_sandbox`, `temporary_agent`) are internal engines, not selectable agents (`evidence/guide_counts.py`). |
| Every file in the directory map (§7) exists | All 90 paths in the tree plus all 111 backticked file names were checked on disk: 0 missing. |
| Backend library versions (§3) | Installed versions match the guide exactly for all 23 packages (FastAPI 0.139.0, LangGraph 1.2.7, Anthropic 0.115.1, SQLAlchemy 2.0.51, …). |
| Frontend libraries (§3) | Next 15.5.21, React 19.2.0, xterm 6.0.0 match exactly. React Query, Tailwind and Zod are installed at newer patch versions than the guide's minimums. |
| Graph-enforced verification (§9.1) | `VerificationConfig.enforce_in_result` overrides the model's claimed result with tracked tool outcomes. Across all 85 agents there are 0 enforced keys that no tool can set (`evidence/agent_scorecard.py`). |
| Policy denylist blocks `rm -rf`, `docker push`, `npm publish`, `.env` reads (§9.2) | Executed probe: 24 of 26 dangerous commands blocked. The 2 gaps are listed in §3 (`evidence/policy_probe.py`). |
| Production refuses to start without `CREDENTIAL_ENCRYPTION_KEY` (§9.6) | `backend/app/config.py:1968` raises at startup when `DEPLOYMENT_ENV=production` and the key is missing. |
| Voyage `voyage-code-2` embeddings (§9.5) | `backend/app/config.py:45` default. |
| Delegation depth limit 3 (§6.1) | `settings.delegation_max_depth` default 3, enforced at `backend/app/agents/delegation.py:195`. |
| `EnhancementRequest` at `models.py:838` (§5.10) | Exact line match. |
| Human plan-review interrupt with edit/reject steps (§4) | `pipeline/graph.py` `interrupt()` at `human_review`; covered by audit 04. |
| 21 API router modules (§7) | 21 `include_router` calls in `backend/app/main.py:1833-1853`, serving 128 paths / 143 operations. |
| Frontend pages (§12) | `next build` produced all 21 routes, including `/fleet`, `/approvals`, `/console`, `/chat` and `/stream/[taskId]`. |
| pgvector memory, `VersionedLesson`, `EpicScratchpad`, `TaskControlFlag` tables | Present in the live database (51 public tables). |
| 4,000+ tests (§1) | 8,756 tests passed in the baseline run (see `00_BASELINE.md`), so "4,000+" is an understatement. |

## 2. Numbers that changed since the guide was written

| Guide says | Reality (2026-09-29) | Proof |
|---|---|---|
| "72+ agents" | **85** registered agents (99 agent modules) | `evidence/guide_counts.out.json` |
| "170+ tools" | **214** tools in `TOOL_MANIFEST`; the chat agent alone is offered 190 | same |
| "44 database tables / 44 models" | **43** ORM models; **51** tables in the live DB (the extra 8 are alembic, 4 LangGraph checkpoint tables, and 3 raw-SQL tables: `audit_log`, `chat_messages`, `lessons`) | same, plus DB diff |
| "39 Alembic migrations" | **62** migrations, single head `062` | `alembic heads` |
| "93 configuration keys" | **301** `Settings` fields | `evidence/guide_counts.out.json` |
| Header: "450 YES / 95.9%" | The later cleanup record says 452 YES / 13 PARTIAL | memory of 2026-09-28 cleanup |

## 3. Statements that are WRONG (corrected in the guide)

| # | Guide statement | What the code actually does | Evidence |
|---|---|---|---|
| G-1 | Agents use "Claude 3.5 Sonnet / 3.5–3.7 Haiku" | `agent_models.json` routes 63 agents to `claude-sonnet-5`, 9 to `claude-opus-4-8`, 2 to `claude-haiku-4-5`; 13 agents with no entry fall back to the DEFAULT tier (Sonnet 5) | `backend/app/fleet/agent_models.json`, `config.py:28-36` |
| G-2 | Sandbox: "512MB RAM, 1 CPU, 128 PIDs" | `run_sandboxed()` defaults: `--memory=1g`, `--pids-limit=512`, `--cpus=1.0`, 120 s timeout | `backend/app/policy/sandbox.py:95-108` |
| G-3 | `bhaskar_sandbox`: "256MB, 30s" | default `max_memory_mb=512`, enforced with RLIMIT_AS / CPU / FSIZE / NPROC plus a watchdog | `backend/app/agents/bhaskar_sandbox.py:341-449` |
| G-4 | Worktrees at `/tmp/gridiron/worktrees/task-{id}-sub-{index}` | `/tmp/gridiron-worktrees/[epic-{id}/]task-{id}`, one worktree per task shared by its subtasks, on branch `agent/task-{id}` | `backend/app/repo_tools/worktree.py:20-65`, `config.py:57` |
| G-5 | "7-Rung Failure Recovery Ladder" (retry → tool adjustment → re-index → re-plan → alternate specialist → human → abort) | Real recovery: (1) bounded retry with the QA/review error fed back (`manager_max_subtask_retries`); (2) in-graph critique and re-planning (`base_graph` `_should_replan`); (3) escalate (agent marked degraded); (4) human review (task → blocked, `ReviewRequested` event); (5) abort (`TaskFailed`); plus a checkpoint snapshot and an orphaned-run sweep with resume. There is **no** "tool parameter adjustment" or "re-index on failure" rung, and **no** automatic switch to `bug_fix`. | `backend/app/fleet/failure_ladder.py`, `backend/app/agents/manager.py:1700-1760` |
| G-6 | "Docs Agent updates README & Changelog" (pipeline step 7) | `run_docs()` has **no caller** in the task pipeline; the only per-subtask documentation step is the free AST docstring gate (`doc_coverage.py`). Waiting on an owner decision (see audit 02). | `grep run_docs`, `backend/app/agents/manager.py:1182-1191` |
| G-7 | `pipeline/dispatcher.py` is "the topological subtask dependency dispatcher" | Legacy module used only by tests. Real ordering is `_topological_subtask_order` / `_topological_subtask_waves` in `manager.py`; real selection is `fleet_manager.select()`. | `evidence/import_graph.out.json`, `manager.py:49-178` |
| G-8 | File locks: "Subtask B safely waits until Subtask A commits" | `reserve_epic_files()` is an all-or-nothing, cross-**epic** lock that returns a conflict (the epic is halted with `halted_conflict`) rather than waiting | `backend/app/pipeline/file_locks.py:53-75`, `manager.py:2248` |
| G-9 | Bootstrap commit "Initial project scaffold by Gridiron" | Commit message is `chore: initial scaffold by gridiron` | `backend/app/pipeline/bootstrap.py:263` |
| G-10 | Policy denylist blocks all dangerous commands | Quote-splitting (`r''m -rf /`) gets past the pattern match, and cloud CLIs (`aws s3 rm --recursive`) are not denied. Handled in audit 05. | `evidence/policy_probe.out.txt` |
| G-11 | §5 agent list is the full fleet | 7 registered agents are missing from the guide: `roadmap_agent`, `mobile_dev`, `ux_design_agent`, `mcp_developer_agent`, `prompt_engineer_agent`, `tech_advisor_agent`, `agentic_ai_architect` | `evidence/guide_counts.py` |

## 4. How to re-check

```bash
cd backend
.venv/bin/python ../What_is/AUDIT_REPORT/evidence/guide_counts.py
.venv/bin/python ../What_is/AUDIT_REPORT/evidence/policy_probe.py
.venv/bin/python ../What_is/AUDIT_REPORT/evidence/import_graph.py
```
