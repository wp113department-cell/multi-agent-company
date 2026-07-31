---
name: feedback-safe-scope-over-literal-spec
description: "when a spec's literal text seems unsafe, verify the specific unsafe mechanism, then look for a redesign that avoids it — don't stop at \"therefore skip it\""
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6abafd0b-70f0-4656-bb9b-4b95cb10cee5
  modified: 2026-07-29T09:53:05.304Z
---

Rule: if a spec asks for something that seems unsafe given the real code's current architecture,
investigate concretely (read the real code, trace or reproduce the actual mechanism) before deciding
anything. If it's genuinely unsafe as literally described, don't stop at "therefore don't implement
it" — check whether a different decomposition/redesign of the same underlying idea avoids the unsafe
mechanism while still delivering the real ask. Only fall back to a lesser substitute, clearly
documented, if no such redesign exists.

**Why**: on the multi-agent-company `MASTER_AGENT_v2.md` engagement, converting `chat_agent.py`'s
confirmation gate to a real LangGraph `interrupt()` was first assessed as unsafe — correctly: wrapping
the whole agentic loop as one graph node means LangGraph replays that node's entire body on resume,
re-executing real side effects (git pushes, bash commands) that already ran before the confirmation
point. But the conclusion drawn — "therefore don't implement the conversion at all, ship an audit-
trail-only substitute instead" — was wrong. The user pushed back ("solve this now i dont need this
bug"), and the actual fix was a decomposition: make *every tool call* its own graph node instead of
one node covering a whole Python loop. Replaying a single interrupted node then only re-runs harmless
pre-confirmation prep, never an already-completed tool's side effect (verified with a standalone
LangGraph reproduction script before touching the real code, then with a real end-to-end test
counting actual side-effect calls across a pause/resume cycle). The unsafety finding was real and
worth surfacing; stopping there was premature.

**How to apply**: when a task instruction implies a specific mechanism (interrupt(), checkpointing,
retries, replay) and it looks unsafe, (1) verify the *specific* failure mode concretely — don't just
reason about it in the abstract, reproduce it if practical; (2) once confirmed, ask whether the
danger is inherent to the ASK or just to the FIRST design tried; a finer-grained decomposition often
removes the exact hazard while keeping the literal ask intact. Present the smaller safe substitute
only when a genuine redesign isn't available, and say so explicitly rather than implying it's the
only option.

This same pattern recurred, confirming it's a real, ongoing risk not a one-off: `base_graph.py`'s
Day 18-19 work in the 65-day gap-closure plan (see `../PLAN.md`, `../IMPLEMENTATION_PROGRESS.md`)
hit the identical "whole node replays on resume" hazard in a structurally different graph, and was
fixed the same way (one-tool-call-per-node-invocation), this time reproduced first via a standalone
script before touching production code, per the plan's own explicit hard-stop condition for this
scenario.
