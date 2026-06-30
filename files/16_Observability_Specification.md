# 16 — Observability Specification

**Applies from:** Stage 1, expanded Stage 7
**Related:** `09_Database_Design_Specification.md`, `19_Operations_Runbook.md`

---

## Logging (Stage 1)

Every agent action is written to `task_logs` (category, message, structured metadata, timestamp) — this is the primary, queryable audit trail and the first place to look when investigating any task's behavior. Application-level logs (API errors, deploy events) go to standard stdout/stderr, captured by the hosting platform's log aggregation.

## Error Tracking (Stage 1)

Sentry captures runtime exceptions across the Next.js app, the agent runtime, and background jobs, with task ID attached as context where available so an error can be traced back to the specific task/agent run that caused it.

## Metrics (Stage 6+)

Once the Agent Registry exists (`06_Agent_SDK_Specification.md`), per-agent success rate, average retry count, and average time-to-completion become queryable metrics, surfaced on the Stage 7 productivity dashboard (`15_Mission_Control_Dashboard_Specification.md`).

## Alerting

**Stage 1–6 (right-sized):** a failed or blocked task triggers a notification (Slack webhook or email) to the team — simple, immediate, sufficient for current volume. No dedicated alerting/on-call rotation tooling yet.
**Stage 7:** if concurrent epic volume makes individual notifications noisy, this evolves into the daily batch review pattern already planned (`15`) plus threshold-based alerts (e.g., "failure rate across an agent type exceeded X% in the last hour") rather than per-task pings.

## What's Deferred

A full OpenTelemetry + Prometheus + Grafana observability stack is not being stood up at Stage 1. Structured Postgres logs plus Sentry cover the actual debugging needs at this scale — one application, a handful of agents, low request volume. Revisit this once Stage 7 concurrency (10–20+ epics in flight, many agent runs per minute) makes querying `task_logs` directly too slow or unwieldy for real-time debugging; at that point, exporting metrics to a dedicated time-series system becomes worth the operational overhead it adds. Building it now would mean maintaining infrastructure with no real signal to observe yet.

## Heartbeats

Every agent run writes a periodic heartbeat (`agent_runs.status`, refreshed on an interval) so the dashboard can distinguish "actively working" from "silently stalled" — a stalled run past a timeout threshold is surfaced the same way a `blocked` task is, for human attention.
