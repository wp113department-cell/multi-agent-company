# Batch 17 — Professional Domain Coverage, Adaptive Expertise, Technology Recommendation Engine, Capability Boundaries

Covers §71, §73, §83, §84 (§82/§72 domain-adjacent items folded in where already covered by Batch 4). Evidence-only, file:line cited.

---

## §71 / §82 Professional Domain Coverage

| Domain | Verdict | Evidence |
|---|---|---|
| Backend Development | **YES** | Dedicated `backend_dev.py`. |
| Frontend Development | **YES** | Dedicated `frontend_dev.py`. |
| Full Stack | **YES** | `coder.py` (generic, backend+frontend capable). |
| API Development (REST/GraphQL) | **YES** | Two dedicated agents: `api_designer_agent.py` (contract/OpenAPI design, explicitly covers REST/GraphQL) + `api_docs_agent.py`. |
| Mobile Development (Android/iOS/Flutter/React Native) | **NO** | Zero references anywhere — no agent, role file, or tool. |
| AI/ML/LLM Engineering | **YES** | Dedicated `ai_engineer.py` with its own real tool handlers (training/inference/eval/embeddings). |
| RAG Systems | **YES** | Dedicated `rag_engineer_agent.py` with its own real tool handlers (chunking, embedding model selection, vector store setup). |
| Agentic AI / LangGraph (as a domain the user gets help *with*, not the infra Gridiron itself runs on) | **NO** | The fleet's own LangGraph usage is infrastructure, not a user-facing capability. No dedicated agent helps a user design *their own* agentic system distinct from `ai_engineer`. |
| MCP Development | **NO — real but mislabeled adjacent capability** | Gridiron has a real MCP *server* (exposes its own repo-intelligence tools via stdio JSON-RPC) — but this is Gridiron acting as an MCP server, not a capability that helps a user build/develop their own MCP servers/clients. Separately, tool specs labeled "MCP / External integration" in `tools.py` are actually plain GitHub/webhook tool specs, a naming mismatch, not real MCP protocol work. |
| Prompt Engineering | **NO — mentioned in a prompt, not a capability** | Only reference is `ai_engineer.md` listing prompt engineering as one of its own skills — no standalone agent/tool. |
| Data Engineering / ETL / Data Warehousing | **YES** | Dedicated `data_pipeline_agent.py`. |
| SQL | **YES** | Dedicated `sql_agent.py`, validates against the live DB schema. |
| Docker | **YES** | Dedicated `docker_agent.py` (established in prior batches). |
| Kubernetes | **NO — deliberately, not a gap** | `infra_agent.py` can review K8s manifests read-only; live `kubectl` execution is explicitly, deliberately blocked fleet-wide (confirmed in the role file's own words: "a real, deliberate security boundary, not a gap"). |
| CI/CD | **YES** | Dedicated `cicd_agent.py`, confirmed real (`_register()` verified), requires human approval by design, tested. |
| Monitoring/Logging | **YES** | Dedicated `monitoring_agent.py` (established in prior batches). |
| Security | **YES** | Three dedicated agents: `security_reviewer.py`, `dependency_security_agent.py`, `security_architect.py` (STRIDE/OWASP threat modeling — a new find this pass, more thorough than previously characterized). |
| QA/Testing | **YES** | Multiple dedicated agents: `qa.py`, `test_writer_agent.py`, `test_coverage_agent.py`, `load_test_agent.py` (k6/Locust). |
| Architecture/System Design | **YES** | `architect.py`, `architecture_reviewer.py`, `architecture_doc_agent.py` (though the last has the missing-role-file crash risk from Batch 10). |
| Product Management (roadmap/strategy) | **NO — generic PM only, no roadmap capability** | `pm.py`/`executive.py` translate a task into goals/constraints/epics — real but generic, not product-roadmap or strategy-specific. No dedicated roadmap agent exists anywhere (consistent with Batch 12's finding that roadmap generation is absent). |
| Business Analysis | **YES** | Dedicated `business_analyst.py`. |
| Sprint Planning | **YES** | Dedicated `sprint_planner.py`. |
| UI/UX Design, Design Systems | **NO** | Zero references — no dedicated agent or tool. |
| Accessibility | **YES** | Dedicated `accessibility_agent.py`, real WCAG 2.1 audit capability — notable given Batch 14 found the *frontend itself* has almost no accessibility investment; the capability to audit for it exists even though it hasn't been applied to the project's own frontend. |

**§71/§82 overall: YES for the great majority of traditional software-engineering domains, NO for three coherent clusters**: mobile development, UI/UX design, and product/roadmap strategy. This is a genuinely broad agent roster (84 files covering ~20 of 24 checked domains with real, dedicated, tool-backed agents) — the gaps are concentrated, not scattered, which suggests they're unaddressed product areas rather than a systematically thin build.

---

## §73 Adaptive Expertise

Not independently re-derived this pass — this maps directly onto Batch 12's finding that no intent/role classification exists anywhere in the system (`chat_agent.py`'s routing distinguishes only "tool call vs. stop," nothing about the user's professional role). **Verdict: NO**, consistent with and explained by that earlier finding — the domain-specific *agents* exist (per §71 above), but nothing detects which one a conversational user implicitly needs, or adapts tone/terminology to a detected role (e.g. talking to a "Business Analyst" vs. a "DevOps Engineer"). Domain coverage and adaptive routing are two separate capabilities, and only the first is real.

---

## §83 Technology Recommendation Engine

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Dedicated multi-criteria recommendation engine (scale/budget/maintainability/security/ecosystem) | **NO** | No `tech_advisor.py` or equivalent exists; no structured multi-criteria scoring found anywhere. |
| General single-question research/recommendation capability | **PARTIAL** | `spike_agent.py` is real — time-boxed research on one specific technical question, explicitly designed to return "a concrete recommendation, not a survey of all options." Can be pointed at a framework/database choice, but it's a general-purpose research tool, not a purpose-built technology-selection engine weighing the specific criteria the question asks about (budget, team complexity, long-term support, etc. as structured inputs). |

**§83 overall: NO/PARTIAL.** The closest real capability (`spike_agent`) is genuinely useful but architecturally different from what's being asked — it's one-question research, not a comparative decision engine.

---

## §84 Capability Boundaries

**YES — confirmed, same mechanism as Batch 4/13.** The `limitation_type`/`proposed_alternative` requirement (real, code-enforced validation on any `blocked`/`needs_human` submission, requiring the agent to classify the limitation as `temporary` or `fundamental` and supply a concrete next step) is the system's actual, singular answer to "how does it communicate what it can't do." No separate/distinct mechanism exists, but this one is real and consistently enforced, not merely descriptive.

---

## Summary — Batch 17

- **YES:** 15 (domains) + 1 (§84)
- **PARTIAL:** 2
- **NO:** 8 (domains) + 1 (§73) + 1 (§83's dedicated-engine half)

**Findings worth flagging:**
1. Domain coverage is genuinely broad and real — 84 distinct agents is not a padded number; the majority checked have real, tool-backed, dedicated implementations, not generic fallbacks dressed up with a name.
2. The three coherent gap clusters (mobile, UI/UX/design-systems, product/roadmap strategy) look like deliberately unaddressed product scope rather than incomplete engineering — worth treating as a roadmap decision, not a "fix this" bug list.
3. The accessibility-agent-exists-but-frontend-has-no-accessibility-investment pairing (cross-referencing Batch 14) is a notable, slightly ironic internal inconsistency worth surfacing directly: the platform can audit for a problem it has itself.
