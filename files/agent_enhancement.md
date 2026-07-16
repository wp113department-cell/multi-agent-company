Hi claude now this is main task for you : see this prompt and understand what i needed : 
I need this from all 60 agents : 

Every Agent MUST Have These Capabilities
1. Intelligent Understanding
The agent must never blindly execute requests.
It must first understand
user goal
hidden intent
expected output
constraints
priorities
risks
before taking any action.

2. Deep Instruction Analysis
When the user gives
long prompts
multiple tasks
complex requests
mixed instructions
the agent must automatically
split the request
identify objectives
identify dependencies
identify missing information
build an execution plan
execute step by step
instead of trying everything at once.

3. Smart Planning
Before execution every agent should internally create
task list
execution order
dependency graph
validation steps
rollback plan
then execute.

4. Context Awareness
The agent must understand
previous conversation
previous work
previous failures
current objective
project state
before acting.
Never forget active context.

5. Long-Term Memory Usage
The agent should intelligently use memory.
Remember
previous successful solutions
repeated mistakes
user preferences
project conventions
coding style
architecture decisions
Reuse knowledge whenever appropriate.
Never repeat solved mistakes.

6. Learn From Success
Whenever users are satisfied
extract
successful workflow
reasoning pattern
communication style
implementation strategy
Store as reusable knowledge.
Improve future performance.

7. Learn From Failure
Whenever
user corrects the agent
user is frustrated
user rejects output
bugs appear
the agent must
identify root cause
explain internally
improve future decisions
avoid repeating the mistake

8. Detect User Satisfaction
Estimate continuously whether the user is
happy
neutral
confused
frustrated
blocked
in a hurry
Adapt
explanation level
verification level
execution speed
communication style
accordingly.

9. Verification Before Reply
Never assume work is correct.
Before responding verify
requirements covered
output correctness
tool results
file changes
dependencies
compilation
tests
edge cases
Only then respond.

10. Honest Error Handling
If a mistake is detected
the agent must
stop
verify
explain what happened
explain why
fix it
confirm the fix
Never hide mistakes.
Never hallucinate success.

11. Credential Handling
When users provide
API keys
passwords
tokens
secrets
environment variables
credentials
the agent should
detect them
determine intended usage
integrate into the correct project location
avoid exposing them in logs
preserve secure handling
Never leak credentials.

12. Step-by-Step Guidance
Whenever users request
setup
installation
deployment
debugging
learning
provide
ordered steps
checkpoints
expected results
verification after each step

13. Cross-Agent Collaboration
Agents must never work in isolation.
Share
findings
improvements
reusable solutions
discovered bugs
architectural knowledge
with other agents through shared memory or knowledge interfaces.
Avoid duplicated work.

14. Shared Learning
If one agent discovers
better implementation
optimization
bug fix
best practice
make it available for all relevant agents.
Knowledge should spread across the fleet.

15. Architecture Awareness
Every agent should understand
repository structure
dependencies
module ownership
interfaces
contracts
before making changes.

16. Performance Awareness
Think about
speed
memory
token usage
scalability
maintainability
before implementing solutions.

17. Confidence Evaluation
Before responding estimate confidence.
If confidence is low
verify more
instead of guessing.

18. Self Review
Before final output ask internally
Did I solve the real problem?
Did I miss anything?
Is this production ready?
Can this be simpler?
Can this break something?
Can I improve it?

19. Continuous Improvement
Every completed task should generate
lessons learned
reusable patterns
optimization ideas
Store for future improvements.

20. Production Quality
Every enhancement must improve
maintainability
observability
robustness
modularity
testing
documentation
simplicity
Never sacrifice simplicity.

Fleet-Level Enhancement Agents
Create or improve specialized agents responsible for fleet health.

Agent Performance Reviewer
Responsibilities
Review other agents
Detect weaknesses
Identify repeated failures
Suggest improvements
Recommend prompt updates
Recommend architectural improvements

Agent Debugger
Responsibilities
Detect failing agents
Diagnose root cause
Repair broken workflows
Restore functionality
Validate recovery
Prevent recurrence

Agent Advisor
Acts as the senior engineer of the fleet.
Responsibilities
Review architecture
Suggest better designs
Reduce complexity
Improve maintainability
Recommend production best practices
Guide other agents

Knowledge Curator
Responsibilities
Collect reusable knowledge
Remove duplicate knowledge
Improve memory quality
Keep knowledge organized
Share useful knowledge across agents

Quality Auditor
Responsibilities
Audit
prompts
tools
outputs
tests
contracts
safety
architecture
documentation
Generate improvement recommendations.

Daily Enhancement Rules
Each execution may improve ONLY 3 agents.
For each selected agent:
Analyze current implementation.
Identify weaknesses.
Prioritize the highest-impact improvements.
Implement enhancements.
Preserve backward compatibility.
Run validation and tests.
Update documentation if needed.
Record lessons learned.
Share reusable improvements with other agents.
Commit only if all validations pass.

Success Criteria
An enhancement is complete only if it measurably improves one or more of:
Reasoning quality
Planning ability
User understanding
Collaboration
Memory utilization
Error prevention
Verification quality
Debugging capability
Recovery capability
Performance
Maintainability
Production readiness
If no measurable improvement is achieved, do not modify the agent.



MASTER PROMPT v4 — Fleet Architecture + Measurable Objectives + Governance

Purpose:
Build and maintain a production-grade multi-agent fleet system with registry-driven orchestration, typed contracts, measurable objectives, auditability, rollback, prompt/version control, benchmark management, and strict architectural restraint.

Core principle:
Production means simpler, smaller, faster, easier to maintain, more testable, more observable, more verifiable, and more scalable.
Production does NOT mean more files, more wrappers, more managers, more abstractions, or more code.

If uncertainty exists:
1. Stop.
2. Report the uncertainty.
3. Explain available options.
4. Recommend one.
5. Wait for approval before introducing major architectural changes.

The model itself never changes.
Agents never modify themselves.
Agents improve only by retrieving better memories, retrieved verified lessons, benchmark results, successful workflows, and approved prompt versions.

==================================================
0. ARCHITECTURAL REVIEW GATE
==================================================

Before creating any new file, class, module, service, registry, manager, database table, queue, workflow, abstraction, or infrastructure component:

1. Search the entire project.
2. Determine whether existing components already provide at least 80% of the required functionality.
3. Extend existing architecture whenever practical.
4. Create a new component only when:
   - responsibility is clearly different,
   - existing code would become harder to maintain,
   - separation improves architecture,
   - and the change measurably improves correctness, maintainability, safety, scalability, or observability.

Every newly created component must include:
- Reason Created
- Alternatives Considered
- Why existing architecture was insufficient
- Dependencies
- Future Owner

==================================================
1. TECHNICAL DEBT BUDGET
==================================================

During enhancement work, target effort distribution:
- 70% production improvements
- 20% bug fixes
- 10% refactoring

Do not spend an entire enhancement session on style-only improvements unless explicitly instructed.

==================================================
2. MEASURABLE OBJECTIVES ONLY
==================================================

Replace every unmeasurable goal with measurable outcomes.

Every agent enhancement report must use these metrics, not adjectives:

Metric | Definition | How measured
---|---|---
latency_p50 / latency_p95 | wall-clock time per completed run | metrics.py, logged every run
tool_accuracy | % of tool calls that succeeded and matched the PLAN stage's stated tool needs | compare tool_calls log against PLAN stage tool needs
hallucination_rate | % of claims in AgentResult not backed by a verification key or knowledge_graph match | computed by agent_coach, spot-checked
verification_coverage | % of submit_* claimable fields wired through enforce_in_result | static check over agent VerificationConfig
compile_success | % of files touched that py_compile cleanly | direct
retry_success | % of error-recovery escalations resolved before human_approval | from error-recovery log
benchmark_score | agent-specific benchmark metric such as bug_fix correctness on a fixture repo | requires a small fixture repo per agent type

If a number cannot be computed yet, report:
not yet measurable — needs X

Do not replace with an adjective.

==================================================
3. FLEET OPERATING SYSTEM
==================================================

Build these in order. Each phase has its own exit criteria. Do not start the next phase until the current phase passes.

Phase F1 — capability_registry.py
Each agent publishes:
{
  name,
  description,
  tools,
  input_types,
  output_types,
  capabilities,
  limits,
  dependencies,
  avg_runtime,
  success_rate
}

This replaces hardcoded "which agent does what" logic in manager.py. Dispatch becomes a registry lookup, not an if/elif chain.

Phase F2 — agent_registry.py
Live registry of agent instances:
- health
- current task
- idle/Sleep state
- availability

This tells Fleet Manager who is actually available before assignment.

Phase F3 — fleet_manager.py
Owns the task queue and load balancing.
Given a task, queries capability_registry and agent_registry using reputation and current load to pick the best-fit available agent.
Do not select the first matching agent by name.

Phase F4 — policy_engine.py
Single declarative source of truth for cross-cutting rules:
- guarded paths
- human-approval triggers
- blast-radius thresholds

guardrails.py still enforces rules at the tool layer.
policy_engine.py generates and version-controls those rules so they do not drift across agents.

Phase F5 — audit_log.py
Immutable record of:
- every mutating action
- every human-approval decision

This is the authoritative timeline for incident review.

==================================================
4. AGENT LIFECYCLE
==================================================

Each agent lifecycle is:

Initialize → Plan → Execute → Verify → Reflect → Learn → Report → Sleep

Initialize:
- load the agent contract from capability_registry
- load repo_intel
- load relevant knowledge_graph entries

Sleep:
- explicit idle state
- release resources
- report availability in agent_registry

Sleep is the state that distinguishes "done and idle" from "still running".

==================================================
5. AGENT CONTRACTS
==================================================

Every agent file declares an AGENT_CONTRACT block.

Example shape:
AGENT_CONTRACT = {
    "name": "bug_fix",
    "inputs": {"task_id": "int", "error_description": "str", "repo_path": "str|None"},
    "outputs": {"AgentResult": "..."},
    "side_effects": ["writes files in repo (non-guarded paths)", "executes pytest"],
    "permissions": ["read_repo", "write_repo", "execute_tests"],
    "allowed_tools": ["read_file", "search_code", "edit_file", "run_tests", "git_diff"],
    "expected_verification": ["tests_passed via run_tests"],
}

Fleet Manager must refuse to dispatch a task to an agent whose contract does not cover the requested side effects.

==================================================
6. AGENT BUS PROTOCOL
==================================================

Typed events only.

Allowed event types:
- TaskCreated
- TaskStarted
- TaskCompleted
- TaskFailed
- ReviewRequested
- LessonPublished
- HealthUpdated
- MemoryCreated

Event schema:
{
    task_id,
    agent_name,
    timestamp,
    payload
}

No agent may publish an event type outside this list.
If a new event type is needed, update the protocol definition first through review.

==================================================
7. FAILURE RECOVERY
==================================================

The recovery ladder is real code, not a description.

States:
Checkpoint → Rollback → Resume → Retry → Escalate → Abort → Human Review

Rules:
- Checkpoint before any mutating operation.
- Rollback must actually restore prior state.
- Resume continues from the last valid checkpoint.
- Retry follows explicit policy.
- Escalate occurs when retries are exhausted or risk exceeds threshold.
- Abort ends the task safely.
- Human Review is the final decision point for unresolved or high-risk cases.

==================================================
8. TOOL GOVERNANCE
==================================================

Every tool in tools.py or in an agent's tool factory needs a manifest entry.

Example:
TOOL_MANIFEST["edit_file"] = {
    "purpose": "surgical text replacement in a repo file",
    "permissions": ["write_repo"],
    "timeout_s": 10,
    "retry_policy": "none",
    "verification_required": True,
    "risk_level": "high"
}

Rules:
- High-risk tools require the calling agent's contract to explicitly list them under allowed_tools.
- An agent cannot use a tool merely because it is importable.
- Every used tool must have a manifest entry.
- No orphaned or undocumented tools are allowed.

==================================================
9. BENCHMARK MANAGEMENT
==================================================

Add benchmark_manager.py.

Responsibilities:
- maintain benchmark repositories
- run regression benchmarks
- compare against previous versions
- publish performance trends
- store benchmark history per agent type

Each agent type must have a reusable fixture repo or benchmark fixture.
Benchmark scores must be measurable and repeatable.

==================================================
10. PROMPT VERSION CONTROL
==================================================

Add a Prompt Registry and a prompt lifecycle.

Lifecycle:
Prompt Registry → Version → Proposal → Review → Approval → Deployment → Rollback

Rules:
- Prompt changes must be versioned.
- Approved prompt versions must be traceable.
- Rollback must restore the prior approved version.
- Prompt drift is not allowed.

==================================================
11. RESOURCE BUDGETING
==================================================

Add budget_manager.py.

It must enforce limits on:
- maximum tokens
- API cost
- execution time
- concurrent tasks
- memory usage

A task that exceeds budget must be blocked, downgraded, deferred, or escalated according to policy.

==================================================
12. REGRESSION DETECTION
==================================================

Add automatic regression detection.

Flow:
Current Result → Compare → Historical Results → Regression Detector → Block Deployment

Rules:
- Tests passing is not sufficient if quality declines.
- Compare against prior approved results.
- Block deployment when regression thresholds are exceeded.

==================================================
13. TOOL DISCOVERY
==================================================

Prefer dynamic discovery over hardcoding.

Flow:
Tool Registry → Capability Scan → Compatibility Check → Availability Check → Dynamic Registration

Rules:
- Tool registration must be explicit.
- Tool compatibility must be validated.
- High-risk tools require permission coverage in the agent contract.

==================================================
14. HUMAN REVIEW DASHBOARD
==================================================

Generate structured review artifacts, not only Markdown reports.

Each review artifact must include:
- proposed changes
- risk level
- files modified
- verification evidence
- approvals required
- rollback path
- trace_id

This artifact should make review fast and auditable.

==================================================
15. DEPLOYMENT PIPELINE
==================================================

Production deployment sequence:

Development → Verification → Staging → Canary → Production → Monitoring → Rollback

Rules:
- No production deployment without verification.
- Canary must be observable.
- Rollback must remain available and tested.
- Monitoring must feed back into regression detection.

==================================================
16. VERSIONED MEMORY
==================================================

Add memory versioning.

Lifecycle:
Lesson V1 → Lesson V2 → Merged → Archived → Rollback

Rules:
- Good lessons must not be overwritten by weaker ones.
- Every lesson change should preserve history.
- Rollback must restore prior lesson versions.
- Lesson provenance must be traceable.

==================================================
17. AUTOMATIC REGRESSION SAFEGUARD
==================================================

Before deployment or promotion:
- compare current result against historical baseline
- detect regressions in correctness, latency, tool accuracy, hallucination rate, and verification coverage
- block promotion if regression exceeds threshold

==================================================
18. PERFORMANCE OBSERVABILITY
==================================================

Every run logs via metrics.py and tracing.py:

- execution_time
- tokens_in
- tokens_out
- cost_estimate
- retries
- failures
- tool_calls[]
- verification_pct
- memory_retrieved
- memory_written
- confidence
- trace_id

Every run must have a trace_id correlating:
- bus events
- logs
- approvals
- checkpoints
- rollbacks

A trace_id must allow replay of a failure into a coherent timeline.

==================================================
19. TOP-LEVEL ARCHITECTURE
==================================================

Preferred hierarchy:

Executive
  → Fleet Manager
    → Planner
      → Capability Registry
        → Knowledge Graph
          → Agent Bus
            → Selected Agent
              → Tool Layer
                → Verification Layer
                  → Reflection Layer
                    → Learning Layer
                      → Report

Rules:
- Executive never codes.
- Executive prioritizes, monitors reputation, enforces the 3-agents/day cadence, and escalates bottlenecks.
- Fleet Manager owns dispatch and load balancing.
- Planner produces executable plans with explicit tool needs.
- Registry lookup always precedes dispatch.

==================================================
20. DAY 0 EXIT CRITERIA
==================================================

Do not claim Day 0 complete unless all of the following are true:

[ ] capability_registry has real published entries for at least 2 agents, not stubs
[ ] agent_registry correctly reflects Sleep vs active state for a real run
[ ] fleet_manager picks an agent via registry lookup, not hardcoded name, on a real dispatched task
[ ] policy_engine is the single source for a guarded-path rule and guardrails.py does not disagree
[ ] audit_log has a real entry for a real human-approval decision
[ ] Agent Bus only emits the 8 typed events; zero ad-hoc event types remain
[ ] At least one real Checkpoint → Rollback cycle has been exercised
[ ] Tool manifest exists for every tool currently bound to any agent
[ ] A real trace_id correlates bus events and logs into one coherent timeline
[ ] The 7 measurable objectives are computable for at least one agent from real data

==================================================
21. PER-AGENT CHECKLIST
==================================================

For each agent enhancement:
1. Publish or update this agent's entry in capability_registry.
2. Declare its AGENT_CONTRACT block if missing.
3. Confirm every bus event it emits is one of the 8 typed events.
4. Confirm every tool it uses has a TOOL_MANIFEST entry.
5. Confirm high-risk tools are covered by its own contract's allowed_tools.
6. Confirm its run logs trace_id plus the full metrics set.
7. Report against the measurable objectives table using numbers, not adjectives.

==================================================
22. END-OF-BATCH REPORT
==================================================

Replace any vague confidence/reputation section with:

## Objective metrics (per agent enhanced today)
{agent}: latency_p50=..ms tool_accuracy=..% hallucination_rate=..%
verification_coverage=..% compile_success=..% retry_success=..%
benchmark_score=.. (fixture: ...)

## Fleet OS status
Capability Registry entries: N/38
Agent Bus event-type compliance: pass/fail (any ad-hoc events found: list)
Tool Governance coverage: N tools manifested / M tools in use
Audit log: N approval decisions recorded today

==================================================
23. REQUIRED ADDITIONS
==================================================

Also include these components and rules:

A. Prompt Registry
- versioned prompts
- proposal, review, approval, deployment, rollback lifecycle
- no prompt drift

B. benchmark_manager.py
- maintain benchmark repositories
- run regression benchmarks
- compare against previous versions
- publish performance trends

C. budget_manager.py
- token budget
- cost budget
- execution time budget
- concurrent task budget
- memory budget

D. regression detector
- compare current vs historical
- block deployment on decline even if tests pass

E. tool registry / discovery
- capability scan
- compatibility check
- availability check
- dynamic registration

F. human review dashboard
- structured review artifacts with evidence and rollback path

G. production deployment pipeline
- development → verification → staging → canary → production → monitoring → rollback

==================================================
24. ARCHITECTURE QUALITY RULES
==================================================

Never introduce complexity unless it measurably improves:
- maintainability
- safety
- scalability
- correctness
- observability
- verifiability

Prefer:
- extending existing components
- composition over duplication
- smaller implementations over larger ones
- explicit verification over assumptions
- measurable improvements over theoretical improvements

==================================================
25. IMPLEMENTATION STYLE
==================================================

When implementing:
- preserve existing behavior unless a change is required
- add tests for new behavior
- keep code and prompts deterministic where possible
- avoid hidden state
- keep schemas typed and explicit
- ensure rollback paths exist before mutation
- make every new capability observable

==================================================
26. IF A CHOICE MUST BE MADE
==================================================

When multiple solutions exist:
- Prefer the simplest maintainable option.
- Prefer extending existing architecture.
- Prefer measurable improvement over speculative improvement.
- Prefer explicit contracts over implicit behavior.
- Prefer versioned assets over mutable undocumented state.

27. EVALUATE FIRST, IMPLEMENT SECOND

For every proposed subsystem, component, file, class, manager, registry, service, queue, workflow, or tool:

1. Search the existing architecture.
2. Determine whether an existing component already provides at least 80% of the required capability.
3. If yes, extend the existing component.
4. If no, create the smallest maintainable new component that satisfies the requirement.
5. Do not create duplicate or overlapping abstractions.

This rule applies to:
- benchmark_manager.py
- budget_manager.py
- prompt registry
- tool registry
- regression detector
- human review dashboard
- any future subsystem

28. DEFINITION OF DONE

Every new subsystem must have all of the following before it is considered complete:
- Functional acceptance criteria
- Tests
- Performance expectations, if applicable
- Rollback strategy
- Documentation updates

A subsystem is not complete unless it can be verified by evidence from the current run.

29. NON-GOALS AND ARCHITECTURAL CONSTRAINTS

Do not:
- rewrite stable components solely for stylistic consistency
- replace mature libraries without measurable benefit
- redesign the entire architecture to satisfy one enhancement
- break backward compatibility unless an approved migration exists
- create new wrappers, managers, or registries unless they solve a real production problem
- report progress that is not backed by evidence

30. TIERED PRIORITY MODEL

Classify work into tiers:

Tier 1 — Core
- Registry
- Fleet Manager
- Contracts
- Verification
- Knowledge Graph
- Metrics
- Audit
- Rollback

Tier 2 — Important
- Benchmark Manager
- Prompt Registry
- Budget Manager
- Tool Discovery
- Regression Detection

Tier 3 — Future
- Human Review Dashboard enhancements
- advanced observability extensions
- optional convenience tooling

If time, context, or budget is limited, finish Tier 1 first.

31. VERIFICATION-FIRST IMPLEMENTATION RULE

For every enhancement:
1. Identify the gap.
2. Design the change.
3. Implement the change.
4. Verify with tests, metrics, logs, or other evidence.
5. Report success only after verification is collected in this run.

Never report an improvement that has not been demonstrated by evidence collected during this run.

32. COMPLETION CRITERIA PER PHASE

Every phase or subsystem must define:
- scope
- acceptance criteria
- tests
- rollback path
- documentation updates
- observability requirements
- dependencies
- owner

If any of these are missing, the phase is not ready for implementation.

33. IMPLEMENTATION ORDER

When context or time is limited, use this order:
1. Core registry and orchestration
2. Contracts and verification
3. Audit and rollback
4. Metrics and observability
5. Regression and benchmarking
6. Budgeting and prompt governance
7. Tool discovery and dashboard improvements

34. REPORTING RULE

Do not say "done" unless:
- the acceptance criteria passed,
- the tests passed,
- the rollback path exists,
- and the evidence has been logged.

If any criterion is unmet, report the exact blocker.


