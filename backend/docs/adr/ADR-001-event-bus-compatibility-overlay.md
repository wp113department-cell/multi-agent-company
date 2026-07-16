# ADR-001 — Event Bus Compatibility Overlay

**Status:** Accepted  
**Date:** 2026-07-16  
**Author:** Fleet OS implementation session  
**Deciders:** Project owner (approved 2026-07-16)

---

## Context

The Master Prompt v4 §6 specifies exactly 8 typed Fleet OS event types:

| Fleet OS Event | Purpose |
|---|---|
| TaskCreated | A new task entered the system |
| TaskStarted | An agent began executing a task |
| TaskCompleted | A task finished successfully |
| TaskFailed | A task failed or was blocked |
| ReviewRequested | A task output requires review |
| LessonPublished | An agent published a lesson to memory |
| HealthUpdated | An agent's health state changed |
| MemoryCreated | A new memory entry was written |

The existing `event_bus/models.py` already defines 15 production event types
(`task.created`, `task.planned`, `epic.completed`, `epic.halted`, `qa.passed`,
`qa.failed`, `review.completed`, etc.) that all current agents publish and
subscribe to. These event types drive SSE push to the frontend, cost
accounting, audit hooks, and the Redis Streams bridge.

## Decision

**Do NOT replace the existing event bus. Implement the Fleet OS typed event
protocol as a compatibility layer on top of the existing bus.**

The new component is `app/fleet/fleet_events.py`.

## Rationale

A breaking replacement would require:
1. Migrating all 70+ agents simultaneously.
2. Migrating all API subscribers (SSE, Redis Streams, cost_controller).
3. Zero rollback path if the new protocol has bugs.
4. Risk of data loss during migration window.

An overlay approach provides:
1. Zero disruption to existing agents.
2. Fleet OS agents can publish/consume typed events immediately.
3. Bidirectional mapping preserves downstream subscribers.
4. Migration is incremental: one agent at a time.
5. Full rollback: removing fleet_events.py reverts to legacy behavior.

## Implementation

### New event types (Fleet OS layer — fleet_events.py)

```
FleetEventType.TASK_CREATED
FleetEventType.TASK_STARTED
FleetEventType.TASK_COMPLETED
FleetEventType.TASK_FAILED
FleetEventType.REVIEW_REQUESTED
FleetEventType.LESSON_PUBLISHED
FleetEventType.HEALTH_UPDATED
FleetEventType.MEMORY_CREATED
```

### Preserved event types (legacy layer — event_bus/models.py, UNCHANGED)

```
task.created, task.planned, architecture.ready, subtask.assigned,
qa.passed, qa.failed, review.completed, epic.completed, task.blocked,
epic.pending_cost_approval, epic.planning_started, epic.ready_for_review,
epic.halted, epic.approved, epic.rejected
```

### Bidirectional mapping

| Legacy event_type | Fleet OS event |
|---|---|
| task.created | TaskCreated |
| task.planned | TaskStarted |
| epic.planning_started | TaskStarted |
| subtask.assigned | TaskStarted |
| epic.completed | TaskCompleted |
| epic.ready_for_review | TaskCompleted |
| qa.passed | TaskCompleted |
| task.blocked | TaskFailed |
| epic.halted | TaskFailed |
| qa.failed | TaskFailed |
| review.completed | ReviewRequested |

When Fleet OS publishes a typed event, `FleetBus.publish()` also emits the
corresponding legacy event so existing subscribers (SSE, Redis Streams, cost
accounting) continue to receive it without modification.

## Migration Rule

Do not remove any legacy event type until:
1. Every agent that publishes or subscribes to it has been migrated and verified.
2. Tests confirm both paths work.
3. A migration report is written.

## Consequences

**Positive:**
- Existing agents need zero changes.
- Fleet OS can start operating immediately.
- Rollback is trivial (remove fleet_events.py import).

**Negative:**
- Two event systems coexist temporarily (acceptable during migration).
- Some events have no direct Fleet OS equivalent; they map to the nearest type.

## Tests

`backend/tests/test_fleet_events.py` verifies:
- All 8 Fleet OS event types can be constructed and published.
- Legacy event types in CORE_EVENT_TYPES remain reachable.
- Bidirectional mapping covers all defined legacy → Fleet OS mappings.
- Publishing a Fleet OS event does not raise (even without an event loop).
