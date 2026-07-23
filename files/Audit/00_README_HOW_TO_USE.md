# Gridiron Audit Suite v2 — How to Use

12 read-only audit prompts, tailored to your actual codebase. v2 adds the
depth that was genuinely missing from v1: a dedicated Zero Policy sweep,
deeper per-agent reliability checks (fallback/timeout/retry, race
conditions, structured-output validation, permission matrix), failure-
scenario simulation for orchestration, and a required evidence schema +
machine-readable JSON output so findings can be merged programmatically
instead of re-read as prose.

## What did NOT get added, and why

The ChatGPT critique also suggested auditing for vLLM, Triton, Ray Serve,
Kubernetes HPA, Helm, Cloudflare, LangSmith, Langfuse, Phoenix, Promptfoo,
DeepEval, Ragas, MLflow, Guardrails, DSPy, LlamaIndex, Haystack, and
GraphRAG. None of these appear in your `requirements.txt`/`package.json`
per PROJECT.md. Auditing for stacks you don't run doesn't make the audit
more rigorous — it makes Claude Code either say "NOT FOUND" 20 times or,
worse, start inventing plausible-sounding analysis for technology that
isn't there. If you ever DO add one of these, tell me and I'll add a
grounded audit section for it specifically.

## Files in this suite

| # | File | Covers |
|---|---|---|
| 00b | `00b_AUDIT_STANDARDS.md` | evidence schema + JSON output format — reference this when running ANY numbered audit |
| 01 | `01_MASTER_ARCHITECTURE_AUDIT.md` | two-graph structure, dependency graph, event flow, DB schema flow |
| 02 | `02_MASTER_AGENT_AUDIT.md` | all ~72 agents vs AGENT_CONTRACT, + deep reliability checklist (fallback, timeout, retry, race conditions, tool permission matrix, multimodal) |
| 03 | `03_MASTER_MEMORY_AUDIT.md` | LessonStore, memory_embeddings, versioned_lessons — 3 separate memory systems |
| 04 | `04_MASTER_ORCHESTRATION_AUDIT.md` | two-entry-point parity, state machine, approvals, failure ladder, + orchestration trace simulation + 9 failure-scenario simulations |
| 05 | `05_MASTER_SECURITY_AUDIT.md` | policy engine, credential vault, RBAC, prompt injection resistance |
| 06 | `06_MASTER_INFRASTRUCTURE_AUDIT.md` | migrations, config completeness, queues, CI/CD, deployment configs |
| 07 | `07_MASTER_AI_EVALUATION_AUDIT.md` | metrics pipeline, benchmark objectives, regression gate, eval suite |
| 08 | `08_MASTER_PRODUCTION_READINESS_AUDIT.md` | test health, startup, observability, data safety, rate limiting |
| 09 | `09_MASTER_PERFORMANCE_SCALABILITY_AUDIT.md` | concurrency, blocking calls, DB performance, token/cost controls |
| 11 | `11_MASTER_ZERO_POLICY_AUDIT.md` | hallucination, hardcoding, leakage, dead code, infinite loops, circular deps, race conditions, silent exceptions |
| 10 | `10_MASTER_FINAL_CONSOLIDATION_AUDIT.md` | run LAST — merges all 10 prior reports (01-09 + 11), weighted scoring matrix, release decision |

(Numbering keeps 10 as "final" and 11 as "Zero Policy" so file order still
sorts mostly-sequentially without renaming anything you've already started
running.)

## Order to run them

1. `01` → `02` → `03` → `04` → `05` → `06` → `07` → `08` → `09` → `11`
2. `10` LAST, with all 10 prior Markdown reports + JSON sidecars available

## How to run each one

1. Open Claude Code in your project root (where `PROJECT.md` lives).
2. Paste the entire contents of `00b_AUDIT_STANDARDS.md` FIRST, then the
   numbered audit file, as one combined prompt (or reference it: "also
   follow the evidence schema and JSON output format in
   00b_AUDIT_STANDARDS.md").
3. Let it run fully read-only.
4. Save both outputs: `docs/reports/AUDIT_02_AGENT.md` AND
   `docs/reports/AUDIT_02_AGENT.json` (the JSON sidecar is what makes audit
   10 reliable — don't skip it).
5. Move to the next numbered file.

## Why this structure, not a single giant prompt

A single 20,000-line mega-prompt runs into the same problem your own
PROJECT.md history documents repeatedly: things get built, look wired, and
turn out to have zero real callers, or get wired into only one of two code
paths, or get silently regressed by a later change. Catching that requires
FOCUSED, evidence-demanding passes per layer — a giant prompt trades depth
for breadth and tends to produce generic, unverifiable output. 12 focused
passes, each demanding file:line evidence, is slower but actually
trustworthy.

## After all 12 are done

If audit 10 says **NOT READY**, work through its ordered, scoped fix list,
then re-run only the specific audit(s) whose findings you fixed (not the
whole suite), then re-run 10 one more time for a fresh consolidated
verdict.

If it says **READY**, wire its recommended post-launch monitoring
priorities into your alerting before you flip the switch.
