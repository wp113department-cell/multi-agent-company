# 15 — Mission Control Dashboard Specification

**Applies from:** Stage 1, grows every stage
**Related:** `08_API_Specification.md`, `01_Vision_Product_Requirements.md`

---

## Purpose

The dashboard is the human's window into what every agent is doing. It is built incrementally — each stage adds the screens that stage's new capability needs, rather than designing the full final UI before any of it is real.

## Stage 1 — Task List + Detail

**Task List page:** all tasks, status badges (`pending`/`planning`/`coding`/`testing`/`blocked`/`completed`/`failed`), filterable by status and project.
**Task Detail page:** task description, the agent's generated plan, and a chronological log timeline pulled from `task_logs`.

## Stage 2 — Diff Viewer

Added to Task Detail: a side-by-side or unified diff view of the proposed code change, with Approve/Reject actions that call the corresponding API endpoints (`08_API_Specification.md`).

## Stage 3 — Pipeline View

Task Detail expands to show the planning subsystem's stages explicitly: PM output → Architect output → subtask breakdown, each inspectable, with a human approval checkpoint shown before any coding agent starts.

## Stage 4 — Artifact Inspector

Per-task view shows the full pipeline (PM → Architect → Decomposer → Dev → QA → Review), with every artifact (`13_..._Specification.md` cross-reference: `artifacts` table) individually inspectable and downloadable — test output, diffs, review findings, each versioned.

## Stage 5 — Epic Approval View

A new top-level page: epics, each showing all subtasks, all diffs, all QA results, all Code Review findings, and the cost estimate vs. actual, with a single Approve/Reject action covering the whole epic rather than per-subtask approval.

## Stage 6 — Agent Registry View

A new page listing every registered agent: type, version, capabilities, owner, and live success-rate/retry metrics, so a human can see "which agents exist, what version, how reliable" from one place.

## Stage 7 — Productivity Dashboard + Daily Batch Review

A metrics page (tasks completed, average time per pipeline stage, failure rates by agent type/version, pulled from the Agent Registry) plus a "daily batch review" queue — completed-and-ready epics reviewed together on a schedule rather than interrupting a human per epic as they complete.

## Realtime Behavior

Stage 1–4: client-side polling (every few seconds) is sufficient at this scale and avoids building a websocket layer before there's a real need. Stage 5+: Postgres `LISTEN/NOTIFY` (already powering the Event Bus, `12_Event_Bus_Specification.md`) can be piped to the frontend via server-sent events if polling latency becomes noticeably worse than it needs to be — evaluated against actual user feedback, not built speculatively.

## Permissions

Stage 1–4: single internal team, no granular roles needed. Stage 5+: approval actions (epic approve/reject) are restricted to users with an `approver` role in Supabase Auth; everyone on the team can view, not everyone can approve — full detail in `17_Security_Handbook.md`.

## Visual/UX Notes

Status uses consistent color coding across every page (e.g., amber for `blocked`/in-review, green for `completed`, red for `failed`) so a glance at any list communicates state without reading text. Every page that shows an agent's output also shows which agent and which run produced it, with a timestamp — never anonymous output.
