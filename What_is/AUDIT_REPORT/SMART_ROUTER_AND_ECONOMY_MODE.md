# Smart Router, Economy Mode and Warm Caches

**Built:** 2026-09-29, before resuming audits 08–14 (owner decision)
**Goal set by the owner:** run 2–3 tasks a day for **≤ $1/day** in total, faster, using only the agents a task really needs.

## Why it was expensive

Measured in the code before this change:

- **One pipeline for every task.** In "full" mode: PM (Sonnet) → Architect (**Opus**) → Decomposer (**Opus**), then **per subtask** dev + QA + reviewer + **3 LLM quality gates** (security, architecture, dependency). A 1-subtask change was **9 agent runs**; a 3-subtask task about **21**.
- **Hidden calls inside every run.** 2 planner calls, a **reflection call on every turn using the agent's own (expensive) model**, a critique call, a lesson call. Until the audit 07 fix these weren't even counted.
- **Conversation history re-sent at full price** on every turn (only the system prompt and tools were cached).

## What was built

### 1. Smart task router (`PIPELINE_MODE=auto`, now the default)

`app/pipeline/task_router.py`. Every task is classified once:

| Tier | How it's recognised | Who runs |
|---|---|---|
| **small** | one area: UI words (button, page, CSS, component, layout, …) **or** backend words (API, endpoint, database, migration, …) | **one specialist**: `frontend_dev` or `backend_dev` (`coder` if the area is unclear) |
| **medium** | both UI and backend | `backend_dev`, then `frontend_dev`, in the same worktree (the second is told what the first changed) |
| **large** | "from scratch", "new project", "entire app", microservices, … or a very long description | the existing full pipeline (PM → Architect → Decomposer → subtasks) |

- **Free first:** keyword rules decide most tasks. Only when they can't does it make **one** tiny Haiku call (max 80 output tokens, about $0.001).
- **Cached:** the decision is stored by task text, in Redis when reachable (shared by all backend processes), otherwise in memory, so a re-run never pays for routing again.
- **Human gates unchanged:** the routed plan still needs your **approval before any code is written**, and **git push still needs approval**. The plan shows which agent was chosen and why.
- **Manual override:** on the task page, **Smart Run** is the green primary button; **Full Pipeline** and **Run Planner Agent (quick)** are still there if you want them.

### 2. Cost modes (`COST_MODE=economy`, now the default)

`app/fleet/cost_mode.py`, one setting applied to every agent run:

| | economy (default) | balanced | quality (old behaviour) |
|---|---|---|---|
| Model tier | **Haiku** | up to Sonnet | as routed (incl. Opus) |
| Planner calls | off | on | on |
| Reflection every turn | off | off | on |
| Critique / replanning | off | critique on | on |
| Lesson extraction | off | on | on |
| 3 LLM quality gates per subtask | off (the free regression and docstring gates stay on) | off | on |
| Max turns per run | 15 | 25 | agent default |

**Never affected by the mode:** the Docker sandbox, command/path policy, scoped file writes, secret redaction, human approvals. Those cost nothing and are identical in every mode.

A single task can run in a different mode than the global default (the router can pass one); worker threads inherit it automatically.

### 3. Token savings in every mode (no quality cost)

- **Conversation-history caching:** the newest message is marked as a cache breakpoint on each call, so the next turn pays about 10% for everything already sent (`_with_history_cache_breakpoint`, `base_graph.py`).
- **Every LLM call counted** (audit 07 fix), so budgets and cost reports finally see real spend.

### 4. Speed ("warm agents")

- **Repo index cache:** the per-run repo scan (75 s this morning, 2.8 s after the `.gitignore` fix) is now reused until the repo's git state changes: **3.3 s → 0.01 s** on repeat runs (`scanner.index_repository_cached`).
- **Warm-up at startup:** the index is built in the background when the server starts, so the first task is fast too.
- One agent run instead of 9 for a small task is also the biggest speed-up: roughly minutes instead of tens of minutes.

## Expected cost: a typical small task ("make the login button blue")

| | Before (full + quality) | Now (auto + economy) |
|---|---|---|
| Agent runs | 9 | **1** |
| LLM calls | ~70 | ~4–6 |
| Model | Sonnet / Opus | Haiku |
| **Estimated cost** | **~$3–5** | **~$0.05–0.10** |

So **2–3 small tasks a day ≈ $0.15–0.30**, inside the $1/day target. Medium tasks (2 specialists) are roughly double. Large tasks still use the full pipeline and cost more; use them for new projects.

**These are estimates from the code and measured call counts, not a live bill.** In the real graph with a faked LLM, economy made **3 calls where quality made 8** for the same 2-turn job. The first real runs after the $5 recharge will give exact numbers (`PENDING_TESTS_API_KEYS.md` L7).

## Honest trade-offs

- Haiku writes weaker code than Sonnet or Opus. For tricky changes, set `COST_MODE=balanced` (about 3× economy) or run that task with **Full Pipeline**.
- Economy has no separate AI reviewer or AI security gate on each change. The free checks (the agent's own tests and lint loop, the regression gate, the docstring gate) and your review before push remain.
- Keyword routing can misjudge a vaguely worded task. The plan approval step shows the chosen agent, so you can reject it and use Full Pipeline instead.
- Redis makes routing decisions shared and instant across processes. It doesn't by itself reduce AI token cost; the router, the cost mode and the caching do.

## Verified by tests

| Test file | What it proves |
|---|---|
| `tests/test_cost_modes.py` (11) | profiles, per-task override reaches worker threads, economy = main-loop calls only on Haiku, quality unchanged, balanced caps Opus→Sonnet, history cache marker sent without mutating state, LLM gates skipped but free gates still run |
| `tests/test_task_router.py` (12) | rule routing for small/medium/large, one LLM call then cached, fallback, and **end to end through the real app:** a UI-only task → routed plan (no planning agents) → approve → **only `frontend_dev` ran** → real commit → push waiting for approval |
| `tests/test_audit04_scanner_gitignore.py` (5) | index cache reused until an edit or a commit |

## Settings

```env
PIPELINE_MODE=auto     # auto | full | simple
COST_MODE=economy      # economy | balanced | quality
```
