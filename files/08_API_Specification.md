# 08 — API Specification

**Applies from:** Stage 1, expanded each stage
**Related:** `09_Database_Design_Specification.md`, `15_Mission_Control_Dashboard_Specification.md`

---

## Conventions

REST over HTTPS, JSON request/response bodies. Resource-based URLs (`/tasks`, `/tasks/:id`), standard HTTP verbs and status codes (200/201 success, 400 validation error, 401/403 auth, 404 not found, 409 conflict, 500 server error). Errors return `{ error: { code, message } }`. Authenticated via Supabase Auth session for all endpoints — this is an internal tool, not a public API, so no API-key tier exists yet.

Versioning and formal rate limiting are deferred until there's an actual external consumer of these APIs (see `05`, ADR-009 reasoning applied here) — at internal scale with one frontend client, premature API versioning adds overhead without benefit. Revisit when a second consumer (e.g., a future department's dashboard) needs to call these endpoints.

## Stage 1 — Task Queue API

| Method | Path | Purpose |
|---|---|---|
| POST | `/tasks` | Create a new development task |
| GET | `/tasks` | List tasks (filterable by status, project) |
| GET | `/tasks/:id` | Get a single task with its full log timeline |
| PATCH | `/tasks/:id` | Update task fields (status, assigned_agent, etc.) |
| POST | `/tasks/:id/logs` | Append a log entry |

**POST /tasks** request body:
```json
{ "title": "string", "description": "string", "priority": "low|medium|high", "project": "string" }
```
Response: `201` with the created task object, `status: "pending"`.

**GET /tasks/:id** response includes the task record plus an array of `task_logs` ordered by `created_at`.

## Stage 2 — Patch Review

| Method | Path | Purpose |
|---|---|---|
| GET | `/tasks/:id/diff` | Retrieve the proposed diff for a task |
| POST | `/tasks/:id/approve` | Human approves the proposed change |
| POST | `/tasks/:id/reject` | Human rejects, optionally with feedback that re-triggers the agent |

## Stage 4 — Artifacts

| Method | Path | Purpose |
|---|---|---|
| GET | `/tasks/:id/artifacts` | List all versioned artifacts produced for a task (plan, patch, test results, review findings) |
| GET | `/artifacts/:id` | Retrieve a specific artifact's content |

## Stage 5 — Epics & Approval

| Method | Path | Purpose |
|---|---|---|
| POST | `/epics` | Create an epic (high-level goal), triggers PM → Architect → Decomposer |
| GET | `/epics/:id` | Full epic detail: subtasks, statuses, cost estimate vs. actual |
| POST | `/epics/:id/approve` | Single approval action covering the whole epic |

## Stage 6 — Agent Registry

| Method | Path | Purpose |
|---|---|---|
| GET | `/agents` | List all registered agents with capabilities and live metrics |
| GET | `/agents/:id/metrics` | Success rate, average retries, recent run history for one agent |

## Stage 7 — Executive Entry Point

| Method | Path | Purpose |
|---|---|---|
| POST | `/goals` | Plain-language goal submitted to the Executive Agent; may spawn one or more epics |
| GET | `/goals/:id` | Plain-language progress summary |

## Pagination

List endpoints (`GET /tasks`, `GET /agents`) use cursor-based pagination (`?cursor=<id>&limit=20`, default limit 20, max 100) — sufficient for internal dashboard scale; revisit only if list sizes genuinely require offset-based or keyset optimization later.
