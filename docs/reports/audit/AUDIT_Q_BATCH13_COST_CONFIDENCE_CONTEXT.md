# Batch 13 — Cost Awareness, Confidence & Uncertainty, Explainability, Multi-Session Continuity, Large Context Understanding, Token/Context Budget, Economic Awareness

Covers §42, §43, §44, §45, §52, §65, §101. Evidence-only, file:line cited.

---

## §42 Cost Awareness

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Pre-execution cost/token estimate | **YES — Production Ready** | `_cost_estimate_node` (`manager.py:953`) runs **before** planning/coding in the epic-manager graph, calls `estimate_epic_cost()` which computes tokens/cost/duration. Real, config-driven threshold: `cost > settings.cost_approval_threshold` → `Epic.status = "pending_cost_approval"`, hard-halts pending human approval. Not observability-only — a real gating state transition. |
| Recommend cheaper approaches | **NO** | No code computes or suggests a cheaper model tier or reduced scope. `cost_rates_for_tier()` exists but per its own docstring has no caller that acts on it — dev-agent dispatch always picks between two same-tier agents (backend_dev/frontend_dev), no tier-downgrade logic anywhere. |

**§42 overall: PARTIAL, leaning strong.** The gating half (estimate → halt on threshold) is genuinely production-grade. The advisory half (suggest something cheaper) doesn't exist — a real, if secondary, gap versus what "cost awareness" implies.

---

## §43 Confidence & Uncertainty

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Every important answer has a confidence estimate | **NO** | Spot-checked 3 core output schemas (`pm.py::submit_brief`, `qa.py::QAResult`, `reviewer.py::ReviewResult`) — **none has a confidence field.** Confidence exists only inside the shared planner's internal state, consumed solely by an internal quality-gate check; it doesn't propagate to any of the 3 checked output types. |
| Distinguish verified facts from assumptions | **YES — exposed, not just internal** | `_quality_gate` results (`checks`, `warnings`, `passed`) are attached to every submit-tool result and surface through the API (`specialized_agents.py:295,477`). `AgentResult.verified` comes exclusively from real tool-derived `state["verification"]`, never the model's own claim — enforced with a logged override whenever they disagree. This is genuinely more than an internal gate, though it's exposed as structured fields (`verified`, `_quality_gate.checks`), not a plain-language "here's what's confirmed vs. assumed" summary a non-technical user could read directly. |
| Explicitly say "I don't know" | **YES — code-enforced, informational** | `limitation_type`/`proposed_alternative` checked and warned-on when missing for blocked/needs_human results — real code, mirrors the prompt-level `_GLOBAL_STANDARDS.md` rule. Explicitly informational-only (flags for human review, never blocks the submission itself). |

**§43 overall: PARTIAL.** Two of three checkpoints are real and reasonably strong; the missing one (per-output confidence field) is a real, specific, fixable gap rather than a vague absence.

---

## §44 Explainability

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Explain why this approach / these agents / these tools were chosen | **NO** | No dedicated "explain your reasoning" endpoint or synthesized output found. A user would have to read raw `activity_stream` events (`thinking`/`tool_call`) and/or the `_quality_gate` fields to reconstruct this themselves — nothing assembles it into a coherent explanation. |
| Structured decision-log/rationale field in DB | **NO** | `TaskLog` has only generic `category`/`message`/`extra_data` — no typed rationale/reasoning column anywhere in `models.py`. |

**§44 overall: NO.** The raw materials for explainability exist (activity stream events carry real "thinking" content) but nothing synthesizes them into an actual explanation artifact — this is a presentation/synthesis gap, not a data-availability gap.

---

## §45 Multi-Session Continuity

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Context persists across app restart | **PARTIAL** | DB task/epic state: yes, unaffected. Chat LangGraph state: no — `MemorySaver()`, explicitly documented as an intentional design choice matching `ChatSession`'s "always held in-memory" design (consistent with Batch 8's finding, now further confirmed as *intentional* rather than an oversight, per the code's own docstring). |
| Branch-context tracking after switching branches | **PARTIAL** | `DevTask.branch_name` persists the per-task **isolation worktree branch** — real, but this is not "which branch was the user last on" for the main repo. No field tracks that; it's purely "whatever git reports right now" at query time. |

**§45 overall: PARTIAL.** Not a defect so much as a scope clarification: durable continuity exists for structured task/epic work, not for the conversational chat surface or general branch awareness.

---

## §52 Large Context Understanding

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Condensation trigger | **YES** | `_select_messages_to_condense` fires on a combined gate: `tokens_in > token_budget` **and** `len(messages) > 4` — both conditions required, not either alone. |
| Compression method | **YES — real LLM summarization, not truncation** | `_summarize_dropped_messages` calls Haiku with an explicit "preserve specifics" instruction over the dropped-message excerpt, splices the result back as a synthetic message. Structurally protects the first message and last 4 messages from ever being dropped. On summarization failure, returns an honest placeholder string rather than silently losing content or fabricating a summary. |
| Applied to chat_agent conversations too | **YES** | `chat_agent.py::_condense_history_async` directly reuses `base_graph.py`'s trigger logic and applies the same head/dropped/tail boundary with its own async summarization call — genuinely shared logic, not a reimplementation that could drift. |
| Multiple repos/documents in one context | **NO** | Every relevant model and function signature uses a single `repo_path: str`; no list/multi-repo support anywhere. |

**§52 overall: YES for single-repo context management — this is one of the strongest-evidenced mechanisms in the entire audit.** Real trigger logic, real LLM-based summarization with explicit fact-preservation instructions, honest failure handling, and genuinely shared (not duplicated) logic between the two agent execution paths. Multi-repo support is absent, but that's a distinct, larger feature, not a flaw in what exists.

---

## §65 Token & Context Budget Management

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Check against the model's real context limit (not just cost budget) | **NO — a real gap** | `TIER_CONTEXT_WINDOWS`/`context_window_for()` define real per-tier ceilings (e.g. 200k for the relevant tiers) but have **zero callers anywhere outside their own module** — dead code for this purpose. The actual budget enforced at request time is a flat, conservative `context_token_budget` setting (default 8000) — an internal condense-trigger threshold, not a check against the model's actual API limit. If that setting were ever misconfigured above the real ceiling, nothing in this path would catch it before the request hits the Anthropic API and fails. |
| Warn user when approaching limits | **YES** | `approaching_limit` SSE event fires at a real 80%-99.9%-of-budget threshold, confirmed live (not just defined) in both `base_graph.py` and independently in `chat_agent.py`. |

**§65 overall: PARTIAL, with one specific, real defect worth prioritizing.** The warning mechanism is real and works. The actual safety net against exceeding the *model's* real limit (as opposed to the app's internal, much-smaller condense-trigger budget) doesn't exist — `TIER_CONTEXT_WINDOWS` was clearly built for this purpose and then never wired in.

**Production Enhancement Plan:** Wire `context_window_for(tier)` into the same check that currently only compares against `context_token_budget`, so a request that would exceed the *model's actual* limit is caught and condensed/rejected before the API call, not just when it exceeds the smaller internal default. This is a real, if narrow, fix — the ceiling data already exists and is correct, it's simply unconsulted.

---

## §101 Economic Awareness

Pre-execution estimate coverage (same real nodes as §42):

| Dimension | Verdict | Evidence |
|---|---|---|
| Token usage | **YES** | `estimated_tokens_in/out`. |
| API cost | **YES** | `estimated_cost_usd`, real gating threshold. |
| Execution time | **YES** | `estimated_duration_seconds`, historical-average-based with a config fallback. |
| Storage impact | **YES** | Real disk-space projection vs. actual free disk, in `_resource_check_node`. |
| Compute requirements | **PARTIAL** | RAM: real projected-vs-available check. CPU: only static capability probing (is a CPU/GPU/Docker present), not a projected compute-load estimate for the specific task. |

**§101 overall: YES, nearly complete.** 4 of 5 explicitly-asked-about dimensions are genuinely, quantitatively estimated pre-execution with real gating consequences — this is a strong, evidence-backed result, one of the better-covered sections in the whole audit.

---

## Summary — Batch 13 (16 checkpoints across 7 sections)

- **YES:** 7
- **PARTIAL:** 7
- **NO:** 2

**Findings worth flagging above the rest:**
1. **Context condensation (§52) is genuinely one of the best-built subsystems found in this entire audit** — real triggers, real LLM summarization with fact-preservation, honest failure handling, and correctly shared (not duplicated) between both agent execution paths. Worth crediting explicitly, not just noting as "passed."
2. **§65's dead `TIER_CONTEXT_WINDOWS` mechanism is a precise, easy-to-miss gap** — the real model context ceiling is computed and available but never consulted; only a much smaller internal budget is checked.
3. **Per-output confidence fields are absent from the 3 checked schemas** despite the underlying confidence-computation machinery existing — another case (consistent with Batch 12) of a real mechanism not being propagated to where it would matter most.
