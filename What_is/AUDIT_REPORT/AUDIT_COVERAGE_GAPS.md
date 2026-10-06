# Audit coverage gaps: areas no audit has examined in depth

**Date:** 2026-10-06 · **Method:** every backend package, API router, fleet module, background loop and UI page was mapped against the audits done so far, then each area's test coverage was counted. The audits so far: our 15, Antigravity, Qoder, and the independent "Sol" production audit, whose 44 findings are already planned in `PLAN_PRODUCTION_AUDIT_REMEDIATION.md`.

**Size of the codebase:**
- backend: about 120,000 lines in 20 packages, including agents 45k (105 files), tools 31k (240 files), fleet 14k (50 modules) and API 9k (25 routers);
- 21 background loops;
- 19 UI pages.

An area counts as **covered** when an audit traced it and proved its behaviour by running it. Unit tests alone don't count.

## Gaps, ranked by risk

| # | Area | What exists | Covered so far | Why it matters | Priority |
|---|---|---|---|---|---|
| **G1** | **Every tool that executes, writes or reaches the network** (a sweep across the 213 tools) | 240 tool files | Bash and bhaskar sandboxes were audited. Sol then found a **third** executor (`python_snippet`) running on the host. Nobody has swept all of them | The same hole may exist in other tools: test runners, package scripts, linters, git hooks, browser, fetch | **P1** |
| **G2** | **Prompt-injection and adversarial content** | Agents read repository files, web pages, memory, logs and tool output | Not audited adversarially. Sol only says such content should be treated as untrusted | A malicious README, web page or stored "lesson" could steer an agent to leak, delete or run things | **P1** |
| **G3** | **The 21 background loops** (scheduler, leader election) | Fleet scan, enhancement monitor, prompt auto-rollback, retention, reindex, orphan recovery, consolidation, score computations, dependency auto-dispatch… | Only leader-pool sizing (Qoder H-4) and today's scan budget. **1 test** touches leader election | Loops run unattended and some start agents or change data: double runs, crashes, runaway cost, kill switches | **P1** |
| **G4** | **Scores and metrics correctness** | 9 score modules (agents, tools, prompts, memory, documentation, quality, security, test, architecture) plus benchmark, analytics, retrospective | Never audited. Sol found one ("no data = perfect score") | Scores drive routing, the regression gate and auto-rollback; wrong scores lead to wrong automatic decisions | **P1** |
| **G5** | **External integrations, live** | GitHub push and PR, Slack (including interactive approvals), Linear, web search and fetch, Voyage | GitHub PR flow has 11 mocked tests. **None has been run against the real service** | Credentials, rate limits, error paths, and approvals arriving through Slack | **P2** |
| **G6** | **Prompt versioning and auto-rollback** | `prompt_registry` versions, deploy, rollback loop | Only the regression gate (L6). The rollback loop has **2 tests** | It changes agent behaviour automatically, with no human in the loop | **P2** |
| **G7** | **Data lifecycle** | Artifacts (DB/S3), retention, privacy export and delete, DB growth, migration **downgrades** | Retention (audit 13, 21 tests). S3 path never run live. Downgrades have **3 tests** | Rolling back a release safely needs working downgrades; storage growth over months | **P2** |
| **G8** | **Concurrency across processes** | Multiple workers, two API instances, Redis outage, DB failover | Targeted cases only (epic locks, fan-out) | Duplicate side effects, lost approvals, stuck tasks under real parallel load | **P2** |
| **G9** | **Model and provider layer** | Anthropic plus Groq and Gemini adapters, fallback models, pricing table, thinking settings | Partly (audit 07 cost; today's thinking-on-Haiku bug) | Pricing errors break the budget cap; a wrong model setting can break every agent of one tier | **P2** |
| **G10** | **Observability correctness** | Structured logs, OpenTelemetry, metrics endpoints, Sentry, in-app alerts | Audit 08 confirmed they exist; Sol A13 (Sentry redaction) | Secrets in logs; alerts that never fire; traces that don't connect | **P2** |
| **G11** | **Strategic layer** | Goals, roadmap, executive agent → epics | Unit tests only (goals 11, roadmap 4, executive 10). No audit | The top of the planning chain; it was never run end to end | **P3** |
| **G12** | **MCP server** | 6 repository tools over stdio | **1 test**. Sol noted it exists | Authentication and exposure if an external client connects | **P3** |
| **G13** | **Frontend security** | Markdown and diff rendering, chat, terminal, CSP | Sol covered UX and CSP briefly; no frontend security audit | XSS through repository content shown in diffs, chat or markdown | **P3** |
| **G14** | **Supply chain and licensing** | Python and pnpm lockfiles, Docker base images, vendored comparison repositories | Vulnerability audits only (pip-audit, pnpm audit) | Licences, pinned images, SBOM | **P3** |

## Suggested order (after or alongside the 44-item plan)

1. **G1 dangerous-tools sweep.** Same method that found A01 and the bhaskar escape: every executing, writing or network tool gets a real attack script. It overlaps with Sol A01, A06, A09–A11, so do them together.
2. **G2 prompt-injection audit.** Planted malicious instructions in a repo file, a web page, a memory lesson and a tool output; prove agents don't obey them.
3. **G3 background loops.** For each of the 21 loops: trigger, leader-only, failure, kill switch, cost, and what it changes; force-run each once.
4. **G4 scores and metrics.** Recompute every score from known data; no-data and edge cases; check that the decisions using them are right.
5. **G6 prompt rollback + G9 providers + G10 observability.**
6. **G5 live integrations.** Needs your credentials and approval (GitHub token, Slack app, Linear key); a free or test workspace is fine.
7. **G7, G8, G11–G14.**

All of these can be done **without the Anthropic API** (real services plus a mocked model), except G5, which needs the integration services, not Anthropic.
