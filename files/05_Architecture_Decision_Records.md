# 05 — Architecture Decision Records (ADR)

**Applies from:** Stage 0, appended to as new major decisions are made
**Related:** `02_System_Architecture_Blueprint.md`

---

Each record below follows the same format: the decision, the context that drove it, and the alternatives that were considered and rejected. New ADRs are appended, never edited after acceptance — if a decision changes later, a new ADR supersedes the old one and says so explicitly.

---

### ADR-001: Use the Claude Agent SDK as the agent execution engine
**Decision:** Build on Anthropic's Claude Agent SDK rather than a custom-built agent loop.
**Context:** The SDK ships with subagents, isolated git worktrees, permission hooks, and sandboxing already built and production-tested (it's the same engine behind Claude Code). Building this from scratch would mean re-implementing tool-calling, context management, and safety primitives that already exist and are maintained by the model vendor.
**Alternatives considered:** Fully custom agent loop calling the raw Claude API — rejected, months of redundant work for less reliable safety primitives.

### ADR-002: Use LangGraph for multi-agent orchestration
**Decision:** LangGraph coordinates multi-step, multi-agent workflows (planning subsystem, Manager Agent).
**Context:** Stateful, checkpointed graph orchestration with built-in human-in-the-loop interrupts is exactly the shape of this problem — staged, auditable, resumable after a crash.
**Alternatives considered:** Temporal, Prefect — both are general workflow engines, not agent-specific; would require more custom integration work for no clear benefit at this stage. AutoGen, CrewAI — less mature support for the supervisor + interrupt pattern this system needs.

### ADR-003: Use MCP for all tool and data access
**Decision:** Agents access filesystem, git, GitHub, and databases through MCP servers, not custom one-off integrations.
**Context:** MCP is Anthropic's open standard, with hundreds of existing servers (filesystem, git, GitHub, Postgres) already available, and the same protocol the rest of the AI industry has converged on. Writing custom integrations per tool would duplicate this work and be harder to maintain.

### ADR-004: Use Git worktree isolation for all agent code changes
**Decision:** Every coding subagent runs in an isolated git worktree (`isolation: worktree`), never directly against the checked-out repo.
**Context:** This is a blast-radius control — if an agent's change is wrong, it's contained to a disposable worktree, never touching the actual codebase until a human approves merging it.

### ADR-005: PostgreSQL from day one, avoiding Supabase-specific lock-in
**Decision:** Use plain PostgreSQL (hosted via Supabase initially) for all relational data; deliberately avoid Supabase-specific features like their Auth or Edge Functions.
**Context:** Standard Postgres keeps the system trivially self-hostable later (a connection-string change, not a migration), while still getting Supabase's hosting convenience now, without a 2–3 person team needing to stand up and maintain self-hosted infrastructure before there's a real workload.
**Alternatives considered:** Self-hosting Postgres + Redis + MinIO + Qdrant from day one — rejected for Stage 1; this is a real DevOps burden for a team with no dedicated infra engineer until Stage 7. Each piece is introduced at the stage that actually needs it.

### ADR-006: pgvector before Qdrant
**Decision:** Start vector search in the same Postgres instance via pgvector; introduce Qdrant only once embedding volume or query load justifies a dedicated vector store.
**Context:** Avoids standing up a second database system before there's a measured need for it.

### ADR-007: Inngest before Redis + BullMQ
**Decision:** Background job execution starts on Inngest; migrates to Redis + BullMQ at Stage 7 if throughput requires it.
**Context:** Same reasoning as ADR-005 — avoid standing up Redis infrastructure before there's concurrent load that needs it.

### ADR-008: No full model-agnostic runtime yet
**Decision:** All model calls route through one thin internal interface (`callModel()`), but no full multi-model adapter layer (Claude/GPT/Gemini/DeepSeek/Qwen/local, fully swappable) is being built.
**Context:** Models don't behave identically in long agentic loops — a thin adapter alone doesn't deliver true interchangeability without per-model prompt and tool tuning underneath. Building that properly would cost months before any agent ships, for models with no current usage plan. The thin interface keeps a real swap point open without paying that cost now.

### ADR-009: No generic "Agent OS" before the Developer Department ships
**Decision:** Build the Developer Department under its current scope first. Do not design a shared platform layer (Agent Marketplace, generic Capability Registry across departments, cross-department Runtime Scheduler) for Sales, Marketing, HR, or Finance departments that haven't been scoped yet.
**Context:** This is the textbook shape of premature abstraction — generalizing before building even one specific case well enough to know what's actually shared versus what only looks shared on a whiteboard. The components already being built (LangGraph orchestration, MCP tool layer, Policy Engine, Artifact Store, Context Builder, Agent Registry) are already generic; they don't know anything specific to "developer work." Extracting them into a formally shared platform package is the right move once a second department is real and its actual requirements are known — not before.
**Alternatives considered:** Renaming the project to "Gridiron Agent OS" and building the OS layer first — rejected; would likely cost 6–12+ months building speculative infrastructure for departments that don't exist, with nothing shipped to the client in the meantime.

### ADR-010: Human approval gate at merge/deploy is permanent
**Decision:** No agent, at any future stage, merges to the main branch or deploys to production without explicit human approval. This is not a milestone to eventually remove as the system matures — it is a permanent architectural constraint.
**Context:** Every credible AI engineering organization building this kind of system — including Anthropic's own Claude Code — keeps this gate. It is the line between "maximum automation" and "fully unsupervised autonomy," and the system is designed to maximize the former while never crossing into the latter.
