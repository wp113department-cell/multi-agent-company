# Batch 10 — Deployment Intelligence, External Knowledge, Git Intelligence, Documentation Intelligence

Covers §19, §20, §40, §41. Evidence-only, file:line cited.

---

## §19 Deployment Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Detect deployment issues | **PARTIAL** | Real pattern-matching Docker log summarizer (`_summarize_docker_log_patterns`) exists and is wired into `docker_agent.py` — but it's keyword/regex detection, not diagnosis. |
| Diagnose deployment failures | **NO** | No dedicated failure-analysis tool/agent beyond the log pattern summarizer. |
| Generate deployment guides for THIS project | **NO** | No `deployment_guide_agent.py` or equivalent exists. |
| Vercel | **NO — denylisted, not supported** | `vercel deploy` is a hard-blocked bash pattern in the policy engine; no tooling, no config field. |
| Docker | **YES** | Real (`docker_agent.py`, `policy/sandbox.py`), established in prior batches. |
| Railway | **NO** | Zero references anywhere. |
| Render | **NO** | Zero references anywhere. |
| Kubernetes | **NO — explicitly, deliberately blocked** | `kubectl` is hard-denylisted fleet-wide; code comments explicitly confirm "terraform and kubectl are deliberately absent... no dry-run/plan carve-out exists." This is an intentional safety boundary, not an oversight. |
| AWS | **PARTIAL** | Real `boto3` usage exists (`artifacts/s3_store.py`) but only for the app's own artifact storage backend — not a deployment/infra tool for user projects. |
| Azure / GCP | **NO** | Zero references anywhere. |

**§19 overall: NO/PARTIAL — and mostly by design, not oversight.** CLAUDE.md's own permanent rule ("Deploy is a human action forever") explains most of these — Kubernetes and Vercel aren't missing by accident, they're deliberately denylisted. The one genuine gap (not explained by the safety policy) is the total absence of deployment *diagnosis* tooling (reading a failed deploy's logs/state and explaining what went wrong) versus deployment *execution* (correctly refused).

**Note for the overall scoring:** don't penalize this section as if it were an unintentional gap — cite the safety rule explicitly when scoring, since implementing Kubernetes/Vercel execution tooling here would directly contradict a permanent project rule, not fill a real gap.

---

## §20 External Knowledge

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Open URLs | **YES** | Confirmed in Batch 9 — real, SSRF-hardened. |
| Understand/summarize websites | **PARTIAL** | Raw content returned only, no summarization step in the tool itself (same finding as Batch 9). |
| Inspect external GitHub repos | **NO** | All GitHub tooling operates on the local repo's own remote via `gh` CLI, not arbitrary external repos. |
| Inspect APIs (OpenAPI/Swagger) | **NO** | Zero references. |
| Use documentation while coding (integrated) | **NO** | `fetch_url` is available but not wired into any automatic context-injection flow — same finding as Batch 9. |

**§20 overall: PARTIAL**, consistent with and duplicate-confirming Batch 9's §79/80/81 findings (same underlying tools).

---

## §40 Git Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Create meaningful commits / write commit messages | **NO — not auto-generated** | Commit message is a required explicit input in every commit tool; `generate_commit_msg` (despite its name) only returns `git diff --cached --stat` output to *help the calling LLM* write one — it doesn't generate the message itself. |
| Create branches | **YES** | Two real implementations, both real `git branch`/`git checkout` calls. |
| Resolve merge conflicts | **PARTIAL — agent-assisted, not automatic** | Real, well-built tooling: `parse_merge_conflicts` structures conflict markers into JSON hunks (ours/theirs/line-ranges); `resolve_merge_conflict` mechanically applies an explicit per-hunk decision (`ours`/`theirs`/`custom`) that the calling agent must supply. The mechanism is genuinely useful (structures the problem correctly) but does not decide resolutions itself — the code's own test docstring confirms this framing directly. Tested, 15/15 passing. |
| Explain conflicts | **PARTIAL** | Structured JSON hunks are a step up from raw markers, but there's no natural-language explanation generator. |
| Review diffs (beyond raw output) | **NO** | All `git diff` implementations return raw stdout only — no LLM-based diff review/annotation layer exists as a distinct capability. |
| Summarize changes | **NO** | Same finding — no dedicated summarization capability beyond raw `--stat` output. |
| Generate PR descriptions | **NO — not auto-generated** | Both PR-creation tools require `title`/`body` as explicit caller-supplied inputs; neither generates them. |

**§40 overall: PARTIAL, with a consistent pattern.** Every "generate X" checkpoint in this section (commit messages, diff summaries, PR descriptions, conflict explanations) resolves the same way: **the mechanical/data-gathering half is real and well-built (real diff output, real conflict-hunk structuring, real stat summaries), but the generative/LLM-authored half is not a separate tool capability — it's implicitly delegated to whichever agent calls the tool, in that agent's next turn.** This is architecturally coherent (the LLM in the loop can write the commit message from the diff it's shown) but means none of these are dedicated, independently-testable capabilities — they're only as good as the calling agent's prompt in that moment.

**Production Enhancement Plan:** If dedicated, consistent quality is wanted for commit messages/PR descriptions (rather than depending on whichever agent happens to call the tool), add a small dedicated LLM call inside `generate_commit_msg`/`create_pr` (similar to the existing `_merge_via_llm` pattern already used in the memory system, per Batch 3) rather than leaving generation fully implicit.

---

## §41 Documentation Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| README generation | **YES** | Real agent, role file exists, wired into dispatch registry. |
| Architecture docs generation | **PARTIAL — will crash if invoked** | Agent code is real, but its role file (`backend/roles/architecture_doc_agent.md`) **does not exist** — `load_role()` will raise `FileNotFoundError`. Confirms the Batch 2 finding. |
| API docs generation | **YES** | Real agent, role file exists (114 lines). |
| Agent docs generation | **PARTIAL — same crash risk** | `agent_roster_doc_agent.py` real, role file missing. |
| Tool docs generation | **PARTIAL — same crash risk** | `tool_catalog_doc_agent.py` real, role file missing. |
| Changelog generation | **YES** | Real agent, role file exists (75 lines), and it's one of only two doc agents with automatic triggering. |
| Migration guide generation | **PARTIAL — same crash risk** | `migration_guide_doc_agent.py` real, role file missing. |
| Auto-update when code changes | **PARTIAL** | A real periodic trigger loop exists (`_doc_agent_auto_trigger_loop`, polls `main`'s HEAD SHA) — but it's wired to **only 2 of the 6+ doc agents** (`changelog_agent`, `release_notes_agent`). The other 4-5 (including all 3 agents with missing role files) remain strictly manual-invocation-only. The code's own docstring is unusually candid about this, quoting a prior audit's finding verbatim. |

**§41 overall: PARTIAL, with a concrete, fixable defect.** This section directly corroborates and sharpens the Batch 2 finding: **4 real, registered agent modules (`architecture_doc_agent`, `agent_roster_doc_agent`, `tool_catalog_doc_agent`, `migration_guide_doc_agent`) will raise an unhandled `FileNotFoundError` if ever actually invoked**, because their role prompt files don't exist on disk. This is not a capability gap — it's a broken capability that appears functional (the Python module, contract, and dispatch registration all look complete) until runtime.

**Production Enhancement Plan:** Immediate fix, low effort: either write the 4 missing `backend/roles/*.md` files (following the existing pattern from `readme_agent.md`/`api_docs_agent.md`) or remove the 4 orphaned agent modules from the dispatch registry until they're ready. This should be prioritized above most other findings in this audit — it's the only issue found so far across 10 batches that causes an outright crash rather than a degraded/missing capability.

---

## Summary — Batch 10 (30 checkpoints across 4 sections)

- **YES:** 6
- **PARTIAL:** 13
- **NO:** 11

**Findings worth flagging above the rest:**
1. **Confirmed, sharpened: 4 doc-generation agents will crash on invocation** due to missing role files — this is now cross-validated by two independent audit passes (Batch 2 and Batch 10) reading different files and reaching the same conclusion via different methods.
2. Deployment tooling gaps are mostly intentional (Kubernetes/Vercel/Terraform execution correctly refused per CLAUDE.md's safety rule) — this should be scored differently from an accidental gap.
3. "Generate X" git/PR capabilities are architecturally real but fully implicit — no dedicated tool guarantees quality independent of the calling agent's prompt in the moment.
