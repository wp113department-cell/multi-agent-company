# Batch 12 — User Intent Understanding, Difficult User Handling, Clarification Engine, Requirement Analysis, Existing-Project Awareness, Safe Implementation

Covers §25, §26, §27, §28, §29, §30, §63. Evidence-only, file:line cited. This batch is dominated by a single recurring distinction that matters more than any individual checkpoint: **real code mechanism vs. prompt-text-only instruction.** Both are noted precisely below.

---

## §25 User Intent Understanding

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Understand vague/incomplete requests (structural gate) | **NO** | No structural "clarify before acting" gate — whether to clarify is entirely the LLM's own judgment each turn. |
| Detect hidden intent / conflicting requirements | **NO — prompt-only** | `_GLOBAL_STANDARDS.md`'s "Hard-Constraint Conflict Rule" is prompt text; no code scans for contradictions. |
| Ask clarification questions before acting | **PARTIAL** | Real tool (`request_clarification`) exists — but wired into **only `planner.py`**, confirmed by grep across all ~80 agent files. `chat.md` explicitly documents chat_agent has no access to this tool at all. |
| Refuse to guess when info insufficient | **NO — prompt-only** | No structural "required fields present" validator. The only code-level analog (`blocking_until`) gates specific tools, not task acceptance in general. |
| Separate multiple tasks from one prompt | **NO** | `decomposer.py` splits an *already-approved single task's* plan into subtasks — this happens downstream of task creation, not at intake. No code takes one raw user message and creates multiple top-level tracked tasks. |
| Detect intent type (explain/implement/debug/compare/docs-only) | **NO** | `chat_agent.py`'s routing (`_route_after_llm`/`_route_after_tool`) only distinguishes "tool call vs. stop," not intent category. Every message goes through an identical loop. `chat.md` lists intent classification as a prompt-level *success criterion* with no code artifact behind it. |

**§25 overall: NO, with one real but narrowly-wired exception.** This section has the most "prompt-only" findings of any batch so far — nearly every checkpoint here is aspirational text in a role file rather than an enforced mechanism.

---

## §26 / §63 Difficult User Handling / Emotion

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Frustration detection changes behavior | **NO — detected but inert** | `detect_user_frustration()` is real and its result IS surfaced — but only as an SSE `user_sentiment` event pushed to the frontend. It does **not** modify the system prompt, does not change tone/model/retry strategy for the LLM call that follows. De-escalation behavior exists only as prompt text in `chat.md` that the model must independently notice from raw conversation — the detector's signal never reaches the prompt. |
| Repetition detection changes behavior | **NO — same pattern** | Jaccard-based repetition signal is computed and pushed to SSE, never fed back to alter tool selection or retry strategy. |
| Contradictory/changing instructions | **NO — prompt-only** | Same Hard-Constraint Conflict Rule as §25. |
| Abusive language / poor English / mixed language / extreme-length prompts | **NO** | No explicit handling code found for any of these — no language detection, length-based branching, or profanity filter. Every message flows through the identical LLM call. |
| Remains professional | **N/A — inherently prompt-level** | Confirmed as `chat.md` instruction text; not something code could enforce short of output filtering (not found). |

**§26/§63 overall: NO.** This is the most consequential finding in the batch: **a real, working sentiment/frustration detector exists but is disconnected from behavior** — it's telemetry, not a feedback loop. Building the detector was real engineering effort that isn't currently paying off in the way the question (and likely the original intent) implies.

**Production Enhancement Plan:** Thread the `detect_user_frustration()` result into the system prompt construction at `chat_agent.py:2949-2951` (which currently builds the prompt from `self._system` + memory block only) — e.g. append a brief, non-verbatim instruction like "the user has shown signs of frustration; prioritize concrete next steps over lengthy explanation" when `frustrated=True`. This closes the loop between a detector that already works and behavior that currently ignores it, without new infrastructure.

---

## §27 Clarification Engine

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Ask only necessary questions | **NO — LLM judgment only** | Entirely governed by the tool's own description text ("not for every minor judgment call"), no code logic. |
| Build temporary plan while waiting | **NO** | `request_clarification`'s schema has no `partial_plan` field; the run ends cleanly rather than pausing with state. |
| Remember previous answers on re-dispatch | **NO — confirmed broken, not just "fresh start"** | This is the sharpest finding in the batch. Tracing the full path: `planner.py` returns a `[NEEDS_CLARIFICATION]`-prefixed error → `api/agents.py::launch_planner` treats it identically to a real failure (`finish_agent_run(..., "failed")`, task transitions to `"blocked"`) → the clarification is recorded as a non-blocking `PendingApproval` row → `api/approvals.py`'s generic decision dispatcher has real resume logic for `plan_review` and `git_push` actions **but no `elif` branch for `"clarification"` at all**. Approving/rejecting a clarification row only flips its DB status — **nothing re-dispatches the planner with the human's answer.** The tool's own description text claims "a future run receives that answer in its task context" — this claim has no automated implementation anywhere in the code. |

**§27 overall: NO, and this is a genuine defect, not a design choice.** Unlike the frustration-detector gap above (which is "built but not wired to behavior"), this is "built, described as working, and actually broken" — the tool's own docstring makes a promise the code doesn't keep. This is the kind of gap that would only surface in production when someone actually tries to answer a clarification question and watches nothing happen.

**Production Enhancement Plan:** Add the missing `elif row.action == "clarification":` branch to `api/approvals.py::_dispatch_decision`, following the same pattern already used for `plan_review`/`git_push` — construct a fresh planner dispatch with the human's answer folded into the `initial_message`, mirroring `resume_planning_pipeline`'s existing shape. This is a bounded, well-scoped fix given the pattern to copy already exists in the same file.

---

## §28 Requirement Analysis

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Break a huge pasted spec into milestones | **NO** | Neither `decomposer.py` nor `pm.py`'s output schemas have any milestone/phase field — both produce flat structures. |
| Detect impossible requirements / duplicated work / suggest better architecture | **NO — prompt-only** | Same Hard-Constraint Conflict Rule; no code scans for duplicate/existing functionality before accepting a task (ties to §29). |
| Produce an execution roadmap | **NO** | Zero references to "roadmap" as a generation capability anywhere. |

**§28 overall: NO across the board.**

---

## §29 Existing Project Awareness

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Check for existing implementation before building | **PARTIAL — available, not enforced** | The planner's fact-gathering step (`_gather_facts_and_plan`) makes pure LLM calls with **no tool access** — it reasons abstractly about what it would need to look up, it doesn't actually look anything up. `search_code`/`search_symbols` ARE available to the planner in later turns, and the role prompt instructs their use ("Check before assuming") — but nothing in code requires them to be called before `submit_plan`. No `blocking_until` entry exists for `submit_plan`. |

**§29 overall: PARTIAL — real capability, zero enforcement.** The tools needed to do this correctly exist and are accessible; whether it actually happens on any given run depends entirely on the LLM choosing to use them.

---

## §30 Safe Implementation

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Repo search / read files / understand architecture required before writing | **PARTIAL — real mechanism, inconsistently applied** | `VerificationConfig.blocking_until` is a genuine, hard, code-level gate (refuses the tool call outright, not just a post-hoc note) — **but only 2 of the agents checked actually use it this way**: `chat_agent.py` (write tools blocked until `read_file`/`search_code` has run) and `dependency_security_agent.py` (`bash` blocked until `read`). **`coder.py` — the actual primary code-implementation agent in the main pipeline — has no `blocking_until` at all.** Its `enforce_in_result` mechanism only overwrites a *reported* field after the fact; it cannot block or reject a submission, so there is no code-enforced requirement that `coder.py` reads before writing, or that lint/type checks actually pass before a patch is accepted (only that the agent can't lie about whether they ran). |
| Explain risks / preserve backward compatibility | **NO — prompt-only** | An 8-step advisory list in `coder.md`, not gated. |
| Static quality checks (mypy/ruff) | **YES, but post-hoc** | `_run_checks()` genuinely runs real subprocess checks — but *after* the LLM's work, as a separate retry loop outside the graph, not as a precondition on write tools. |

**§30 overall: PARTIAL, and this is a meaningful, specific gap.** The exact mechanism that would make "safe implementation" real (`blocking_until`) exists in the codebase, is tested, and is already used correctly by 2 agents — but the flagship code-writing agent doesn't use it. This isn't a missing capability; it's an unapplied one, which is a smaller fix than building the mechanism from scratch.

**Production Enhancement Plan:** Add `blocking_until={"write_file": "read", "edit_file": "read"}` to `coder.py`'s `_VERIFICATION_CFG`, mirroring `chat_agent.py`'s existing pattern exactly — this closes the gap with a config change to an agent's contract, not new engine code, since the enforcement mechanism (`base_graph.py:1637-1644`) already exists and is tested.

---

## Summary — Batch 12 (18 checkpoints across 6 sections)

- **YES:** 1
- **PARTIAL:** 5
- **NO:** 12

**This is the weakest-scoring batch of the audit so far** — but the *character* of the gaps is what matters most for a production plan: two of them (frustration-signal wiring, `coder.py`'s missing `blocking_until`) are genuinely small, well-scoped fixes because the underlying mechanisms already exist and work elsewhere in the same codebase. One (clarification resume) is a real, previously-undetected functional defect where documented behavior doesn't match implementation. The rest (intent classification, milestone breakdown, roadmap generation, contradiction detection) are genuine absences that would require new capability, not just wiring.

**Priority ranking for fixes, cheapest-to-highest-value first:**
1. `coder.py` blocking_until (config change, mechanism exists) — closes Batch 12's most safety-relevant gap.
2. Clarification resume branch in `api/approvals.py` (follows an existing pattern in the same file) — fixes a broken promise, not a missing feature.
3. Frustration-signal → prompt wiring (small code change, mechanism exists) — makes existing telemetry actionable.
4. Intent classification / milestone breakdown / roadmap generation — genuinely new capability, appropriately scoped as future work rather than a quick fix.
