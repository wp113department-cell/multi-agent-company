# 12 — Event Bus Specification

**Applies from:** Stage 4, upgraded at Stage 7
**Related:** `02_System_Architecture_Blueprint.md`, `06_Agent_SDK_Specification.md`

---

## Purpose

From Stage 4 onward, multiple specialist agents need to react to each other's progress without being directly wired together. The Event Bus decouples this: agents emit events when they finish meaningful work, and other agents (or the dashboard) subscribe to the events relevant to them. Adding a new agent type later means subscribing it to existing events, not rewiring every other agent's code.

## Transport

**Stage 4:** Postgres `LISTEN/NOTIFY` — sufficient at this scale, no new infrastructure to stand up, lives in the same database already in use.
**Stage 7:** Redis Streams, introduced only once concurrent epic volume genuinely requires higher throughput than Postgres notification can comfortably handle (see `02`, ADR reasoning on not over-building infrastructure ahead of need). Full Kafka-style infrastructure is not planned at any stage currently scoped — see `14_Scheduler_Specification.md` for the related reasoning on right-sizing this kind of infrastructure.

## Event Schema

```json
{
  "event_id": "uuid",
  "event_type": "string",
  "task_id": "uuid | null",
  "epic_id": "uuid | null",
  "payload": { },
  "emitted_by": "agent_type",
  "created_at": "timestamp"
}
```

## Core Event Types

| Event | Emitted By | Consumed By |
|---|---|---|
| `task.created` | Task Engine | Manager Agent, dashboard |
| `task.planned` | Planner / PM Agent | Architect Agent |
| `architecture.ready` | Architect Agent | Task Decomposer |
| `subtask.assigned` | Task Decomposer / Manager Agent | Backend/Frontend/QA agents (dispatch trigger) |
| `qa.passed` | QA Agent | Code Review Agent |
| `qa.failed` | QA Agent | The originating dev agent (triggers fix loop) |
| `review.completed` | Code Review Agent | Manager Agent, dashboard |
| `epic.completed` | Manager Agent | Documentation Agent, dashboard (Epic Approval view) |
| `task.blocked` | Any agent | Dashboard (human notification) |

## Routing

Consumers subscribe by `event_type`; no broadcast-to-everyone pattern. The Manager Agent (Stage 5+) additionally subscribes to all subtask-level events for a given `epic_id` to maintain its progress view.

## Retries & Failure Handling

If a consumer fails to process an event (e.g., the dispatch trigger errors before spawning the subagent), the event is retried up to 3 times with backoff, then written to a `failed_events` log table for human review — a lightweight dead-letter pattern appropriate to current volume, not a dedicated DLQ infrastructure component. Revisit if event volume at Stage 7 concurrency makes manual review of `failed_events` impractical.

## Ordering

Events are not guaranteed globally ordered across different tasks/epics (they run independently and in parallel by design), but are ordered within a single `task_id`'s event stream, which is what consumers actually depend on.

## Replay

Because every event is persisted (not just transiently delivered), a stalled or crashed consumer can replay unprocessed events for its task on restart by querying `events WHERE task_id = ? AND created_at > last_processed_at` — sufficient replay capability without building a dedicated replay subsystem.
