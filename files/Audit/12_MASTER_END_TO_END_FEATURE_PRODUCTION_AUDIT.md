# 12_MASTER_END_TO_END_FEATURE_PRODUCTION_AUDIT.md

# Gridiron Developer Department
## Master End-to-End Feature Reality / Wiring / Production Audit

**Audit type:** Full feature reality + implementation + integration + UI wiring + runtime + production verification  
**Purpose:** Verify that every feature described, implemented, exposed, or reachable in the project is actually usable in production.  
**Primary rule:** Never mark a feature complete because code exists. Prove the complete execution path.  
**Audit mode:** Evidence-first, zero-assumption, zero-hallucination, repair-and-retest  
**Owner:** Human + Claude Code  
**Scope:** Entire repository — backend, frontend, database, agents, tools, orchestration, workers, infrastructure, configuration, tests, documentation, runtime integrations, external services  
**Status:** START HERE

---

# 0. NON-NEGOTIABLE MISSION

This audit is NOT another architecture audit.

This audit answers one question for every feature:

> **Can a real user use this feature from the actual product UI/API and does the complete path work correctly in a real environment?**

A feature is not production-ready merely because:

- a Python function exists
- an API route exists
- a React component exists
- a database table exists
- a test exists
- documentation says it works
- an agent prompt mentions it
- a tool is registered
- an endpoint returns HTTP 200
- a mock passes
- a unit test passes
- a feature flag exists
- a TODO was removed
- an old audit marked it YES

The feature must be traced and verified from the actual entry point through every required layer.

---

# 1. CORE AUDIT CONTRACT

Claude Code MUST follow these rules for the entire audit.

## 1.1 Evidence before conclusion

Never say:

- "this works"
- "production ready"
- "connected"
- "wired"
- "tested"
- "secure"
- "complete"

unless there is concrete evidence.

Every YES result must contain evidence.

Minimum evidence should identify:

- file
- symbol/function/component/route
- line or exact location when available
- command used
- test or runtime result
- relevant HTTP response / browser result / database result
- dependency or connection path
- timestamp where useful

---

## 1.2 Never trust project documentation as proof

Documentation is a source of intended behavior.

Source code and runtime behavior are sources of truth.

Existing audit files are evidence to inspect, NOT proof to blindly accept.

If documentation says:

`Feature X is production-ready`

but the UI cannot reach it:

`Feature X = FAIL`

If backend implementation exists but frontend does not expose it:

`Feature X = PARTIAL / UNWIRED`

If frontend calls an endpoint that does not exist:

`Feature X = FAIL`

If both exist but the response contract is incompatible:

`Feature X = FAIL`

If tests pass only because external integrations are mocked:

`Feature X = INTEGRATION UNVERIFIED`

---

# 2. ZERO-HALLUCINATION POLICY

## 2.1 Allowed evidence

Accept evidence from:

1. Actual source code inspection
2. Actual imports and call sites
3. Actual API route registration
4. Actual frontend API client usage
5. Actual database schema/migrations
6. Actual running application
7. Actual browser interaction
8. Actual Playwright results
9. Actual CLI command results
10. Actual test execution
11. Actual HTTP requests
12. Actual database queries
13. Actual logs/traces/metrics
14. Actual configuration loaded by the application
15. Actual external-service response
16. Git history when verifying implementation history
17. Build artifacts when verifying compiled output

## 2.2 Not acceptable as standalone proof

Do NOT accept:

- comments
- README claims
- TODO removal
- function name
- class name
- route declaration alone
- TypeScript interface alone
- Pydantic model alone
- mock-only test
- snapshot-only test
- screenshot without successful interaction evidence
- "looks correct"
- LLM reasoning
- agent claim
- previous audit claim
- code similarity
- generated documentation

---

# 3. NO ASSUMPTIONS

When evidence is missing:

`UNKNOWN / UNVERIFIED`

NOT:

`YES`

Claude Code must never fill an evidence gap with an assumption.

Use:

> "I could not verify this behavior from available evidence."

Do not invent expected API responses, database state, UI behavior, environment variables, credentials, service availability, or successful execution.

---

# 4. NO HARD-CODED AUDIT PASS CONDITIONS

Do not make the application appear compliant by adding hardcoded audit results.

Do NOT:

- hardcode `production_ready = true`
- hardcode feature status
- hardcode expected API responses
- hardcode fake users
- hardcode fake database records
- hardcode test pass values
- bypass authorization
- bypass validation
- bypass business logic
- add fake endpoints solely for audit
- add fake UI solely to make a feature appear connected

Audit infrastructure must verify the real implementation.

---

# 5. NO REGEX AS A SUBSTITUTE FOR REAL SOFTWARE ANALYSIS

For core feature verification, do not use regex-based source parsing as the primary truth mechanism.

Prefer:

- Python AST
- Tree-sitter
- TypeScript compiler APIs
- Next.js route analysis
- OpenAPI inspection
- import graph analysis
- call graph analysis
- SQL/database metadata
- runtime tracing
- browser DOM inspection
- Playwright
- actual HTTP requests
- actual process inspection
- actual test execution

Regex may be used only for narrow text searches where semantics are irrelevant and the result is manually verified.

Never use regex to claim:

> "Feature is wired"

---

# 6. PROTECT WORKING FEATURES

This audit must never break a working feature while repairing another feature.

Before modifying a feature:

1. Establish baseline.
2. Run relevant existing tests.
3. Record current behavior.
4. Identify dependency surface.
5. Create isolated worktree/branch when appropriate.
6. Make the smallest safe change.
7. Run targeted tests.
8. Run integration tests.
9. Run affected UI tests.
10. Run regression tests.
11. Compare before/after behavior.

If an unrelated feature regresses:

`STOP`

Do not continue stacking changes.

Investigate and resolve the regression first.

---

# 7. HUMAN-CONFLICT GATE

Claude Code may fix clear defects.

Claude Code MUST ask the human before making a change when:

- two valid architectural choices conflict
- intended business behavior is ambiguous
- changing behavior could break an existing contract
- deleting an existing feature may be required
- changing security policy changes product behavior
- changing database semantics could cause data loss
- migration could be destructive
- external billing/cost behavior changes
- production infrastructure behavior is unclear
- multi-tenant behavior is unclear
- compliance requirements are ambiguous
- an external API contract is uncertain
- a feature is intentionally disabled but its intended state is unknown
- two project documents contradict actual requirements
- fixing one feature requires changing another feature's intended behavior

Ask a concise human clarification question.

Do not guess.

---

# 8. FEATURE STATUS MODEL

Use exactly these statuses.

| Status | Meaning |
|---|---|
| DISCOVERED | Feature found but not yet fully verified |
| VERIFIED | Evidence confirms implementation and expected behavior |
| PARTIAL | Some layers work but complete feature path is incomplete |
| UNWIRED | Implementation exists but required connection is missing |
| BROKEN | Feature path exists but runtime behavior fails |
| BLOCKED | Verification cannot continue because required external/human dependency is unavailable |
| CONFLICT | Requirements or existing behavior conflict and require human decision |
| NOT_APPLICABLE | Feature is proven outside current product scope |
| DEFERRED | Human explicitly chose to postpone it |
| PRODUCTION_READY | All required production gates pass |
| REGRESSION | Previously working behavior broke during audit repair |

Never use "probably working".

---

# 9. WHAT COUNTS AS PRODUCTION-READY

A feature can receive `PRODUCTION_READY` only when ALL applicable gates pass.

## Gate A — Requirement

- Intended behavior is identifiable.
- Inputs and outputs are defined.
- Acceptance criteria are concrete.
- Scope is known.

## Gate B — Implementation

- Real implementation exists.
- No dead implementation is being mistaken for live behavior.
- Required dependencies exist.

## Gate C — Backend

- Route/service/worker is registered.
- Authentication is correct.
- Authorization is correct.
- Validation is correct.
- Business logic executes.
- Errors are handled.
- Persistence behavior is correct where applicable.

## Gate D — Database

Where applicable:

- schema exists
- migration exists
- indexes/constraints are correct
- transactions are correct
- rollback behavior is understood
- data lifecycle is correct
- concurrent behavior is safe

## Gate E — Frontend

Where applicable:

- UI exposes the feature
- UI calls the correct API/service
- request schema matches backend
- response schema matches frontend expectations
- loading state works
- success state works
- failure state works
- empty state works
- retry behavior works
- permission behavior works
- stale data behavior works
- navigation/deep links work

## Gate F — Runtime Integration

- Real application starts.
- Real dependency path executes.
- Real API request succeeds.
- Real UI interaction succeeds.
- External services are verified when required.

## Gate G — Tests

- unit tests
- integration tests
- API tests
- frontend tests
- E2E tests
- regression tests

Only applicable tests are required, but applicability must be proven.

## Gate H — Security

- authentication
- authorization
- input validation
- secret handling
- path safety
- command safety
- injection resistance
- tenant isolation where applicable
- audit logging where applicable

## Gate I — Reliability

- timeout
- retry
- cancellation
- duplicate request behavior
- failure recovery
- partial failure handling
- restart behavior
- cleanup

## Gate J — Observability

- meaningful logs
- error identity
- trace/correlation ID where applicable
- metrics where applicable
- user-visible errors where appropriate

## Gate K — Performance

- no obvious N+1 behavior
- bounded resource use
- reasonable latency
- no leaked processes
- no leaked connections
- no uncontrolled queue growth

## Gate L — Production Configuration

- required environment variables documented
- required environment variables validated
- production configuration differs correctly from development
- no development-only bypass
- no localhost dependency accidentally required
- no debug mode
- no test credentials

## Gate M — Regression

Existing working features remain working.

---

# 10. FEATURE DISCOVERY — DO THIS BEFORE FIXING ANYTHING

Claude Code MUST first build a complete feature inventory.

Do not start by reading only the README.

Inspect the entire repository.

## 10.1 Discover frontend features

Inspect:

- app routes
- pages
- layouts
- route handlers
- components
- hooks
- context/providers
- stores
- forms
- dialogs
- modals
- navigation
- command palettes
- keyboard shortcuts
- uploads
- downloads
- streaming UI
- terminals
- dashboards
- settings
- authentication pages
- error pages
- loading pages
- not-found pages

For each user-visible capability create a feature record.

---

# 11. FRONTEND FEATURE INVENTORY FOR GRIDIRON

At minimum verify the following documented surfaces, then discover anything else actually present.

## 11.1 Dashboard

Expected surface:

`/`

Verify:

- active tasks
- system health
- fleet status
- recent activity
- loading
- errors
- refresh
- navigation
- permissions
- real data

## 11.2 Task Management

Expected:

`/tasks`

Verify:

- task list
- task creation
- repository selection
- execution mode
- task detail
- task state
- task logs
- task cancellation
- task pause/resume where supported
- task images
- PR information
- error states
- refresh/polling

## 11.3 NewTaskForm

Verify:

- goal input
- repository selection
- full/simple mode
- image attachment
- drag/drop
- validation
- upload
- preview
- remove attachment
- submit
- backend request
- task creation
- navigation after creation

## 11.4 Pipeline Visualizer

Expected:

`PipelineView.tsx`

Verify:

- PM
- Architect
- Decomposer
- interrupt
- Manager
- subtasks
- status transitions
- real-time state
- error state
- reconnect behavior

## 11.5 Approval Center

Expected:

`/approvals`

Verify:

- pending approvals
- plan approval
- plan edit
- remove step
- reject
- approve
- diff review
- git push approval
- prompt approval where applicable
- stale approval behavior
- duplicate approval prevention

## 11.6 Console / Terminal

Expected:

`/console`

Verify:

- terminal creation
- PTY connection
- output
- input
- resize
- process lifecycle
- exit code
- background process
- termination
- reconnect
- timeout
- cleanup
- unauthorized access prevention

## 11.7 Fleet Dashboard

Expected:

`/fleet`

Verify:

- agent list
- capabilities
- model mappings
- metrics
- enhancement requests
- proposal details
- evidence
- approve
- reject
- apply
- status changes
- SSE updates
- rollback information

## 11.8 Repository Chat

Expected:

`/chat`

Verify:

- chat creation
- message send
- streaming
- repository context
- search
- AST/code understanding
- tool calls
- error handling
- cancellation
- reconnect
- conversation persistence

## 11.9 Stream Feed

Expected:

`/stream`

Verify:

- SSE connection
- event ordering
- event parsing
- reconnect
- duplicate event handling
- terminal events
- agent events
- tool events
- file modification events
- errors
- authorization

## 11.10 Epics / Goals

Verify all actual routes:

- create
- read
- update
- delete where supported
- status
- task association
- navigation
- persistence

## 11.11 Repository Explorer

Verify:

- repository list
- repository selection
- files
- directories
- worktrees
- file content
- search
- symbol information
- permissions
- large-file handling

## 11.12 Cost / Metrics

Verify:

- cost calculations
- token counts
- latency
- agent metrics
- filters
- aggregation
- time ranges
- empty state
- error state

## 11.13 Settings

Verify:

- credentials
- secret storage
- configuration
- validation
- permissions
- masking
- save
- retrieval
- update
- delete where supported

## 11.14 Authentication

Verify:

- login
- logout
- session
- expired session
- invalid credentials
- password hashing
- authorization
- protected routes
- protected API endpoints
- direct URL access

---

# 12. BACKEND FEATURE DISCOVERY

Discover every:

- FastAPI router
- endpoint
- dependency
- service
- background task
- queue consumer
- worker
- WebSocket/SSE endpoint
- terminal endpoint
- file operation
- agent execution endpoint
- external integration
- database repository method
- scheduled loop
- event handler

Build an endpoint inventory.

For every endpoint record:

```text
Feature
HTTP method
Path
Router file
Handler
Authentication
Authorization
Request schema
Response schema
Service function
Database operations
External services
Frontend callers
Tests
Runtime proof
Status
```

---

# 13. API ↔ FRONTEND WIRING AUDIT

This is one of the most important sections.

For every backend endpoint:

1. Find all frontend callers.
2. Identify the actual client/hook/function.
3. Verify request payload.
4. Verify response parsing.
5. Verify error handling.
6. Verify authentication headers/cookies.
7. Verify loading state.
8. Verify success state.
9. Verify failure state.
10. Verify UI action that triggers the request.
11. Execute it in the running application.

Classify:

- `BACKEND + FRONTEND + RUNTIME = VERIFIED`
- `BACKEND ONLY = UNWIRED`
- `FRONTEND ONLY = BROKEN/UNWIRED`
- `MISMATCH = BROKEN`
- `NO CALLER = POSSIBLY DEAD API`
- `MOCK ONLY = UNVERIFIED`
- `RUNTIME FAILURE = BROKEN`

Do not assume every API must have a frontend caller. Some internal APIs are intentionally backend-only. Prove their intended consumer.

---

# 14. FRONTEND → BACKEND → DATABASE TRACE

For every data-backed feature trace:

```text
UI action
  ↓
React component
  ↓
hook / state / client
  ↓
HTTP request
  ↓
FastAPI route
  ↓
dependency/auth
  ↓
service/business logic
  ↓
repository/DAO
  ↓
SQLAlchemy model
  ↓
PostgreSQL
  ↓
response schema
  ↓
HTTP response
  ↓
frontend parsing
  ↓
state update
  ↓
UI rendering
```

Every broken link must be recorded.

---

# 15. DATABASE REALITY AUDIT

For every model/table:

Verify:

- model is imported
- table is actually created
- migration creates it
- migration is included in migration chain
- relationships are valid
- foreign keys are valid
- constraints are valid
- indexes exist where needed
- queries actually use it
- writes actually occur
- reads actually occur
- orphan records are handled
- deletion semantics are correct
- transaction boundaries are correct
- concurrent access is safe

A model existing in `models.py` is NOT proof that the feature uses it.

---

# 16. MIGRATION AUDIT

Verify:

- migration chain is linear/valid
- latest migration applies cleanly
- fresh database creation works
- upgrade from realistic previous state works
- downgrade behavior is understood where supported
- migrations do not silently destroy required data
- indexes/constraints are created
- application code matches current schema

Run:

- migration validation
- fresh DB test
- upgrade test
- integration test

---

# 17. AGENT FEATURE AUDIT

Because Gridiron contains a large agent fleet, every agent must be verified as an actual usable capability.

For every agent:

```text
Agent name
Agent source file
Prompt/role definition
Registration
Capability registry
Tool permissions
Model routing
Invocation path
API exposure
Orchestration exposure
Delegation exposure
Tests
Actual execution
Output validation
Failure behavior
Status
Evidence
```

Do not count an agent merely because a `.py` file exists.

Verify that:

- it can be selected when appropriate
- its contract is valid
- its tools are actually available
- forbidden tools are actually unavailable
- its model mapping resolves
- it can execute
- failures are handled
- result enters the intended pipeline
- UI exposes the result when applicable

---

# 18. TOOL AUDIT

For every operational tool:

Verify:

- registration
- schema
- implementation
- permissions
- agent access
- invocation
- output
- error behavior
- timeout
- security
- tests
- actual execution

Specially verify tools that are described as:

- filesystem
- git
- terminal
- AST
- search
- web
- browser
- database
- memory
- sandbox
- deployment
- credential
- PR
- testing
- verification

A tool being importable is not proof that an agent can actually use it.

---

# 19. ORCHESTRATION AUDIT

Verify the real path:

```text
User Goal
↓
Task creation
↓
PM
↓
Architect
↓
Decomposer
↓
Human interrupt
↓
Manager
↓
Dispatcher
↓
Subtask dependency ordering
↓
Agent selection
↓
Worktree
↓
File locks
↓
Developer
↓
QA
↓
Verification
↓
Reviewer
↓
Failure recovery
↓
Documentation
↓
Commit
↓
Human sign-off
↓
PR
```

For every transition verify:

- state exists
- transition is reachable
- transition occurs
- invalid transition is rejected
- failure transition works
- resume works
- cancellation works
- retry works
- persistence works after restart

---

# 20. GRAPH-ENFORCED VERIFICATION AUDIT

Do not trust agent claims.

Verify the actual implementation of verification state.

For code-changing operations:

1. tests must become unverified after a relevant modification
2. test verification must require actual test execution
3. exit code must be observed
4. graph state must use verified execution result
5. agent text must not override actual verification
6. submit-result logic must preserve verified truth

Test deliberately:

- agent claims tests passed without running tests
- tests actually fail
- code changes after passing tests
- test command itself fails
- test command times out

The platform must not incorrectly report success.

---

# 21. FAILURE RECOVERY AUDIT

Verify every actual rung implemented by the project.

For each rung:

- trigger condition
- state transition
- retry
- context propagation
- budget behavior
- logging
- next rung
- human escalation
- rollback
- cleanup

Verify that failure recovery does not hide failures.

---

# 22. TERMINAL / PTY AUDIT

Verify:

- PTY creation
- shell process
- correct worktree
- input
- output
- resize
- process exit
- exit code
- background process
- process registry
- cleanup
- timeout
- hung process detection
- reconnect
- unauthorized terminal access
- cross-task isolation

Test real commands, not mocks only.

---

# 23. SANDBOX AUDIT

Verify:

- sandbox is actually used
- high-risk commands do not run directly on host
- worktree mount is correct
- resource limits are enforced
- non-root behavior
- environment isolation
- credentials are not exposed
- Docker-unavailable behavior fails closed where required
- container cleanup occurs

Do not accept configuration declarations without runtime proof.

---

# 24. MEMORY AUDIT

Verify each memory tier that actually exists.

For every memory mechanism:

- write
- read
- scope
- retrieval
- update
- expiration/aging where applicable
- conflict behavior
- persistence
- isolation
- failure behavior

Verify project/repository scoping prevents cross-project contamination.

---

# 25. SECURITY FEATURE AUDIT

Security must be tested as behavior, not merely source code.

Verify:

### Authentication

- valid login
- invalid login
- expired session
- logout
- protected route
- protected API

### Authorization

Test multiple roles where applicable.

Attempt:

- allowed action
- forbidden action
- direct API call
- direct UI route
- object belonging to another user/project

### Secrets

Verify:

- encryption at rest
- no secret in logs
- no secret in SSE
- no secret in error message
- no secret in database plaintext where prohibited
- no secret in source
- production key requirement

### Injection

Verify protections for:

- SQL
- shell
- path traversal
- prompt/tool boundaries
- XSS
- unsafe file handling

Do not rely on regex-only secret or injection detection.

---

# 26. FILESYSTEM / REPOSITORY SAFETY AUDIT

Verify:

- path validation
- worktree containment
- symlink handling
- traversal protection
- protected file rules
- file size limits
- binary handling
- concurrent writes
- cleanup

Attempt realistic boundary cases.

---

# 27. EXTERNAL INTEGRATION AUDIT

For every external service:

```text
Provider
Purpose
Configuration
Authentication
Client
Call site
Timeout
Retry
Rate-limit behavior
Error handling
Fallback
Frontend exposure
Tests
Real runtime proof
```

Examples include:

- LLM providers
- GitHub
- Anthropic
- Groq
- OpenAI
- Voyage AI
- PostgreSQL
- Redis
- Docker
- Sentry
- OpenTelemetry
- external APIs

Do not mark external integration verified if only a mocked client was tested.

If credentials are unavailable:

`BLOCKED — REAL INTEGRATION CREDENTIAL REQUIRED`

Do not fabricate credentials.

---

# 28. REAL-TIME / SSE AUDIT

For every SSE stream:

Verify:

- connection
- authentication
- authorization
- event schema
- event generation
- event delivery
- ordering
- reconnect
- duplicate events
- missed events
- disconnect cleanup
- backpressure
- error event
- frontend event parser
- UI state update

Test an actual live stream.

---

# 29. ERROR HANDLING AUDIT

Every feature must have a defined behavior for:

- invalid input
- unauthorized request
- forbidden request
- not found
- duplicate request
- dependency unavailable
- timeout
- malformed upstream response
- database error
- process failure
- network failure
- stale UI
- server restart

Verify that the UI does not silently pretend success.

---

# 30. FRONTEND STATE AUDIT

For every interactive feature verify:

### Loading

User sees correct loading state.

### Success

User sees actual result.

### Empty

Empty data is distinguishable from failure.

### Error

Actionable error is shown.

### Retry

Retry actually retries the failed operation.

### Optimistic updates

If used:

- rollback on failure
- no duplicate state
- server truth eventually wins

### Refresh

Refresh does not corrupt state.

### Navigation

Deep linking works.

### Browser refresh

State restoration works where required.

---

# 31. FORM AUDIT

Every form:

- required fields
- optional fields
- validation
- type validation
- server-side validation
- client/server agreement
- disabled submit
- loading
- duplicate submission
- failure
- success
- reset
- accessibility
- keyboard navigation

Never rely only on client-side validation.

---

# 32. ACCESSIBILITY AUDIT

For user-facing features verify:

- semantic controls
- labels
- keyboard navigation
- focus behavior
- dialogs
- error announcements
- form labels
- button names
- sufficient interaction target
- screen-reader semantics
- no keyboard trap

Use automated accessibility tooling plus manual verification.

---

# 33. RESPONSIVE / BROWSER AUDIT

For major UI features test supported environments defined by the project.

At minimum investigate:

- desktop Chromium
- supported Firefox
- supported WebKit/Safari-equivalent
- narrow viewport
- normal desktop viewport

Verify no critical feature is usable only at one viewport.

---

# 34. PERFORMANCE AUDIT PER FEATURE

For every high-traffic or expensive feature check:

- request latency
- database query count
- N+1 behavior
- payload size
- frontend rendering cost
- repeated requests
- polling interval
- SSE behavior
- memory growth
- process count
- connection leaks

Use actual measurements.

Do not invent thresholds.

If the project has no SLO, report the measurement and ask the human to define a target when necessary.

---

# 35. CONCURRENCY AUDIT

For features that can run concurrently:

Test:

- two users
- two tasks
- two subtasks
- duplicate clicks
- concurrent writes
- same-file access
- same-record updates
- task cancellation during execution
- restart during execution

Verify:

- locking
- isolation
- idempotency
- race protection
- consistent final state

---

# 36. IDEMPOTENCY AUDIT

For actions that may be retried:

- create task
- approve
- reject
- commit
- push
- start process
- stop process
- create worktree
- write database record
- submit enhancement
- apply enhancement

Verify repeated requests do not produce unintended duplicate effects.

---

# 37. CANCELLATION / PAUSE / RESUME AUDIT

Where supported, verify:

- pause
- stop
- cancel
- resume
- restart
- stale state
- process cleanup
- DB state
- UI state
- agent state
- terminal state

A UI button that changes a DB flag without stopping actual work is not a working cancellation feature.

---

# 38. BACKGROUND WORKER AUDIT

For every background process:

Verify:

- startup
- registration
- queue
- task pickup
- processing
- failure
- retry
- dead-letter behavior
- shutdown
- restart
- duplicate processing
- observability

---

# 39. CONFIGURATION AUDIT

Discover all configuration sources.

Verify:

- environment variables
- config files
- defaults
- production overrides
- required/optional status
- validation
- secret handling
- unused variables
- undocumented variables
- development-only defaults
- accidental localhost values

A configuration variable existing in `.env.example` is not proof that code actually reads it.

A variable read in code but absent from deployment documentation is a production risk.

---

# 40. BUILD AUDIT

Run the real builds.

Backend:

- Python syntax/import checks
- type checks where configured
- lint
- tests
- package/build validation

Frontend:

- TypeScript
- lint
- build
- tests
- route compilation
- production start

Infrastructure:

- Docker build
- compose validation
- migration validation
- startup validation

Record actual exit codes.

---

# 41. PRODUCTION STARTUP AUDIT

Start the project using the real production-like procedure.

Verify:

- database
- migrations
- backend
- frontend
- workers
- Redis where applicable
- Docker dependencies
- health checks
- readiness
- authentication
- actual browser access

Do not declare production-ready if only development mode was tested.

---

# 42. CLEAN ENVIRONMENT AUDIT

Test from a clean environment.

Do not depend on:

- developer machine state
- undocumented files
- stale database
- manually created folders
- hidden credentials
- cached dependencies
- manually started processes

Document every prerequisite.

---

# 43. CLEAN DATABASE AUDIT

At least one clean database test must verify:

```text
empty database
↓
migration
↓
application startup
↓
user setup
↓
feature execution
↓
database writes
↓
database reads
↓
restart
↓
data still correct
```

---

# 44. DATA INTEGRITY AUDIT

For each important feature verify:

- create
- read
- update
- delete where applicable
- relationships
- transaction consistency
- duplicate behavior
- invalid references
- restart persistence

---

# 45. TEST QUALITY AUDIT

Do not count test quantity.

For every important feature determine:

- does the test exercise real behavior?
- is the important dependency mocked?
- is the assertion meaningful?
- can the test pass while the feature is broken?
- is there integration coverage?
- is there E2E coverage where UI matters?

A feature with 100 shallow tests can still be broken.

---

# 46. MOCK / STUB DETECTION

Identify:

- mock API clients
- fake repositories
- fake database
- fake LLM
- fake SSE
- fake terminal
- fake browser
- fake authentication

Determine which claims rely on mocks.

Clearly label:

`MOCK VERIFIED`

versus:

`REAL INTEGRATION VERIFIED`

Never merge these statuses.

---

# 47. DEAD FEATURE / DEAD CODE AUDIT

Discover:

- unused routes
- unused components
- unused API clients
- unreferenced services
- unregistered agents
- unregistered tools
- unreachable branches
- obsolete feature flags
- abandoned implementations

Do not delete automatically if intent is uncertain.

Ask human if removal could change behavior.

---

# 48. FEATURE FLAG AUDIT

For every feature flag:

- owner
- default
- enabled environments
- consumer
- backend behavior
- frontend behavior
- stale flag detection
- removal plan

Verify both enabled and disabled states where relevant.

---

# 49. API CONTRACT AUDIT

Compare:

```text
Frontend request
↔
OpenAPI/schema
↔
FastAPI handler
↔
Pydantic validation
↔
Service
↔
Database
↔
Response schema
↔
Frontend response parser
```

Find:

- missing fields
- renamed fields
- nullable mismatch
- enum mismatch
- date/time mismatch
- numeric/string mismatch
- error shape mismatch
- pagination mismatch

---

# 50. TIME / DATE / TIMEZONE AUDIT

For time-dependent features verify:

- timezone source
- UTC/storage behavior
- display timezone
- daylight-saving behavior where relevant
- ordering
- expiration
- timeout
- token/session expiry

Do not infer timezone behavior from one successful local test.

---

# 51. FILE UPLOAD / DOWNLOAD AUDIT

Where applicable:

Verify:

- size limit
- type validation
- filename handling
- path safety
- storage
- database metadata
- retrieval
- permissions
- deletion
- malformed file
- large file
- duplicate upload
- download integrity

---

# 52. STREAMING / TOKEN OUTPUT AUDIT

For streaming LLM/UI features verify:

- stream starts
- chunks arrive
- chunks are ordered
- partial output renders
- completion event arrives
- error event arrives
- cancellation works
- reconnect behavior
- final persisted response matches displayed response

---

# 53. LLM FEATURE AUDIT

For every LLM-powered feature verify:

- model routing
- model configuration
- credentials
- prompt loading
- prompt version
- tool availability
- context assembly
- token budget
- timeout
- retry
- structured output validation
- refusal/error behavior
- result persistence
- verification

Never mark an LLM feature production-ready merely because the model API returns text.

---

# 54. LLM STRUCTURED OUTPUT AUDIT

Where structured output is required:

Verify:

- schema
- actual model output
- parser
- invalid output handling
- retry
- refusal
- partial output
- extra fields
- missing fields

Do not use fragile text/regex parsing where a schema/parser/structured API is appropriate.

---

# 55. GIT FEATURE AUDIT

Verify:

- repository discovery
- clone/open
- branch creation
- worktree creation
- file changes
- status
- diff
- commit
- push
- PR creation
- approval gates
- rollback
- cleanup

Test failures deliberately.

Do not push to real production repositories without required human approval.

---

# 56. PULL REQUEST AUDIT

Verify:

- branch exists
- diff is correct
- commit is correct
- PR metadata is correct
- PR URL persists
- approval state is correct
- duplicate PR behavior
- failed push behavior
- authentication
- rollback path

---

# 57. OBSERVABILITY AUDIT

Verify:

- structured logs
- correlation/trace IDs
- task IDs
- agent run IDs
- error identity
- metrics
- latency
- token usage
- cost
- queue state
- process state
- database errors

A log saying "failed" without enough context is insufficient for production operations.

---

# 58. HEALTH CHECK AUDIT

Every actual health/readiness endpoint must be tested.

Differentiate:

- process alive
- database connected
- Redis connected
- required dependency available
- service ready to accept traffic

Do not make health checks report healthy when critical dependencies are unavailable.

---

# 59. ERROR BOUNDARY AUDIT

Frontend:

- route errors
- component errors
- failed API
- streaming errors
- unexpected response

Backend:

- validation errors
- application errors
- database errors
- external service errors
- unexpected exceptions

Verify no sensitive internals leak to users.

---

# 60. AUDIT EXECUTION ORDER

Claude Code MUST use this order.

## Phase 1 — Discovery

Do not modify code.

Create:

`AUDIT_FEATURE_INVENTORY.md`

Collect every discovered feature.

## Phase 2 — Dependency Mapping

Create:

`AUDIT_FEATURE_WIRING_MATRIX.md`

Map:

```text
Feature
→ UI
→ frontend client
→ API
→ service
→ DB
→ external dependency
→ tests
→ runtime proof
```

## Phase 3 — Baseline

Run:

- build
- tests
- lint
- type checks
- startup
- health checks

Record failures.

## Phase 4 — Feature Verification

Process one feature at a time.

## Phase 5 — Repair

If a feature fails:

1. Reproduce.
2. Identify root cause.
3. Confirm intended behavior.
4. Fix.
5. Test.
6. Integration test.
7. E2E test.
8. Regression test.
9. Re-run feature audit.

## Phase 6 — Production Gate

Only after all applicable features pass.

---

# 61. FEATURE-BY-FEATURE LOOP

This loop is mandatory.

```text
DISCOVER FEATURE
      ↓
DEFINE EXPECTED BEHAVIOR
      ↓
TRACE COMPLETE WIRING
      ↓
RUN STATIC VERIFICATION
      ↓
RUN UNIT TEST
      ↓
RUN INTEGRATION TEST
      ↓
RUN REAL API TEST
      ↓
RUN REAL UI / E2E TEST
      ↓
CHECK SECURITY
      ↓
CHECK ERROR PATHS
      ↓
CHECK PERFORMANCE
      ↓
CHECK REGRESSION
      ↓
PASS?
 ┌────┴────┐
YES        NO
 ↓          ↓
PROD       ROOT CAUSE
READY       ↓
            FIX
             ↓
          RETEST
             ↓
          REGRESSION
             ↓
         LOOP AGAIN
```

Do not move to the next feature until the current feature reaches:

`PRODUCTION_READY`

or a human-approved:

`BLOCKED / DEFERRED / NOT_APPLICABLE`

---

# 62. FEATURE ACCEPTANCE RECORD

Create one record for every feature.

Use:

```markdown
## FEATURE: <name>

ID: F-XXXX
Category:
Priority:
User-facing: YES/NO
Source of requirement:
Expected behavior:

### Implementation
Backend:
Frontend:
Database:
External dependencies:

### Wiring
UI →
Frontend →
API →
Service →
Database →
External service →
Response →
UI:

### Evidence
Source evidence:
Runtime evidence:
Test evidence:
Browser evidence:
Database evidence:

### Verification
[ ] Requirement verified
[ ] Implementation verified
[ ] Backend verified
[ ] Frontend verified
[ ] API contract verified
[ ] Database verified
[ ] Integration verified
[ ] E2E verified
[ ] Security verified
[ ] Error paths verified
[ ] Performance measured
[ ] Observability verified
[ ] Regression verified

### Result
Status:
Root cause if failed:
Changes made:
Files changed:
Tests run:
Commands:
Evidence:

### Final gate
PRODUCTION_READY: YES/NO
```

---

# 63. PROOF STANDARD

A YES should look like:

```text
F-0021 Task Creation

UI:
apps/web/.../NewTaskForm.tsx

API:
POST /api/tasks

Runtime:
HTTP 201

Database:
DevTask row created with task_id=...

Frontend:
Navigation to /tasks/<id> confirmed.

E2E:
Playwright test passed.

Regression:
Existing task list test passed.

Evidence:
<command/result/reference>

STATUS: PRODUCTION_READY
```

A weak result like:

```text
Task creation seems implemented.
```

is NOT acceptable.

---

# 64. FAILED FEATURE STANDARD

A failure must explain:

```text
Feature:
Expected:
Actual:
Reproduction:
Root cause:
Affected layers:
Risk:
Proposed fix:
Files likely affected:
Regression risk:
Human decision required: YES/NO
```

---

# 65. REPAIR STANDARD

Before changing code:

```text
Current behavior:
Current tests:
Affected files:
Affected features:
Dependency graph:
Expected behavior:
```

After changing code:

```text
Changed:
Why:
Unit result:
Integration result:
E2E result:
Regression result:
Security result:
Performance result:
```

---

# 66. REGRESSION GATE

Every repair must run:

1. feature-specific tests
2. directly dependent tests
3. API tests
4. frontend tests
5. relevant E2E
6. broader regression suite

If regression occurs:

`STATUS = REGRESSION`

Stop the feature sequence and repair the regression.

---

# 67. CHANGE MINIMIZATION

Do not refactor unrelated code while fixing a feature.

Avoid:

- broad rewrites
- unnecessary renaming
- unrelated formatting
- dependency upgrades without need
- architecture changes without need
- replacing working implementations merely for style

Prefer the smallest change that correctly fixes the verified defect.

---

# 68. NO "FIX" WITHOUT REPRODUCTION

When possible:

1. reproduce failure
2. capture evidence
3. fix
4. prove original failure is gone
5. prove adjacent behavior remains correct

If failure cannot be reproduced:

`UNVERIFIED`

Do not claim a fix based only on code inspection.

---

# 69. HUMAN APPROVAL CHECKPOINTS

Ask the human before:

- destructive migration
- deleting production data
- deleting feature
- changing public API contract
- changing authentication behavior
- changing authorization policy
- changing external billing behavior
- changing deployment architecture
- changing intended product behavior
- resolving conflicting requirements
- bypassing an existing safety gate

---

# 70. AUDIT ARTIFACTS TO PRODUCE

The audit must produce:

```text
Audit/
├── 12_MASTER_END_TO_END_FEATURE_PRODUCTION_AUDIT.md
├── feature_inventory.md
├── feature_wiring_matrix.md
├── feature_evidence/
│   ├── F-0001.md
│   ├── F-0002.md
│   └── ...
├── runtime/
│   ├── startup.md
│   ├── api.md
│   ├── browser.md
│   ├── database.md
│   └── integrations.md
├── regressions/
│   └── ...
└── FINAL_FEATURE_PRODUCTION_REPORT.md
```

Do not create unnecessary duplicate documentation if an existing audit structure already provides the same artifact. Reuse compatible files when safe.

---

# 71. MASTER FEATURE MATRIX

Create a table:

| ID | Feature | UI | API | Service | DB | External | E2E | Security | Runtime | Regression | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F-0001 | ... | PASS | PASS | PASS | PASS | N/A | PASS | PASS | PASS | PASS | PRODUCTION_READY |

No status may be filled without evidence.

---

# 72. WIRING MATRIX

Create:

| Feature | UI entry | Frontend call | Backend route | Service | DB | External | Result |
|---|---|---|---|---|---|---|---|

Special attention:

- backend-only feature with no caller
- frontend-only feature with no backend
- API route with no UI
- UI calling wrong endpoint
- stale endpoint
- wrong HTTP method
- wrong payload
- wrong response shape
- missing auth
- missing error handling

---

# 73. API COVERAGE MATRIX

Create:

| API | Method | Auth | Frontend Caller | Runtime | Tests | Status |
|---|---|---|---|---|---|---|

Every API must have an intentional consumer.

If backend-only:

document why.

---

# 74. UI COVERAGE MATRIX

Create:

| UI Feature | Route | Component | API | Real Data | E2E | Status |
|---|---|---|---|---|---|---|

A UI component with hardcoded/mock data must not be marked production-ready.

---

# 75. DATABASE COVERAGE MATRIX

Create:

| Model/Table | Migration | Read | Write | Feature | Constraints | Indexes | Runtime | Status |
|---|---|---|---|---|---|---|---|---|

---

# 76. EXTERNAL INTEGRATION MATRIX

Create:

| Provider | Feature | Config | Auth | Runtime | Error Path | Retry | Status |
|---|---|---|---|---|---|---|---|

---

# 77. SECURITY MATRIX

Create:

| Feature | Auth | RBAC | Input | Secret | Isolation | Injection | Audit | Status |
|---|---|---|---|---|---|---|---|---|

---

# 78. E2E USER JOURNEY MATRIX

Verify complete user journeys.

At minimum discover and test journeys equivalent to:

## Journey A — Login

```text
Open app
→ login
→ dashboard
→ protected API
→ logout
→ protected page blocked
```

## Journey B — Create Task

```text
Login
→ create task
→ select repo
→ select execution mode
→ submit
→ backend task
→ database record
→ pipeline
→ UI state
```

## Journey C — Plan Approval

```text
Task
→ PM
→ Architect
→ Decomposer
→ approval UI
→ edit plan
→ approve
→ manager
```

## Journey D — Agent Execution

```text
Subtask
→ agent selection
→ worktree
→ tool
→ code
→ tests
→ verification
→ reviewer
```

## Journey E — Failure Recovery

```text
intentional failure
→ failure detection
→ recovery rung
→ retry
→ success OR human escalation
```

## Journey F — Terminal

```text
open console
→ create terminal
→ execute command
→ stream output
→ exit
→ cleanup
```

## Journey G — Repository Chat

```text
open chat
→ select repo
→ ask question
→ repository context
→ tool usage
→ streamed response
→ persisted conversation
```

## Journey H — Fleet Enhancement

```text
fleet
→ enhancement request
→ evidence
→ human approval
→ apply
→ tests
→ commit
→ result
```

---

# 79. NEGATIVE TESTING

For each important feature intentionally test bad conditions.

Examples:

- invalid input
- missing required field
- invalid ID
- unauthorized user
- forbidden user
- missing database row
- database unavailable
- Redis unavailable
- LLM unavailable
- GitHub unavailable
- timeout
- malformed upstream response
- duplicate request
- concurrent request
- stale browser
- expired session
- process crash

Production features must fail safely.

---

# 80. FAILURE MUST NOT LOOK LIKE SUCCESS

Examples of failures:

- HTTP 200 with an error payload
- UI displays stale success after failed request
- task marked complete while worker failed
- approval marked approved but execution never started
- terminal UI connected while backend process died
- SSE appears connected but events are no longer arriving
- PR URL displayed but PR creation failed
- agent result displayed without verified execution

Explicitly test these.

---

# 81. DATA FLOW CONSISTENCY

Verify status values across:

```text
Database enum
→ backend model
→ API schema
→ frontend type
→ frontend rendering
→ filters
→ transitions
```

Find mismatched values such as:

- `completed` vs `complete`
- `failed` vs `error`
- `pending` vs `queued`

Do not patch one layer without understanding the complete contract.

---

# 82. TYPE CONSISTENCY

Verify:

- Python types
- Pydantic schemas
- OpenAPI
- TypeScript types
- runtime validation
- database types

No silent type conversion should be relied upon where correctness matters.

---

# 83. AUTHENTICATION CONTEXT PROPAGATION

Verify the authenticated identity is preserved across:

```text
Browser
→ frontend client
→ API
→ service
→ DB query
→ background task
→ agent run
→ audit log
```

A feature must not accidentally lose user/project identity.

---

# 84. PROJECT / REPOSITORY ISOLATION

Where project/repository scoping exists verify:

- task belongs to project
- memory belongs to project
- files belong to repository
- agent context belongs to correct repository
- terminal belongs to correct worktree
- logs identify correct task
- users cannot access another project's data

---

# 85. BACKGROUND TASK IDENTITY

If a background worker continues work after the HTTP request ends:

Verify it retains:

- task ID
- user/project ID
- repository ID
- authorization context needed for the operation
- trace ID
- correct database context

---

# 86. CACHE AUDIT

Where caching exists verify:

- cache key
- scope
- invalidation
- stale data behavior
- cross-user isolation
- cross-project isolation
- cache failure fallback

A cache must never return another user's/project's result.

---

# 87. QUEUE AUDIT

Where queues exist verify:

- enqueue
- dequeue
- worker
- retry
- duplicate handling
- dead-letter
- visibility/lease
- cancellation
- shutdown
- recovery after restart

---

# 88. REDIS AUDIT

If Redis is used:

Verify actual runtime usage.

Do not mark Redis as integrated because the dependency is installed.

Verify:

- connection
- queue/event bus
- serialization
- TTL
- reconnect
- failure behavior
- cleanup

---

# 89. POSTGRESQL AUDIT

Verify:

- connection pool
- migrations
- transactions
- connection cleanup
- indexes
- constraints
- query failures
- restart behavior
- concurrent transactions

---

# 90. DOCKER AUDIT

Verify:

- Dockerfile
- image build
- compose
- health checks
- volumes
- network
- environment
- non-root behavior
- resource limits
- restart behavior
- cleanup

Do not claim container isolation without running the container.

---

# 91. DEPLOYMENT AUDIT

Verify actual documented deployment path.

At minimum determine:

- required services
- environment variables
- migration process
- startup process
- health checks
- frontend build
- backend build
- workers
- database
- Redis
- secrets
- rollback

If deployment is intentionally human-controlled, record that rather than automating it.

---

# 92. PRODUCTION CONFIGURATION SAFETY

Fail the production gate if any applicable issue is found:

- debug enabled
- insecure default password
- test credentials
- missing required secret
- development-only auth bypass
- localhost-only dependency
- wildcard unsafe CORS without documented reason
- exposed internal diagnostics
- stack traces leaking secrets
- unsafe command execution
- missing authorization

---

# 93. OBSERVABILITY / INCIDENT READINESS

For important features verify an operator can answer:

- What failed?
- Which user?
- Which project?
- Which task?
- Which agent?
- Which request?
- Which database operation?
- Which external dependency?
- When did it fail?
- What was the retry state?
- What happened next?

If not, mark observability incomplete.

---

# 94. PERFORMANCE BASELINE

Do not invent universal performance targets.

Collect real measurements:

```text
Feature
Environment
Request count
p50
p95
p99 where meaningful
DB query count
memory
CPU
payload size
LLM tokens where applicable
external latency
```

Then compare against:

- existing project SLO
- documented target
- human-approved target

If no target exists, report measurements and request a target where necessary.

---

# 95. RESOURCE LEAK AUDIT

Look for:

- DB connections not released
- files not closed
- subprocesses not cleaned
- PTYs not closed
- Docker containers left behind
- worktrees left behind
- Redis connections leaked
- async tasks left pending
- event listeners duplicated
- browser contexts not closed

Verify with runtime observation.

---

# 96. SHUTDOWN / RESTART AUDIT

Test:

- backend restart
- frontend restart
- worker restart
- Redis restart
- database restart where safe
- Docker restart where relevant

Verify persistent features recover correctly.

---

# 97. RESUME AFTER FAILURE

For durable task execution verify:

```text
start task
→ interrupt process
→ restart service
→ recover state
→ continue safely
```

Verify no duplicate destructive operation occurs.

---

# 98. AUDIT LOGGING

Every important state-changing operation should have appropriate audit evidence.

Examples:

- login
- logout
- approval
- rejection
- task state
- agent run
- tool execution
- credential change
- git push
- enhancement apply
- rollback

Verify actual log creation.

---

# 99. DOCUMENTATION CONSISTENCY

After implementation changes:

Update only documentation that is actually affected.

Never modify documentation merely to make an audit pass.

Documentation must reflect observed reality.

---

# 100. FINAL PRODUCTION GATE

The final green flag is allowed only if:

```text
ALL DISCOVERED IN-SCOPE FEATURES
        ↓
COMPLETE WIRING VERIFIED
        ↓
BACKEND VERIFIED
        ↓
FRONTEND VERIFIED
        ↓
DATABASE VERIFIED
        ↓
REAL RUNTIME VERIFIED
        ↓
SECURITY VERIFIED
        ↓
ERROR PATH VERIFIED
        ↓
E2E VERIFIED
        ↓
REGRESSION VERIFIED
        ↓
NO UNKNOWN CRITICAL ITEMS
        ↓
NO UNRESOLVED CRITICAL BUGS
        ↓
NO UNRESOLVED FEATURE WIRING GAPS
        ↓
NO UNRESOLVED AUTHORIZATION GAP
        ↓
NO UNRESOLVED DATA INTEGRITY GAP
        ↓
NO UNRESOLVED PRODUCTION CONFIG GAP
        ↓
GREEN FLAG
```

---

# 101. GREEN FLAG RULE

At the end output exactly one of:

## GREEN FLAG — PRODUCTION FEATURE COMPLETE

Only when every required feature has reached `PRODUCTION_READY`.

OR:

## NOT GREEN — PRODUCTION FEATURE AUDIT INCOMPLETE

With:

- total discovered features
- production-ready count
- partial count
- broken count
- unwired count
- blocked count
- conflict count
- deferred count
- unknown count
- critical blockers
- remaining fixes

Never output green merely because the percentage is high.

One critical authentication/data-loss/security/wiring defect can block the green flag.

---

# 102. FINAL REPORT FORMAT

Create:

`FINAL_FEATURE_PRODUCTION_REPORT.md`

Use:

```markdown
# Final Feature Production Report

Audit date:
Repository:
Commit:
Environment:

## Final Decision

GREEN FLAG — PRODUCTION FEATURE COMPLETE

OR

NOT GREEN — PRODUCTION FEATURE AUDIT INCOMPLETE

## Feature Counts

Discovered:
Production Ready:
Partial:
Broken:
Unwired:
Blocked:
Conflict:
Deferred:
Unknown:

## Critical Findings

1.
2.
3.

## Repairs Performed

1.
2.
3.

## Regression Results

Tests:
Build:
E2E:
Security:
Runtime:
Database:
External integrations:

## Evidence

<commands and references>

## Human Decisions Required

<only if applicable>

## Final Green Flag Conditions

- [ ] Every required feature verified
- [ ] Every required feature wired
- [ ] Backend verified
- [ ] Frontend verified
- [ ] Database verified
- [ ] Runtime verified
- [ ] Security verified
- [ ] E2E verified
- [ ] Regression verified
- [ ] No critical unknowns
- [ ] No unresolved critical defects
- [ ] No unresolved feature/API wiring gaps

FINAL STATUS:
```

---

# 103. AUDIT COMMAND DISCIPLINE

Before using a command, understand what it proves.

For example:

```bash
pytest
```

proves tests passed.

It does NOT prove:

- frontend wiring
- production credentials
- browser behavior
- external API behavior
- authorization
- deployment configuration

Likewise:

```bash
npm run build
```

proves build success.

It does NOT prove:

- backend integration
- UI functionality
- database correctness
- runtime behavior

Every command must have a documented purpose.

---

# 104. EVIDENCE CHAIN

For every important YES maintain:

```text
Claim
↓
Source location
↓
Execution
↓
Observed result
↓
Conclusion
```

Example:

```text
Claim:
Approval button actually approves a pending plan.

Source:
Approval UI component
↓
frontend client
↓
POST /api/approvals/<id>/approve
↓
backend handler
↓
DB state transition

Execution:
Playwright clicked Approve.

Observed:
HTTP 200
DB status changed pending → approved
SSE event received
UI changed to Approved
Manager execution started

Conclusion:
VERIFIED
```

---

# 105. ANTI-FALSE-POSITIVE RULES

These are explicit audit failures.

## False positive 1

"Endpoint exists."

Not enough.

## False positive 2

"Component exists."

Not enough.

## False positive 3

"Test exists."

Not enough.

## False positive 4

"Test passes with mocks."

Not enough for integration.

## False positive 5

"Database model exists."

Not enough.

## False positive 6

"Agent is registered."

Not enough.

## False positive 7

"Tool appears in tool list."

Not enough.

## False positive 8

"README says it works."

Not enough.

## False positive 9

"Manual screenshot looks good."

Not enough.

## False positive 10

"Previous audit says YES."

Not enough.

---

# 106. ANTI-FALSE-NEGATIVE RULE

Do not declare a feature broken merely because its implementation is non-obvious.

Before marking broken:

1. Search actual imports.
2. Search actual call graph.
3. Inspect route registration.
4. Inspect configuration.
5. Inspect runtime.
6. Check generated code/build output where relevant.
7. Check dynamic registration.
8. Check plugin/tool registries.
9. Check dependency injection.
10. Reproduce behavior.

If still uncertain:

`UNKNOWN`

not `BROKEN`.

---

# 107. DYNAMIC REGISTRATION AUDIT

The project may dynamically register:

- agents
- tools
- routes
- workers
- capabilities
- models
- prompts
- plugins

Do not rely only on static file discovery.

Inspect actual registration mechanisms and runtime registries.

---

# 108. GENERATED CODE AUDIT

If code is generated:

Verify:

- generator
- generated artifact
- generation step
- generated artifact actually used
- stale generated output
- production build behavior

---

# 109. PLUGIN / TOOL CONNECTION AUDIT

For every optional plugin/integration:

- installed?
- connected?
- permission granted?
- actual runtime call?
- failure fallback?
- UI indication?
- configuration?
- production behavior?

Do not call an optional integration production-ready when it is disconnected.

---

# 110. FEATURE OWNERSHIP

Every feature should have:

- implementation owner/area
- source files
- dependencies
- tests
- documentation

If ownership is missing, record it as maintainability risk.

---

# 111. FEATURE COMPLETENESS CHECK

A feature is incomplete if any essential layer is absent:

```text
Requirement
Implementation
Connection
Execution
Persistence where needed
UI where needed
Error handling
Security
Testing
Observability
Regression protection
```

Applicability must be proven for layers marked N/A.

---

# 112. NO UNNECESSARY FEATURE CREATION

The purpose of this audit is not to invent new product functionality.

If the requirement is:

> verify and repair existing features

do not expand product scope without human approval.

---

# 113. NO UNNECESSARY DEPENDENCY CHANGES

Do not upgrade packages simply because newer versions exist.

Dependency changes require evidence that they are needed.

After any dependency change:

- lockfile
- install
- build
- tests
- integration
- security
- regression

---

# 114. NO MASS REFACTOR DURING FEATURE AUDIT

If a feature works but the code is ugly:

do not automatically refactor it.

This audit is about production behavior.

Create a separate enhancement item unless refactoring is required to fix a production defect.

---

# 115. FEATURE PRIORITY

Use:

`P0` = security/data-loss/core platform failure  
`P1` = core product feature failure  
`P2` = important secondary feature failure  
`P3` = minor UX/quality issue

Do not use priority as a reason to declare a failed P0/P1 feature production-ready.

---

# 116. CRITICAL BLOCKERS

The following normally block green flag when applicable:

- authentication bypass
- authorization bypass
- cross-user/project data exposure
- data corruption
- destructive migration without safe path
- secret exposure
- unsafe command execution
- broken core task lifecycle
- broken production startup
- broken core database
- broken core API/frontend wiring
- false success reporting
- unrecoverable worker/process leak
- critical unresolved integration failure

---

# 117. ACCEPTABLE HUMAN-GATED FEATURES

A feature may remain production-ready while intentionally requiring human action.

Example:

- final PR approval
- production cloud deployment approval
- destructive operation confirmation

The human gate itself must work.

Do not classify intentional human approval as a bug.

---

# 118. PRODUCTION-READY VS AUTOMATED

These are different.

A feature can be:

`PRODUCTION_READY + HUMAN_GATED`

if the human gate is intentional and verified.

Do not force automation where the architecture intentionally requires human approval.

---

# 119. EXISTING AUDITS INTEGRATION

This audit complements existing audits.

Existing audits cover areas such as:

- architecture
- agents
- memory
- orchestration
- security
- infrastructure
- AI evaluation
- production readiness
- performance/scalability
- consolidation
- zero-policy

This audit should reuse their evidence where valid, but independently verify the actual feature path.

Do not duplicate their scope unnecessarily.

---

# 120. FINAL EXECUTION INSTRUCTION TO CLAUDE CODE

You are now acting as a senior production verification engineer.

Your job is NOT to produce a report saying the code looks good.

Your job is:

```text
DISCOVER
↓
TRACE
↓
VERIFY
↓
REPRODUCE
↓
FIX
↓
TEST
↓
INTEGRATE
↓
E2E
↓
REGRESSION
↓
RECHECK
↓
PRODUCTION READY
↓
NEXT FEATURE
```

For every discovered feature:

1. Find the real implementation.
2. Find the real consumer.
3. Find the real API connection.
4. Find the real database/external dependency.
5. Execute the feature.
6. Verify the result.
7. Test failure paths.
8. Test security.
9. Fix only real defects.
10. Re-run the feature.
11. Run regression.
12. Do not move forward until production-ready or human-approved blocked/deferred/conflict.
13. Never invent evidence.
14. Never mark something green because documentation says so.
15. Never break an already-working feature.
16. Stop and ask the human when requirements conflict.
17. Continue until the entire in-scope feature inventory is exhausted.

---

# 121. FINAL GREEN FLAG

At the absolute end, after all feature-level verification and regression testing:

```text
===========================================================
             GRIDIRON FEATURE PRODUCTION GATE
===========================================================

Features discovered:              <N>
Production-ready:                <N>
Partial:                         <N>
Broken:                          <N>
Unwired:                         <N>
Blocked:                         <N>
Conflict:                        <N>
Deferred:                        <N>
Unknown:                         <N>

Critical blockers:               <N>
Unresolved API/UI wiring gaps:   <N>
Unresolved security gaps:        <N>
Unresolved data gaps:            <N>
Unresolved runtime gaps:         <N>

Regression suite:                PASS/FAIL
E2E suite:                       PASS/FAIL
Production build:                PASS/FAIL
Runtime startup:                 PASS/FAIL
Database verification:           PASS/FAIL
External integration checks:     PASS/FAIL

===========================================================

FINAL STATUS:

GREEN FLAG — PRODUCTION FEATURE COMPLETE

OR

NOT GREEN — PRODUCTION FEATURE AUDIT INCOMPLETE

===========================================================
```

**GREEN FLAG is a factual gate, not a score.**

Do not output green until the evidence supports it.

---

# END OF MASTER END-TO-END FEATURE PRODUCTION AUDIT
