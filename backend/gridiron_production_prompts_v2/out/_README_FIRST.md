# Gridiron Workforce OS — Production Prompts v2.0

## How to install
1. Copy ALL files into your project's agent-prompts folder, replacing the old files.
2. `_GLOBAL_STANDARDS.md` is REQUIRED — every agent prompt inherits it. Ensure your orchestrator
   loads it into every agent's context alongside the agent's own role file
   (prepend it, or reference it, exactly like Claude Code loads CLAUDE.md for every session).
3. `UPGRADE_REPORT.md` documents Production Score / what changed / why changed for every role. Not needed at runtime.

## What changed (summary)
- 67x duplicated boilerplate → ONE versionable global constitution (DRY, maintainable)
- Every agent now has: Non-Responsibilities, Success Criteria, Failure Conditions,
  Output Contract, Quality Gates, Edge Cases, role-specific Escalation
- Anti-hallucination hardened: evidence-first (file:line), live-data-over-training-data,
  adversarial self-check, 3-attempt error rule, honest blocked status
- All original responsibilities, workflows, tools, checklists, and Karpathy principles preserved
- Single Responsibility enforced: every agent has explicit "never do these" boundaries
  pointing to the sibling agent that owns the adjacent work
