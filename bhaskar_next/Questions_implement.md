# GridIron → Production AI Software-Engineering Platform

## Final Implementation Roadmap & Claude Code Execution Brief

### Production Hardening → Commercial Launch

**Baseline audit:** 519 total checkpoints\
**Current baseline:** 394 YES / 61 PARTIAL / 14 NO / 50 SKIP\
**Goal:** eliminate genuine PARTIAL/NO gaps without regressing the 394
existing YES checkpoints, while preserving deliberate SKIP/safety
boundaries.

> **Important:** The final status must be determined by re-running the
> original 519-checkpoint audit against the current codebase. Roadmap
> completion does not automatically mean an audit checkpoint is YES.

------------------------------------------------------------------------

# 0. HOW TO USE THIS FILE

1.  Do **not** paste this entire document into one Claude Code session.
2.  Execute **one PROMPT block at a time**, in the recommended order.
3.  At the beginning of every Claude Code session, paste the **Global
    Engineering Contract** from Section 2.
4.  Claude Code must inspect the current source before changing
    anything. The previous audit is a baseline, not permission to assume
    the code is unchanged.
5.  One implementation prompt should normally produce one PR unless the
    prompt explicitly says it may be split.
6.  After every prompt, run the Definition of Done checklist in Section
    9.
7.  If any required evidence is missing, the item remains **PARTIAL**.
8.  Never mark a roadmap item YES merely because code exists.
9.  Protect the original 394 YES checkpoints from regression.
10. After all implementation programs, execute the **Final
    519-Checkpoint Re-Audit** in Section 10.

------------------------------------------------------------------------

# 1. TARGET STATE

The target is:

> **A serious production AI software-engineering platform capable of
> operating like a Claude Code/Cursor-style engineering organization,
> while providing stronger orchestration, verification, human control,
> recovery, governance, and enterprise isolation.**

The implementation is organized into:

-   **P0 --- Critical architecture**
-   **P1 --- Product experience and reliability**
-   **P2 --- Intelligence and organization**
-   **P3 --- Enterprise/commercial**
-   **P4 --- Launch validation**
-   **FINAL --- Re-run all 519 audit checkpoints**

------------------------------------------------------------------------

# 2. GLOBAL ENGINEERING CONTRACT

Paste this at the top of every Claude Code session.

``` text
You are acting as a Production Implementation Agent on the GridIron
codebase.

For every task in this session follow this exact sequence:

1. AUDIT
Before writing code, inspect the actual current implementation of
everything related to this task.

Explicitly report:
- what already exists
- what is incomplete
- what is missing
- which audit claims are still true
- which audit claims have already been fixed

Do not assume the previous audit is still accurate.

2. LOCATE
Identify the exact files/classes/functions/tables/endpoints/tests that
will be affected.

List them before modifying code.

3. DEPENDENCY CHECK
Inspect callers, imports, persistence dependencies, graph dependencies,
API contracts, security boundaries and tests that depend on current
behavior.

4. DESIGN
Propose the implementation before coding.

Prefer extending/reusing existing mechanisms over creating parallel
systems.

If an important architectural decision is genuinely ambiguous, stop and
ask rather than guessing.

5. IMPLEMENT
Implement the real capability.

No placeholders.
No fake success paths.
No TODOs presented as implementation.
No fabricated metrics.
No fabricated verification.
No unnecessary rewrites.

6. TEST
Add and EXECUTE appropriate tests.

Use:
- unit tests
- integration tests
- failure tests
- concurrency tests where relevant
- crash/recovery tests where relevant
- multi-instance tests where relevant
- security tests where relevant
- frontend tests where relevant

Mocks are acceptable only for genuinely external systems.
Never mock away the mechanism being tested.

7. REGRESSION
Run the relevant existing test suite plus the full regression suite where
practical.

Run:
- tests
- linter
- formatter checks
- type checker

Zero unexplained new failures.

If an existing assertion became intentionally stale, update it only after
explaining why.

8. SECURITY
Confirm that no existing:
- sandbox boundary
- HITL/approval boundary
- RBAC boundary
- secret-redaction boundary
- audit logging
- tenant/repository isolation
- tool permission boundary

was weakened.

9. EVIDENCE REPORT
Return:
- files changed with file:line evidence
- database migrations
- tests added
- exact test commands executed
- actual test results
- lint/type-check results
- integration/concurrency/recovery evidence where applicable
- remaining gaps
- deliberately scoped-out items and why

10. AUDIT STATUS
For every relevant original audit checkpoint say:
- YES
- PARTIAL
- NO
- SKIP

with evidence.

HARD RULES:

- Code existence is NOT evidence of completion.
- A written test is NOT evidence; the test must actually execute and pass.
- Never fabricate a benchmark, metric, test result, confidence score or
  verification result.
- Never weaken security/HITL/sandboxing to make a feature easier.
- Preserve backward compatibility unless the prompt explicitly permits a
  breaking change.
- Reuse existing mechanisms named in the prompt.
- If reuse is impossible, explain why before introducing a parallel system.
- Do not claim production readiness from local unit tests alone.
- Do not silently downgrade an existing YES capability.
- Do not change deliberate architectural boundaries simply to make audit
  wording say YES.
```

------------------------------------------------------------------------

# 3. PERMANENT GUARDRAILS

Do NOT "fix" these into different architectures:

1.  Separate tool registry for the fleet self-improvement agents ---
    keep the existing intentional shared infrastructure.
2.  A single centralized codebase-monitor module --- monitoring is
    intentionally distributed.
3.  Automatic AWS/cloud deployment execution --- diagnosis/guide
    generation may exist, but dangerous deployment execution remains
    human-controlled.
4.  Blind automatic merge-conflict resolution --- conflicts remain
    human-judgment gated.
5.  True FIFO queue reordering --- retain the existing priority-bucketed
    scheduling model.
6.  Do not remove existing approval requirements to improve automation
    scores.
7.  Do not turn prompt instructions into substitutes for code-enforced
    policy.
8.  Do not build fake hallucination detection by asking the same LLM
    whether it hallucinated.

------------------------------------------------------------------------

# 4. AUDIT BASELINE AND REGRESSION TARGET

Current baseline:

  Status          Count
  ----------- ---------
  YES               394
  PARTIAL            61
  NO                 14
  SKIP               50
  **TOTAL**     **519**

The objective is NOT simply "make 28 prompts pass."

The actual objective is:

> **Preserve the 394 YES, upgrade genuine PARTIAL/NO checkpoints where
> applicable, preserve deliberate SKIPs, and introduce zero unacceptable
> regressions.**

Every implementation prompt must identify which original audit
checkpoints it affects.

------------------------------------------------------------------------

# 5. ROADMAP ↔ AUDIT MAPPING

Use this mapping as the starting point. Claude Code must verify the
exact checkpoint mapping against the original audit before changing
code.

  ------------------------------------------------------------------------------
  Program                 Main capability            Known audit area
  ----------------------- -------------------------- ---------------------------
  Q1                      Dynamic subtask creation   #44 and related
                                                     orchestration

  Q2                      Agent-to-agent delegation  #45, #67

  Q3                      Memory/performance-aware   #58 and routing/performance
                          routing                    gaps

  Q4                      Dynamic tool switching     #66

  Q5                      Distributed AgentRegistry  #494 and distributed
                                                     coordination

  Q6                      Horizontal scaling         #171 and related
                                                     distributed runtime

  Q7                      Universal evidence         #495, #503 and related
                          enforcement                enforcement

  Q8                      Facts vs assumptions       #505

  Q9                      Production completion gate #453--#457 family

  Q10                     Dependency quality gate    dependency-gate gaps

  Q11                     Documentation quality gate documentation-gate gaps

  Q12                     Interactive PTY            #3, #12 and terminal gaps

  Q13                     Multi-terminal             #5 and terminal-session
                                                     gaps

  Q14                     Windows CI                 #6

  Q15                     Human takeover             #227

  Q16                     Universal recovery         #234--#246 family

  Q17                     Memory lifecycle           #88, #90, #98, #100

  Q18                     Large repository           #255, #257, #259
                          engineering                

  Q19                     Dependency-aware           #428, #429, #407, #437,
                          dispatch + metrics         #439

  Q20                     Governance                 governance gaps

  Q21                     Company Brain              #405

  Q22                     Conversational repeat      conversational task-history
                                                     gap

  Q23                     Documentation lookup       #297

  Q24                     Agent health intelligence  #443

  Q25                     Architecture protection    #456/architecture-related
                                                     gaps

  Q26                     Repository/branch context  #361

  Q27                     Multi-tenant isolation     cross-repository/tenant
                                                     isolation

  Q28                     Per-user cost analytics    commercial analytics

  Q29                     Production deployment      launch readiness
                          validation                 

  Q30                     Security red-team          production security

  Q31                     Production load testing    performance/capacity
  ------------------------------------------------------------------------------

**Rule:** if the current source shows that an old gap has already been
fixed, do not recreate it. Verify it and move to the remaining gap.

------------------------------------------------------------------------

# 6. PHASE P0 --- CRITICAL

## Q1 --- Dynamic subtask creation

``` text
Allow a running worker agent to create new subtasks when it discovers
work that was not known during initial planning.

Build/extend a secure propose_subtask capability.

Requirements:
- validate proposed subtask against parent task/epic scope
- prevent duplicate/conflicting subtasks
- reuse existing conflict/dependency mechanisms
- record depends_on relationships
- associate child with parent task/epic
- respect existing token/cost budget
- enforce role-based permission
- allow manager wave-dispatch to discover newly created subtasks
- dispatch newly-created work without restarting the whole epic
- persist enough state for crash/recovery

Do not replace decomposer_node/decomposition.

Tests:
- validation
- deduplication
- integration dispatch during active epic
- concurrent proposals
- crash between proposal and dispatch
- recovery after restart
```

## Q2 --- Agent-to-agent delegation

``` text
Allow one agent to request assistance from another specialized agent
during execution.

Build/extend delegate_to with:
- explicit role allow-list
- configurable delegation depth limit
- independent cycle detection
- inherited epic/task context
- shared token/cost budget
- timeout
- cancellation propagation
- complete audit trail
- result returned to requesting agent

Test:
- recursive delegation
- cycles
- budget exhaustion
- timeout
- failure propagation
- permission denial
- cancellation
```

## Q3 --- Memory-aware + performance-aware agent selection

``` text
First verify the current source. Do not assume the previous audit's
memory_embeddings schema is unchanged.

If agent attribution is still missing:
- add additive migration for agent_name
- update embed_task_outcome callers
- preserve old unattributed rows

Extend FleetManager.select() using real data:
- historical success on similar tasks/domains
- historical failure patterns
- p50/p95 latency
- token/cost history
- current workload
- confidence/capability

Reuse MetricsCollector and existing DispatchPlan.reason/task_logs.rationale.

Prefer faster equally-capable agents only when quality is statistically
equivalent. Latency must not override a real quality gap.

Tests:
- migration
- attribution
- similarity routing
- latency tie-break
- cost routing
- explainability
- regression
```

## Q4 --- Controlled dynamic tool switching

``` text
Allow controlled mid-run tool expansion only after a concrete runtime
signal.

Candidate high-confidence triggers:
- security finding → security_scan-class tools
- dependency failure → dependency-resolution tools
- test failure → debugger-class tools

Before implementing, inspect the existing policy/manifest architecture.

Every dynamic tool grant must still pass:
- role check
- permission check
- budget check
- policy check
- audit logging

Never allow the LLM to arbitrarily grant itself tools.

Tests:
- each real trigger
- unrelated signal does not trigger
- unauthorized role remains blocked
- audit trail
- budget denial
```

------------------------------------------------------------------------

# 7. PHASE P0-2 --- DISTRIBUTED RUNTIME

## Q5 --- Distributed AgentRegistry proof of concept

``` text
This is a high-risk dispatch-path change.

First determine whether "one agent type at a time" is intended as a
system-wide invariant or only a process-local invariant.

Inspect actual callers and current production behavior before deciding.

Design authoritative distributed state using existing PostgreSQL/Redis
infrastructure where appropriate.

Do not force a technology choice before evaluating:
- consistency
- atomic claiming
- latency
- cancellation
- recovery
- operational complexity

Implement:
- distributed registration
- distributed health state
- distributed concurrency
- stale worker detection
- atomic claiming
- race protection
- cache invalidation
- multi-instance chat/session state strategy

Do not rely on TTL-based correctness.

Tests:
- real 2-instance integration
- concurrent claim
- no double dispatch
- cache invalidation
- cancellation
- failure recovery
- latency benchmark before/after
```

## Q6 --- Horizontal scaling

``` text
After Q5 is proven, run a repeatable 2–5 backend instance test harness
against shared PostgreSQL/Redis.

Prove:
- no duplicated tasks
- no double dispatch
- distributed locks work
- cancellation crosses instances
- HITL state is shared
- checkpoints are shared
- orphan recovery works
- chat/session state is shared
- queue state remains consistent
- concurrent enqueue is safe

Prefer a Docker Compose or equivalent repeatable multi-instance harness.

Make the harness a permanent regression gate.
```

------------------------------------------------------------------------

# 8. PHASE P0-3 --- EVIDENCE-FIRST ENFORCEMENT

## Q7 --- Universal blocking_until / verification enforcement

``` text
Audit every current agent.

For every write-capable or consequential agent:
- identify write/submit tools
- define appropriate blocking_until requirements
- enforce read-before-write
- enforce execution/test evidence before success claims
- enforce actual tool-derived verification
- verify file/function/class/API existence where required

Read-only agents may be N/A only with an explicit reason.

Ensure verification is code-enforced and returns [POLICY DENIED] when
required evidence is absent.

Verify verify_file_line_citations and equivalent submit-chokepoint checks
cover every applicable agent.

Produce a coverage table.

Tests:
- each newly gated agent
- denial without evidence
- success after evidence
- no invented test results
- no invented files/APIs
```

## Q8 --- Facts vs assumptions

``` text
Add structured result classification:
- VERIFIED
- INFERRED
- ASSUMED
- NOT VERIFIED
- FAILED TO VERIFY

Reuse existing quality-gate evidence rather than creating a parallel
verification system.

Expose the classification clearly in the frontend.

An unverified assumption must never render like a verified result.

Tests:
- verified result
- inferred result
- failed verification
- frontend rendering
```

------------------------------------------------------------------------

# 9. PHASE P0-4 --- MANDATORY PRODUCTION QUALITY GATES

## Q9 --- Production completion gate

``` text
Before a code-changing task can report SUCCESS, evaluate:

1. tests
2. lint
3. formatting
4. type checking
5. security
6. dependency safety
7. architecture
8. performance/regression
9. documentation
10. evidence verification

Every gate returns structured:
PASS / FAIL / SKIPPED
plus evidence.

Mandatory SKIPPED blocks SUCCESS unless an authorized approver
explicitly overrides it.

A FAILED gate cannot be overridden by an ordinary user.

Before making reviewer gates mandatory fleet-wide, implement a bounded
retry/self-correction loop for security and architecture findings,
mirroring proven coder retry behavior.

Tests:
- failed gate blocks success
- skipped mandatory gate blocks
- authorized override works
- unauthorized override fails
- failed gate cannot be bypassed
```

## Q10 --- Dependency gate

``` text
Build a mandatory dependency-quality gate.

Reuse:
- dependency_security_agent
- pip-audit integration
- dependency_agent
- license_check.py
- existing advisory gate patterns

Verify:
- vulnerabilities
- outdated packages
- abandoned packages
- dependency conflicts
- license policy
- lockfile consistency where applicable

For true constraint conflicts, use a real dependency-resolution mechanism,
not only pip check.

Tests must include an actual conflicting dependency scenario.
```

## Q11 --- Documentation gate

``` text
Build a scoped-diff documentation completeness gate.

Inspect only changed files and affected public surfaces.

Potential checks:
- README
- API docs
- architecture docs
- agent/tool docs
- changelog
- migration notes

Do not regenerate the entire repository on every task.

Pure internal refactoring should not automatically require documentation.

Tests:
- new public endpoint without docs → FAIL
- internal refactor → PASS
- intentional documentation change → PASS
```

------------------------------------------------------------------------

# 10. PHASE P1 --- PRODUCT EXPERIENCE + RELIABILITY

## Q12 --- Real interactive PTY terminal

``` text
Replace request/response shell behavior with a real interactive PTY
inside the existing sandbox.

Requirements:
- real PTY
- stdin
- streaming stdout/stderr
- Ctrl+C
- resize
- environment handling
- persistent working directory per session
- process lifecycle
- timeout
- cancellation
- audit logging
- sandbox containment

Frontend:
- xterm.js-style terminal
- streaming connection

Never bypass the existing sandbox.

Tests:
- real command
- interactive input
- Ctrl+C
- resize
- cancellation
- sandbox escape attempts
```

## Q13 --- Multi-terminal

``` text
Allow multiple independent PTY sessions per task.

Provide:
- terminal tabs
- unique session IDs
- independent working directories
- independent processes
- kill/restart
- session listing
- backend restart reattachment

Tests:
- two terminals run independently
- killing one leaves the other alive
- reattachment works
```

## Q14 --- Real Windows CI

``` text
Add GitHub Actions windows-latest CI.

Actually run the backend test suite on Windows.

Audit existing cross-platform call sites and fix genuine failures.

Do not claim Windows support without a real Windows CI execution.

Deliverable:
- passing Windows CI
- Windows-specific regression coverage
```

## Q15 --- Human takeover / step-level plan editing

``` text
Implement step-level human control over an executing plan.

User must be able to:
- pause
- inspect
- edit future step
- delete step
- reorder step
- reject step
- insert step
- approve step
- inject instructions
- resume from exact checkpoint

Preserve previous execution history.

Do not restart the entire task.

Audit every human plan modification.

Tests:
- edit future step
- reject/replace
- insert
- reorder
- exact checkpoint resume
- history preservation
```

## Q16 --- Universal checkpoint/recovery

``` text
Build the common recovery architecture once.

Create a per-agent-type graph rebuild factory mapping agent_type to the
correct graph/tool handlers/verification configuration.

Persist:
- checkpoint
- execution state
- control flags
- agent type
- tool configuration
- verification configuration
- task state
- trace ID
- current step

Persist abort/resume state to DB.

Make background-process/PID state recoverable.

Make orphan recovery reconstruct the correct graph and resume rather than
simply marking the run failed.

Support:
- process crash
- machine reboot
- worker termination
- network interruption
- LLM timeout
- terminal termination

Tests:
- kill process mid-run
- restart
- resume correctly
- at least 3 different agent types
```

## Q17 --- Memory lifecycle

``` text
Implement:

capture
→ validate
→ score
→ compress
→ consolidate
→ promote
→ retrieve
→ evaluate
→ decay
→ archive

Close remaining lifecycle gaps:
- session summarization
- context compression
- usefulness feedback
- periodic consolidation
- provenance
- confidence
- rollback

Never lose critical facts silently.

If summarization/compression fails, retain original content.

Tests:
- fact preservation
- compression threshold
- ranking changes from feedback
- leader-gated consolidation
- rollback
- provenance
```

## Q18 --- Massive repository engineering

``` text
Improve large repository operations.

1. Large-file I/O:
- streaming/chunked paths where safe
- avoid unnecessary whole-file memory usage

2. 100+ file batch editing:
- transactional behavior
- dry run
- preview
- explicit large-batch confirmation
- rollback on failure

3. TypeScript/JavaScript AST-aware refactoring:
- use existing tree-sitter TS/JS parser
- do not use regex where AST/span information is available

Tests:
- 10,000+ line file
- 100+ file batch
- mid-batch rollback
- TS/JS rename
- string/comment safety
```

------------------------------------------------------------------------

# 11. PHASE P2 --- INTELLIGENCE + ORGANIZATION

## Q19 --- Dependency-aware dispatch + persistent metrics

``` text
Implement:
- explicit dependency-blocked status
- automatic dispatch when dependencies complete
- persisted real retry metrics
- persisted agent performance metrics
- real user satisfaction signal

Use existing leader-gated background loop patterns.

Do not use regex frustration detection as a substitute for actual
user feedback.

Tests:
- dependency completion triggers dispatch
- no premature dispatch
- metrics survive restart
- retries equal actual retries
- satisfaction is persisted
```

## Q20 --- Governance engine

``` text
Do not code until actual organization rules are defined.

First produce a governance specification covering:
- approved frameworks
- coding standards
- naming rules
- dependency policy
- security standards
- architecture rules
- project overrides

Then extend existing governance/policy mechanisms.

Do not create a second policy engine.

Every policy decision must be:
- explainable
- versioned
- auditable

Tests:
- each rule
- explanation
- audit record
```

## Q21 --- Company Brain

``` text
Make approved prompts, tools and MCP configurations first-class
organizational knowledge.

Store:
- name
- version
- purpose
- approved configuration
- successful use cases
- failure cases
- owner
- approver
- provenance
- project scope

Reuse the existing organizational memory/search mechanism.

Ensure repository/project scoping.

Tests:
- semantic retrieval
- scope isolation
- provenance
```

## Q22 --- Conversational "do that again"

``` text
Reuse the existing deterministic task repeat mechanism.

Add a chat-facing tool capable of resolving:
- do that again
- repeat the last task
- repeat the previous fix
- do it on the new branch
- repeat with a changed requirement

If ambiguous:
- show candidate
- require confirmation
- never silently guess

Tests:
- unambiguous reference
- ambiguous reference
- modified repeat
- confirmation gate
```

## Q23 --- Narrow documentation lookup

``` text
Do not build "always search web when unsure."

Trigger documentation lookup only on high-confidence signals:
- unresolved import
- compiler/type-checker unknown API error
- unsupported/unrecognized package version

Reuse existing URL/GitHub/OpenAPI inspection tools.

Retrieve authoritative documentation, summarize, cite, and gate risky
write/execute instructions behind approval.

Tests:
- each trigger
- no false trigger for unrelated uncertainty
- approval before risky action
```

## Q24 --- Agent health intelligence

``` text
Treat this as research-adjacent infrastructure.

Detect:
- evidence-contradicted claims
- repeated incorrect outputs
- memory synchronization failure
- abnormal latency
- repeated retries
- tool misuse
- context corruption
- runaway loops

Do not ask the same LLM whether it hallucinated.

Use independent evidence:
- tool output
- file citations
- test results
- execution traces
- cross-checks

Extend existing health state machine only where necessary.

Tests:
- induced contradiction detected
- correct evidence-backed claim not falsely flagged
- loop detection
- tool misuse detection
```

## Q25 --- Architecture protection

``` text
Extend architecture checks to multi-file write paths.

Check:
- circular imports
- forbidden dependencies
- module boundaries
- public API compatibility

Reuse detect_circular_imports and existing architecture review logic.

Fail mandatory violations unless authorized human override is used.

Tests:
- circular import introduced through sync_files
- forbidden dependency
- public API regression
```

## Q26 --- Persistent repository/branch context

``` text
Track the active repository branch explicitly.

Do not confuse:
- repository active branch
with
- per-task isolation branch.

When branch changes:
- update persistent state
- invalidate stale context
- rebuild required context
- expose correct branch to agents

Tests:
- branch switch
- stale context invalidation
- next agent sees correct branch
```

------------------------------------------------------------------------

# 12. PHASE P3 --- ENTERPRISE / COMMERCIAL

Only implement when selling to multiple organizations.

## Q27 --- Multi-tenant isolation

``` text
Implement real tenant/workspace/organization isolation.

Every scoped entity must have validated ownership.

Prevent cross-tenant access to:
- memory
- credentials
- tasks
- artifacts
- events
- approvals
- embeddings
- metrics
- agent context
- repositories

Use an explicit tenant/workspace entity rather than relying on implicit
repo_id assumptions.

Tests:
- adversarial cross-tenant API access
- cross-tenant memory
- credentials
- tasks
- artifacts
- events
- approvals
- embeddings
- metrics
```

## Q28 --- Per-user cost/usage analytics

``` text
Add actor/user attribution to AgentRun and orchestration.

Track:
- user
- task
- agent
- tokens
- cost
- duration
- retries

Build per-user cost/token analytics.

Tests:
- concurrent users
- correct attribution
- aggregate accuracy
- isolation
```

------------------------------------------------------------------------

# 13. PHASE P4 --- PRODUCTION LAUNCH VALIDATION

## Q29 --- Production deployment validation

``` text
Validate GridIron as a production service.

Prove:
- reproducible production Docker images
- clean database migration
- upgrade migration
- rollback procedure
- PostgreSQL failure behavior
- Redis failure behavior
- worker failure recovery
- backend restart recovery
- secret management
- environment validation
- health/readiness/liveness
- structured logs
- tracing
- metrics
- alerting
- backup/restore
- rate limiting
- authentication
- authorization
- audit-log integrity
- sandbox isolation
- resource limits
- graceful shutdown
- deployment/restart behavior

Execute production smoke tests against a production-like environment.

Configuration existence alone is not evidence.
```

## Q30 --- Security red-team

``` text
Run a production security red-team against the complete execution
surface.

Test:
- prompt injection
- malicious repository instructions
- tool abuse
- sandbox escape
- command injection
- path traversal
- credential exposure
- secret leakage into LLM prompts
- cross-project access
- unauthorized delegation
- unauthorized dynamic tool activation
- HITL bypass
- approval bypass
- ownership bypass
- webhook/event forgery
- SSRF
- malicious MCP/tool configuration
- repository poisoning
- dependency poisoning

Every finding must include:
- severity
- reproduction
- affected code
- remediation
- regression test

Do not rely only on static scanners.
```

## Q31 --- Production load test

``` text
Create a repeatable production-load benchmark.

Measure:
- concurrent users
- concurrent tasks
- concurrent agents
- queue latency
- dispatch latency
- LLM latency
- tool latency
- DB latency
- Redis latency
- token consumption
- cost/task
- CPU
- memory
- p50
- p95
- p99
- failure rate
- retry rate
- recovery time

Increase load until the supported capacity boundary is identified.

Document measured capacity and resource requirements.

Never invent capacity numbers.
```

------------------------------------------------------------------------

# 14. RECOMMENDED EXECUTION ORDER

Use this order rather than simply numerical order:

``` text
1.  Q1  Dynamic subtasks
2.  Q2  Agent-to-agent delegation
3.  Q3  Intelligent agent routing
4.  Q4  Dynamic tool switching

5.  Q7  Universal evidence enforcement
6.  Q8  Facts vs assumptions

7.  Q9  Production completion gate
8.  Q10 Dependency gate
9.  Q11 Documentation gate

10. Q5  Distributed AgentRegistry PoC
11. Q6  Horizontal scaling

12. Q16 Universal checkpoint/recovery

13. Q12 PTY
14. Q13 Multi-terminal
15. Q14 Windows CI

16. Q15 Human takeover
17. Q17 Memory lifecycle
18. Q18 Large repository engineering

19. Q19 Dependency-aware dispatch + metrics
20. Q25 Architecture protection
21. Q26 Branch/repository context

22. Q22 Conversational repeat
23. Q23 Documentation lookup
24. Q21 Company Brain
25. Q20 Governance

26. Q24 Agent health intelligence

27. Q27 Multi-tenancy — only when commercializing
28. Q28 Per-user analytics — only when commercializing

29. Q29 Production deployment validation
30. Q30 Security red-team
31. Q31 Production load test

32. FINAL 519-CHECKPOINT RE-AUDIT
```

------------------------------------------------------------------------

# 15. DEFINITION OF DONE

After EVERY prompt, all applicable boxes must be true:

-   [ ] Current source was inspected first.
-   [ ] Exact affected files/functions/classes were identified.
-   [ ] Existing mechanisms were reused where appropriate.
-   [ ] Real implementation exists.
-   [ ] No placeholders/stubs/fake success.
-   [ ] Tests were written.
-   [ ] Tests were actually executed.
-   [ ] Actual test output was inspected.
-   [ ] Full relevant regression suite passes.
-   [ ] Linter passes.
-   [ ] Type checker passes.
-   [ ] Security boundaries remain intact.
-   [ ] HITL/approval boundaries remain intact.
-   [ ] Sandbox remains intact.
-   [ ] Backward compatibility is preserved unless explicitly changed.
-   [ ] Concurrency tests exist where concurrency matters.
-   [ ] Failure-injection tests exist where failure matters.
-   [ ] Multi-instance tests exist where distributed behavior matters.
-   [ ] Crash/recovery tests exist where recovery matters.
-   [ ] Evidence report identifies file:line evidence.
-   [ ] Original audit checkpoint mapping is updated.
-   [ ] No existing YES checkpoint regressed.

If any required box is unchecked:

> **STATUS = PARTIAL**

Never upgrade to YES until the missing evidence exists.

------------------------------------------------------------------------

# 16. FINAL 519-CHECKPOINT RE-AUDIT

This step is mandatory.

After all roadmap programs are implemented, re-run the original audit
against the CURRENT codebase.

For every one of the 519 checkpoints classify:

``` text
YES
PARTIAL
NO
SKIP
```

Definitions:

YES: - capability fully implemented - integrated - enforced where
required - tests exist - tests executed - evidence exists - no known
material gap

PARTIAL: - capability exists but incomplete - integration incomplete -
enforcement incomplete - test/evidence incomplete - production behavior
not fully proven

NO: - capability is not implemented

SKIP: - deliberately out of scope - architectural boundary -
intentionally human-controlled - explicitly excluded by product decision

Produce a final table:

  Metric      Original   Final   Change
  --------- ---------- ------- --------
  YES              394       ?        ?
  PARTIAL           61       ?        ?
  NO                14       ?        ?
  SKIP              50       ?        ?
  TOTAL            519     519        0

Then produce:

1.  All remaining PARTIAL checkpoints.
2.  All remaining NO checkpoints.
3.  All preserved SKIP checkpoints and why.
4.  Every original YES that regressed.
5.  Every upgraded checkpoint with file:line evidence.
6.  Every upgraded checkpoint with executed-test evidence.
7.  Security findings.
8.  Performance/load-test results.
9.  Recovery results.
10. Multi-instance results.
11. Windows CI result.
12. Production deployment result.
13. Final known limitations.
14. Final production-readiness recommendation.

The final audit is the source of truth.

------------------------------------------------------------------------

# 17. FINAL SUCCESS CRITERIA

Do NOT call GridIron "production ready" merely because all roadmap
prompts were completed.

The final recommendation should be based on:

### Architecture

-   distributed coordination proven
-   dynamic orchestration proven
-   recovery proven

### Safety

-   evidence-first enforcement
-   security gates
-   HITL boundaries
-   sandbox boundaries
-   approval controls

### Reliability

-   crash recovery
-   restart recovery
-   orphan recovery
-   multi-instance consistency

### Engineering quality

-   tests
-   lint
-   type checking
-   architecture checks
-   dependency checks
-   documentation checks

### Product experience

-   interactive terminal
-   multi-terminal
-   streaming
-   human takeover
-   conversational task history

### Intelligence

-   memory-aware routing
-   memory lifecycle
-   dependency-aware dispatch
-   agent health
-   company knowledge

### Commercial readiness

-   tenant isolation where required
-   user cost attribution
-   deployment validation
-   security red-team
-   load testing

### Audit

The final 519-checkpoint audit must show the actual state.

------------------------------------------------------------------------

# 18. CLAUDE CODE FINAL REPORT FORMAT

At the end of every program, return:

``` text
============================================================
GRIDIRON PRODUCTION IMPLEMENTATION REPORT
============================================================

PROGRAM:
Q__

STATUS:
YES / PARTIAL / NO

IMPLEMENTED:
- ...

FILES CHANGED:
- path/file.py:line
- ...

DATABASE:
- migrations:
- schema changes:

TESTS ADDED:
- ...

TESTS EXECUTED:
$ command
actual result

REGRESSION:
- full suite:
- lint:
- type check:

SECURITY:
- ...

CONCURRENCY / RECOVERY:
- ...

AUDIT CHECKPOINTS AFFECTED:
- #...
- #...

CHECKPOINT STATUS:
- #... YES
- #... PARTIAL
- #... NO

REMAINING GAPS:
- ...

DELIBERATELY NOT IMPLEMENTED:
- ...

WHY:
- ...

REGRESSION CHECK:
Existing YES capabilities affected:
- NONE
or
- #... explanation

EVIDENCE QUALITY:
REAL EXECUTED EVIDENCE / INCOMPLETE
============================================================
```

------------------------------------------------------------------------

# 19. IMPORTANT OPERATING PRINCIPLE

GridIron should not become "better" by making audit checkboxes say YES.

It becomes better by making the underlying system:

``` text
MORE CAPABLE
     +
MORE VERIFIABLE
     +
MORE RECOVERABLE
     +
MORE SECURE
     +
MORE SCALABLE
     +
MORE OBSERVABLE
     +
MORE HUMAN-CONTROLLABLE
     +
MORE PRODUCT-READY
```

The audit is the measurement system.

The codebase is the product.

The executed evidence is the proof.
