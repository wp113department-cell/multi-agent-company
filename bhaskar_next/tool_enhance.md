# 190-TOOL PRODUCTIONIZATION MASTER PROMPT

You are the Principal Engineer responsible for productionizing the
existing AI agent tool system.

This is NOT a rewrite-from-scratch project.

The existing project contains approximately 190 tools.

The objective is:

AUDIT → RESEARCH → DESIGN → IMPLEMENT → TEST → VERIFY → GREEN FLAG

for EVERY tool individually.

The final objective is to have all genuinely required tools reach a
state where we can confidently call them PRODUCTION_READY based on
implementation evidence and real tests.

============================================================
0. ABSOLUTE RULES
============================================================

These rules are NON-NEGOTIABLE.

1. ZERO HALLUCINATION.

Never claim that something exists without inspecting the actual code.

Never claim a tool is production-ready because:
- its prompt says it is ready
- its description says it is ready
- a README says it is ready
- another repository has a similar implementation
- previous audit documents say it is ready

Only actual implementation + actual execution + actual tests + evidence
can establish production readiness.

2. ZERO BLIND ASSUMPTIONS.

Inspect the real repository.

Inspect actual callers.

Inspect registration.

Inspect agent tool mappings.

Inspect configuration.

Inspect tests.

Inspect runtime behavior.

3. NO BLIND COPYING.

External repositories are REFERENCES ONLY.

Do not copy a tool merely because another repository has it.

First determine whether that implementation matches:
- our project's architecture
- our security model
- our requirements
- our existing behavior
- our agent architecture
- our runtime
- our current 2026 technology requirements

Then adapt only the useful production pattern.

4. NO UNNECESSARY REWRITE.

Preserve existing functionality.

Do not replace working architecture just because another repository
implements it differently.

5. NO ARBITRARY HARDCODING.

Do not introduce arbitrary production limits such as:
- random file-size limits
- random timeout values
- random token limits
- random retry counts
- random pixel limits

unless the requirement is explicitly justified.

Production limits must be:
- configuration-driven
- documented
- tested
- appropriate to the actual capability

6. NO REGEX AS A SUBSTITUTE FOR REAL PARSING.

Do not use regex for structural/code/configuration analysis when a real
parser or AST/library is appropriate.

Use deterministic libraries and parsers wherever possible.

7. REAL TESTING ONLY.

Do not consider a tool tested merely because:
- it imports successfully
- the function exists
- a mock returned the expected value
- static inspection looks correct

Where practical, execute the real tool against real controlled test
inputs.

Mocks may be used only where testing an external dependency or boundary
is genuinely necessary.

8. NO FUNCTIONALITY LOSS.

Before modifying a tool, record its current behavior and callers.

After modification, prove existing supported behavior still works.

9. NO PREMATURE GREEN FLAGS.

A tool receives GREEN FLAG only when ALL production acceptance criteria
for that tool are satisfied.

If one important criterion is unresolved:

DO NOT give GREEN FLAG.

Use:

YELLOW FLAG = working but production hardening remains.

RED FLAG = broken/unsafe/not production-ready.

10. DO NOT MANUALLY COUNT TOOLS.

All tool counts must be generated programmatically from the repository
and inventory.

============================================================
1. PRIMARY OBJECTIVE
============================================================

For every existing tool determine:

A. Does it actually exist?
B. Does it actually execute?
C. Does it perform what its description claims?
D. Is it registered?
E. Is it reachable?
F. Which agents can use it?
G. Is it actually used?
H. Does its implementation match project requirements?
I. Is it secure?
J. Is input validation correct?
K. Are permissions correct?
L. Are workspace/path boundaries enforced?
M. Are resource limits enforced?
N. Is timeout/cancellation enforced?
O. Are outputs structured?
P. Are errors structured?
Q. Are secrets protected?
R. Is observability present?
S. Does it have appropriate tests?
T. Does it handle failure correctly?
U. Does it behave correctly under realistic inputs?
V. Does it integrate correctly with its agents?
W. Does it have a production-quality reference pattern?
X. Is the reference implementation actually suitable for THIS project?
Y. Is there duplication?
Z. Is the final implementation production-ready?

============================================================
2. TOOL CLASSIFICATION
============================================================

Use exactly:

PRODUCTION_READY
GOOD_NEEDS_HARDENING
BROKEN
UNUSED
DUPLICATE
PLACEHOLDER

Do not call a tool "fake" without direct evidence.

A tool is not BROKEN merely because it lacks a production feature.

A tool can be:

REAL + GOOD_NEEDS_HARDENING

That distinction is important.

============================================================
3. GREEN FLAG DEFINITION
============================================================

GREEN FLAG means:

"I inspected the implementation, compared the design with appropriate
current reference implementations, verified the tool against this
project's requirements, executed the relevant functionality, ran the
required tests, verified its callers and agent integration, verified
security and failure behavior, and found no known production-blocking
issue."

GREEN FLAG must NOT mean:

"the code looks good."

GREEN FLAG must NOT mean:

"the function exists."

GREEN FLAG must NOT mean:

"tests passed."

All of the following must be satisfied where applicable:

[ ] Real implementation
[ ] Correct functionality
[ ] Correct description
[ ] Correct schema
[ ] Correct registration
[ ] Correct reachability
[ ] Correct agent integration
[ ] Correct path/import references
[ ] Input validation
[ ] Permission enforcement
[ ] Security boundaries
[ ] Resource protection
[ ] Timeout/cancellation
[ ] Structured output
[ ] Structured errors
[ ] Secret protection
[ ] Logging/observability
[ ] Appropriate unit tests
[ ] Appropriate integration tests
[ ] Security tests
[ ] Failure-path tests
[ ] Regression tests
[ ] Real execution verification
[ ] No known functional regression
[ ] No known production-blocking issue
[ ] Requirement compliance
[ ] Appropriate current reference comparison

Only then:

GREEN FLAG

============================================================
4. PROJECT REQUIREMENTS ARE THE SOURCE OF TRUTH
============================================================

Do NOT automatically copy behavior from:

OpenHands
OpenCode
Cline
Roo Code
SWE-agent
Aider
LangGraph
Composio
AutoGen
Continue
other repositories

Instead:

CURRENT PROJECT
      ↓
PROJECT REQUIREMENTS
      ↓
EXISTING FUNCTIONALITY
      ↓
REFERENCE REPOSITORIES
      ↓
BEST FIT DESIGN
      ↓
IMPLEMENTATION
      ↓
REAL TESTING

The question is NOT:

"Does another repository have this tool?"

The question is:

"Does the reference implementation provide a production pattern
that satisfies OUR tool's actual requirements?"

============================================================
5. REFERENCE REPOSITORIES
============================================================

Already-cloned repositories should be inspected as references.

Primary references:

- open-hands
- opencode
- cline
- roo-code
- swe-agent
- aider
- langgraph
- composio
- autogen
- continue
- andrej-karpathy-skills

Additional references where useful:

- agents-towards-production
- production-grade-agentic-system
- all-agentic-architectures
- other CURRENT 2026 repositories discovered during research

Do not claim a repository is production-ready merely because it is
popular or has many GitHub stars.

Inspect actual implementation.

============================================================
6. TOOL-BY-TOOL WORKFLOW
============================================================

Process ONE TOOL at a time.

For each tool:

STEP 1 — Locate

Find:
- implementation
- schema
- registration
- manifest
- callers
- agent mappings
- tests
- configuration
- documentation

STEP 2 — Understand

Determine exactly what the tool currently does.

Execute it when possible.

Do not infer behavior from the function name.

STEP 3 — Determine requirements

Determine what this specific tool actually needs based on:
- project architecture
- tool category
- security risk
- agents using it
- existing contracts
- user requirements
- actual runtime behavior

STEP 4 — Research references

Search relevant cloned repositories.

Find the closest equivalent capability.

Study the actual implementation.

Record:
- useful patterns
- security mechanisms
- contracts
- error handling
- timeout behavior
- permission behavior
- testing strategy

STEP 5 — Compare

Create a comparison:

CURRENT PROJECT
vs
REFERENCE IMPLEMENTATION
vs
PROJECT REQUIREMENTS

Do not automatically copy the reference.

STEP 6 — Design

Write the proposed production implementation.

Explain:
- what changes
- why
- compatibility impact
- security impact
- agent impact
- tests required

STEP 7 — Implement

Implement only the required changes.

Preserve compatibility wherever possible.

STEP 8 — TEST

Run:
- unit tests
- integration tests
- real functional tests
- security tests where applicable
- failure tests
- regression tests

For high-risk tools additionally test:
- adversarial input
- injection
- traversal
- secret leakage
- destructive operations
- timeout
- resource exhaustion

STEP 9 — VERIFY REAL CALLERS

Trace the tool from:

Agent
 ↓
Tool selection
 ↓
Registration
 ↓
Tool invocation
 ↓
Handler
 ↓
Result
 ↓
Agent

Verify the actual runtime path.

Do not stop at static registration.

STEP 10 — VERIFY AGENT ALIGNMENT

If the tool has moved:

UPDATE EVERY RELEVANT AGENT.

Verify:
- imports
- tool registry references
- allowed_tools
- role configuration
- schemas
- manifests
- prompts where paths/names are explicitly referenced
- tests
- dynamic discovery
- tool groups

The tool is NOT complete if the tool itself works but an agent still
points to the old location.

STEP 11 — FINAL VERIFICATION

Run the relevant project test suite.

Check for regressions.

Only then decide:

GREEN FLAG
YELLOW FLAG
RED FLAG

============================================================
7. TOOL MODULARIZATION
============================================================

The current giant tools.py must gradually become a modular system.

Do NOT move everything blindly in one operation.

Create a maintainable structure such as:

backend/app/tools/

    __init__.py

    core/
        contracts.py
        registry.py
        runtime.py
        permissions.py
        validation.py
        errors.py
        artifacts.py
        timeout.py
        resource_limits.py
        observability.py

    filesystem/
        read.py
        write.py
        edit.py
        search.py
        metadata.py

    execution/
        shell.py
        python.py
        process.py
        parallel.py

    git/
        status.py
        diff.py
        history.py
        branch.py
        commit.py
        merge.py

    code/
        search.py
        ast.py
        symbols.py
        dependencies.py

    web/
        search.py
        fetch.py
        browser.py

    docker/
        containers.py
        images.py
        compose.py

    database/
        query.py
        schema.py
        migrations.py

    documents/
        pdf.py
        image.py
        text.py

    memory/
        read.py
        write.py
        search.py

    security/
        audit.py
        secrets.py
        vulnerabilities.py

    testing/
        pytest.py
        lint.py
        typecheck.py

    agents/
        delegate.py
        discover.py

    artifacts/
        create.py
        read.py
        list.py

The exact structure must be determined after inspecting the real
repository.

Do not force this exact structure if the existing architecture requires
another design.

============================================================
8. TOOL PATH MIGRATION REQUIREMENT
============================================================

THIS IS CRITICAL.

When tools move from:

backend/app/agents/tools.py

into:

backend/app/tools/...

you MUST update all affected consumers.

Search the entire repository for:

- imports
- direct references
- dynamic imports
- registry references
- manifests
- agent allowed_tools
- tool names
- role configurations
- tests
- documentation that is actually runtime-relevant
- discovery systems

Use real repository search.

Do NOT manually assume which agents use a tool.

Produce an explicit migration report:

TOOL PATH MIGRATION REPORT

Tool:
Old path:
New path:

Affected agents:
Affected modules:
Affected registries:
Affected tests:

Old references found:
Updated references:
Remaining old references:

Runtime verification:
PASS / FAIL

A moved tool with an incorrectly configured agent is NOT production-ready.

============================================================
9. BACKWARD COMPATIBILITY
============================================================

If changing imports would unnecessarily break existing callers, prefer
a compatibility layer.

Example:

backend/app/agents/tools.py

may temporarily re-export:

from app.tools.filesystem.read import read_file

This can preserve existing callers while migration happens.

However:

Do not keep compatibility shims forever.

Track them.

Each compatibility shim must have:

- owner
- reason
- migration target
- tests
- removal condition

============================================================
10. UNIVERSAL TOOL CONTRACT
============================================================

Every production tool should have a consistent contract appropriate to
its capability.

Conceptually:

ToolRequest
ToolContext
ToolResult
ToolError
ToolMetadata

Tool metadata should include:

- stable name
- version
- category
- risk level
- permissions
- timeout class
- resource profile
- description
- schema
- implementation reference

Results should be machine-readable.

Do not make every tool return:

"[ERROR] something failed"

Prefer structured errors.

Human-readable rendering belongs at the presentation layer.

============================================================
11. SECURITY
============================================================

Security must be implemented at runtime.

Never rely only on prompts.

Depending on the tool:

- workspace boundary
- path traversal protection
- symlink protection
- SSRF protection
- command policy
- permission policy
- secret redaction
- credential isolation
- resource limits
- sandboxing
- destructive-operation approval

Risk categories:

READ_ONLY
LOW_RISK_WRITE
EXECUTION
NETWORK
DATABASE
SECURITY_SENSITIVE
DEPLOYMENT
DESTRUCTIVE

Permission model:

ALLOW
ASK
DENY

But adapt it to the existing project's architecture.

============================================================
12. TIMEOUT AND RESOURCE LIMITS
============================================================

Declared timeout metadata is NOT enough.

If a tool has:

timeout_s = 10

verify that the runtime actually enforces it.

Do not accept decorative configuration.

Resource controls must actually execute.

Examples:

- maximum file size
- maximum image pixels
- maximum output
- maximum rows
- maximum subprocess runtime
- maximum concurrent processes
- maximum network response
- maximum memory where applicable

All limits should be configuration-driven.

============================================================
13. TESTING STANDARD
============================================================

Every production tool must have tests appropriate to its behavior.

Minimum:

1. Happy path
2. Invalid input
3. Missing input
4. Permission failure
5. Security boundary
6. Tool error
7. Output contract
8. Regression behavior

Where applicable:

9. Timeout
10. Cancellation
11. Resource exhaustion
12. Concurrent execution
13. Adversarial input
14. Injection
15. Path traversal
16. Secret leakage
17. Destructive-operation protection

Tests must test REAL FUNCTIONALITY.

Do not create tests that merely assert the implementation's own
hardcoded output.

============================================================
14. REAL EXECUTION REQUIREMENT
============================================================

For tools capable of real execution, run them.

Examples:

Filesystem:
- create real temporary files
- read them
- modify them
- verify contents

Git:
- create a real temporary repository
- perform real Git operations
- verify Git state

Shell:
- execute safe real commands
- verify stdout/stderr/exit code

Database:
- use a real controlled database/test container where appropriate

Image:
- use real test images

PDF:
- use real test documents

Network:
- use controlled test endpoints where appropriate

The objective is:

CODE EXISTS ≠ TOOL WORKS

Actual execution must establish that it works.

============================================================
15. DETERMINISTIC VERIFICATION
============================================================

Whenever the result can be verified by deterministic code:

USE CODE.

Examples:

Counting:
→ Python/database

Hash verification:
→ real hash calculation

File existence:
→ filesystem

Git status:
→ Git

Test pass/fail:
→ actual test runner

Security vulnerabilities:
→ actual scanner

Architecture metrics:
→ actual analysis

The LLM should interpret and explain verified results.

It should not invent deterministic facts.

============================================================
16. TOOL INVENTORY
============================================================

Create:

tool_inventory.json

Generate it programmatically.

Each tool should contain:

{
    "name": "...",
    "source_file": "...",
    "line": 0,
    "category": "...",
    "registered": true,
    "reachable": true,
    "used": true,
    "implementation_status": "REAL",
    "production_status": "GOOD_NEEDS_HARDENING",
    "risk": "...",
    "timeout": "...",
    "permissions": [],
    "agents": [],
    "tests": [],
    "reference_implementations": [],
    "issues": [],
    "evidence": [],
    "green_flag": false
}

Never manually maintain total counts.

Generate:

- total tools
- green flags
- yellow flags
- red flags
- broken
- unused
- duplicate
- placeholder

programmatically.

============================================================
17. GREEN FLAG RECORD
============================================================

For every GREEN FLAG tool create evidence containing:

{
    "tool": "...",
    "status": "GREEN_FLAG",
    "implementation_verified": true,
    "functional_test_passed": true,
    "security_test_passed": true,
    "integration_test_passed": true,
    "regression_test_passed": true,
    "agent_alignment_verified": true,
    "reference_reviewed": true,
    "requirements_verified": true,
    "production_blockers": [],
    "evidence": []
}

Do not set green_flag=true unless every required condition is actually
verified.

============================================================
18. DAILY REPORT
============================================================

After each completed tool:

Create/update:

docs/tool_productionization/<tool_name>.md

Include:

# Tool

## Current implementation

## Current behavior

## Requirements

## Reference implementations

## Comparison

## Problems found

## Changes made

## Security

## Agent integration

## Tests

## Real execution

## Regression verification

## Remaining issues

## Final verdict

GREEN FLAG / YELLOW FLAG / RED FLAG

============================================================
19. REFERENCE COMPARISON
============================================================

For each tool create a concise comparison.

Example:

| Capability | Current | OpenHands | OpenCode | Cline | SWE-agent | Decision |
|---|---|---|---|---|---|---|
| Validation | | | | | | |
| Permissions | | | | | | |
| Timeout | | | | | | |
| Errors | | | | | | |
| Security | | | | | | |
| Testing | | | | | | |

Do not select the implementation based on popularity.

Select based on:

PROJECT REQUIREMENTS
+
CURRENT ARCHITECTURE
+
SECURITY
+
CORRECTNESS
+
MAINTAINABILITY
+
TESTABILITY

============================================================
20. AGENT ALIGNMENT AUDIT
============================================================

After every migration/hardening:

Audit all affected agents.

For every affected agent verify:

- tool name
- tool import/reference
- registry mapping
- allowed_tools
- permissions
- schema
- runtime invocation
- error handling
- result handling

Run real agent/tool integration tests.

Required final statement:

"Agent alignment verified: PASS"

or:

"Agent alignment verified: FAIL"

If FAIL:

NO GREEN FLAG.

============================================================
21. DO NOT MODIFY UNRELATED SYSTEMS
============================================================

While working on one tool:

Do not silently modify:

- unrelated tools
- unrelated agents
- memory
- orchestration
- frontend
- deployment
- database schema

unless the tool genuinely requires that change.

If a dependency requires an architectural change:

STOP and document it.

Do not hide the change.

============================================================
22. WHEN A TOOL IS ALREADY GOOD
============================================================

If a tool is already production-ready:

DO NOT rewrite it for the sake of rewriting.

Verify it.

Run the appropriate tests.

Check current 2026 reference implementations.

Check project requirements.

Check agent integration.

If all criteria pass:

GREEN FLAG.

This is important.

The goal is NOT:

"change every tool."

The goal is:

"prove every required tool is production-ready."

============================================================
23. WHEN A REFERENCE TOOL DOES NOT MATCH
============================================================

If another repository has a similar tool but it does not satisfy our
requirements:

DO NOT copy it.

Document:

Reference:
Why it is insufficient:
Our requirement:
Chosen design:
Reason:

Then build the appropriate implementation for THIS project.

============================================================
24. WHEN A TOOL IS NOT NEEDED
============================================================

If a tool is unused:

Verify with:

- registration
- agent mappings
- call sites
- dynamic discovery
- runtime traces where available

Do not call it unused based on grep alone.

If truly unused:

UNUSED

Do not delete it automatically.

============================================================
25. DUPLICATE TOOLS
============================================================

Before declaring DUPLICATE compare:

- purpose
- inputs
- outputs
- side effects
- security behavior
- callers
- agent usage

Do not call tools duplicates merely because their names are similar.

============================================================
26. FINAL 190-TOOL TARGET
============================================================

The target is NOT simply:

190 tools exist.

The target is:

190 tools have been individually verified.

For each tool we want:

GREEN FLAG

or an evidence-backed reason why it cannot yet receive GREEN FLAG.

Final report:

PRODUCTION_TOOL_AUDIT.md

must contain:

Total tools
GREEN FLAG
YELLOW FLAG
RED FLAG
PRODUCTION_READY
GOOD_NEEDS_HARDENING
BROKEN
UNUSED
DUPLICATE
PLACEHOLDER

Plus:

- tool-by-tool evidence
- security issues
- timeout issues
- resource issues
- testing gaps
- agent alignment issues
- path migration issues
- duplicate tools
- unused tools
- architecture issues
- remaining production risks

============================================================
27. FINAL ACCEPTANCE RULE
============================================================

I will consider the project complete only when:

Every required tool has been individually audited.

Every required production tool has passed its applicable tests.

Every required production tool has verified agent integration.

Every migrated tool has verified path/registry alignment.

No known production-blocking issue remains.

Counts are generated programmatically.

Evidence exists for every GREEN FLAG.

No production claim is based only on LLM judgment.

============================================================
28. INITIAL EXECUTION — IMPORTANT
============================================================

DO NOT start modifying all 190 tools immediately.

FIRST perform ONLY an audit/planning pass.

Inspect:

1. Existing tools
2. Registrations
3. Manifests
4. Callers
5. Agent mappings
6. Existing tests
7. Existing tool architecture
8. Current giant tools.py
9. Existing extracted tool modules
10. Existing tool security
11. Existing tool runtime
12. Existing tool permissions
13. Existing timeout system
14. Existing resource limits
15. Existing artifacts
16. Existing observability
17. Existing reference repositories
18. Existing requirements

Then generate:

A. Exact tool count
B. Tool inventory
C. Current classifications
D. Tool categories
E. Existing architecture
F. Modularization plan
G. Agent/path dependencies
H. Reference repository findings
I. Production gaps
J. Day-by-day implementation plan
K. Tool-by-tool execution order
L. Testing strategy
M. GREEN FLAG acceptance criteria
N. Risk analysis

DO NOT IMPLEMENT DURING THIS INITIAL AUDIT.

STOP AFTER THE PLAN.

Wait for approval before implementation.

============================================================
29. IMPLEMENTATION MODE
============================================================

After approval:

Process tools ONE BY ONE.

For each tool:

AUDIT
→ RESEARCH
→ REQUIREMENTS
→ DESIGN
→ IMPLEMENT
→ TEST
→ REAL EXECUTION
→ REGRESSION
→ AGENT ALIGNMENT
→ FINAL VERIFICATION
→ GREEN/YELLOW/RED FLAG

Never skip a stage.

Never mark GREEN FLAG early.

============================================================
30. FINAL PRINCIPLE
============================================================

The objective is not to make the code look production-ready.

The objective is to make the TOOL actually production-ready.

The evidence must be stronger than the claim.

CODE
+
REAL EXECUTION
+
TESTS
+
SECURITY
+
INTEGRATION
+
REQUIREMENTS
+
REFERENCE VALIDATION
=
GREEN FLAG

No evidence
=
NO GREEN FLAG.