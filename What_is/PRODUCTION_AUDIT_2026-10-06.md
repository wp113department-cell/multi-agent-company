# Gridiron Developer Department — independent production audit

**Date:** 6 October 2026, Asia/Kolkata  
**Requested scope:** audit only; one Markdown deliverable; no application changes; no use of the unfunded Anthropic account.  
**Initial source revision:** bf0b424328b24bd307b4c848c1aa51164a82c409.  
**Concurrent source updates observed:** 162f0658 (Bhaskar Docker isolation), b830b77f (daily/budget-guarded fleet scans), cc4f1e4b (isolated enhancement APPLY worktrees), and f7006e9d (Barot delegation), plus further uncommitted scratchpad/test changes. These were authored outside this audit and preserved.

**Snapshot rule:** findings, line references, inventories and ratings apply to the initial audited revision unless explicitly qualified. The changing workspace is not certified by those checks. The Bhaskar mitigation was separately inspected; the newer scan/APPLY/delegation changes were not fully re-audited. A final release assessment requires a fixed post-repair revision.

## 1. Decision

**This project is substantial, but it is not ready for unrestricted production use.** It is a developer platform suitable for further testing and, after the release blockers are resolved, a supervised internal pilot. It is not presently a safe replacement for an established coding product when handling hostile repositories, confidential independent customer projects, or a public multi-user service.

My approximate production-readiness assessment is **53/100, or 5.3/10**. This is an evidence-based engineering judgment under the rubric below, **not a measured 53% probability of success, a certification, or the percentage of code completed**. A high feature count cannot compensate for an exploitable filesystem boundary or a broken deployment.

| Area | Weight | Rating / 10 | Weighted points | Reason |
|---|---:|---:|---:|---|
| Security, executable-code containment, privacy | 25 | 3 | 7.5 | Real auth and bash controls; alternate host execution, protected-file bypass, arbitrary workspace roots and browser/network weaknesses remain |
| Agents, tools and capability implementation | 20 | 7 | 14 | Real fleet and handlers; several accepted entry points fail; governance and environment availability are incomplete |
| Orchestration, concurrency, durable recovery | 15 | 6 | 9 | Real graphs, approvals, retries and worktrees; RQ checkpoint initialization and plan-edit ordering are defective |
| UI and user experience | 10 | 6 | 6 | Compiles and passes tests; pagination, history recovery, confirmation/error handling and streaming need work |
| Deployment, operations and disaster recovery | 15 | 4 | 6 | Production manifests exist; image context, API proxy, storage permissions and toolchain provisioning prevent reliable clean deployment |
| Verification and evaluation evidence | 10 | 7 | 7 | Strong static checks and large test inventory; broad live agent competence and production recovery are not established |
| Token/cost efficiency mechanisms | 5 | 7 | 3.5 | Routing, caching, compaction and caps are real; cost-mode tradeoffs, non-atomic budget checks and routing metadata need correction |
| **Total** | **100** | | **53** | **Production verdict remains NO while release blockers are open** |

The concurrent Bhaskar Docker change is a positive mitigation. Its source was reviewed, and a mocked missing-Docker probe confirmed refusal to fall back to host execution. Its real container behavior was not verified in this audit. It does not fix the independent host Python execution, symlink-policy, workspace-root, browser, deployment or routing issues. Therefore it does not change the overall release decision.

### Direct answers to your questions

| Your question | Answer supported by this audit |
|---|---|
| Are all agents really working? | **No blanket “yes” is justified.** All 85 contracts register; 78 regular wrappers reach the shared graph with handlers. However, 20 accepted synchronous names/aliases have incompatible calls, and research/DevOps background results are mishandled. Live competence of every agent remains unverified. |
| Are the tools real and attached? | **Mostly real.** All tool specifications captured from those 78 wrappers had handlers. There are 213 manifest entries, but additional real runtime tools lack manifest metadata. Availability of Docker, Node, browser binaries, GitHub CLI, credentials and target services is not proved by registration. |
| Is the system production-ready? | **No, for public or adversarial production.** A restricted internal pilot should follow the critical fixes and acceptance tests. |
| Does it have skills? | It has role prompts, global standards, procedural guidance and versioned prompts. **No native SKILL.md discovery/loading framework was found in the application.** |
| Is MCP connected? | A real six-tool stdio MCP **server** exists. **No application MCP client or configured third-party MCP connections were found.** Direct Python integrations are separate from MCP. |
| Does it learn? | Memory retrieval, explicit signals, historical routing and human-approved prompt/lesson changes exist. **Measured improvement over a held-out baseline is not established.** This is memory/prompt adaptation, not model-weight training. |
| Is it fast and cheap? | There are credible efficiency mechanisms. **Actual task latency, throughput, success-per-dollar and superiority to competing products were not measured.** |
| Can I trust it more than Cursor, Claude Code or Antigravity? | The source is inspectable and configurable, which is valuable. **Present evidence does not support trusting it more.** Demonstrated isolation, reproducible task quality, recovery and user experience must come first. |

## 2. What was actually checked

This audit used source tracing, independent specialized reviews, safe local reproductions, registry/handler introspection, static analysis, frontend tests and a temporary production build. Prior audit reports and the master guide were treated as claims to verify, not as proof.

**No paid LLM/provider request was made.** Provider-dependent checks used dummy or empty credentials; external provider requests were not made. Network-dependent test paths were blocked or mocked, and database/Redis-dependent probes used deliberately unreachable addresses. Telemetry was disabled for the temporary frontend build. No live task was launched through your provider accounts, no existing database was mutated, and no existing service was started or stopped. The local secret values were not printed or used.

Temporary probes, logs, a frozen source checkout and frontend build output were kept under /tmp. **This report is the only file created in the project by this audit.** Separate source edits and a new commit appeared during the audit; they were preserved. I did not make or revert those edits.

### Evidence labels

- **R:** locally reproduced with real implementation code and harmless temporary data.
- **M:** reproduced with mocked dependencies or captured call/signature binding; no live external system.
- **S:** confirmed by tracing source/configuration. The resulting deployment/exploit scenario was not executed.
- **U:** live behavior, service connectivity, performance or quality remains unverified.

### Results obtained

| Check | Result and limit |
|---|---|
| Backend Ruff | Passed, entire backend check; no cache writes requested |
| Backend strict mypy | Passed: 498 source files; strict mode with missing third-party imports ignored |
| Backend Black check | Passed for app, tests, migrations and scripts |
| Backend focused offline tests | **70 passed, 2 deselected, 3.82 seconds**, against frozen initial revision; policy, dependency ordering, circuit breaker, selected cost-profile checks and eval schema/judge behavior |
| Backend test collection | **9,041 collected; 21 deselected; 9,020 selected** at the initial revision. Collection is not execution |
| Broader offline test attempts | Did not complete cleanly under intentionally blocked network/database/thread-dependent paths and were stopped. They are not reported as passing, or counted as confirmed application regressions |
| Frontend TypeScript | Passed, no emit and incremental disabled |
| Frontend ESLint | Passed |
| Frontend unit tests | **59 passed across 10 files, 12.19 seconds** |
| Frontend production build | Passed in a source-only /tmp copy; 20 static pages generated; compilation approximately 2.4 minutes |
| Migration topology | Alembic reports **063 as the single head**. No database migration was applied |
| ORM metadata | **43 mapped tables**. This is not an inventory of tables in the live database |
| OpenAPI generation | **131 paths / 146 operations**, schema generated without starting application lifespan |
| Fleet imports and contracts | **99 modules imported / 85 registered contracts** |
| Regular runner capture | **78 wrappers captured**, zero missing handlers among tools supplied to those graph calls |
| Tool manifest | **213 entries:** 147 low, 54 medium, 12 high risk |
| Browser journeys and production compose deployment | **Not run** |
| Real agents, funded providers, external integrations, crash/restart drills and sustained load | **Not run** |

The seven agents outside the regular wrapper capture are architect, barot_agent, chat_agent, decomposer, executive, manager and pm. Their different entry-point forms are not evidence that they are broken. Their specialized paths were inspected separately.

### Concrete probes

| Probe | Observed result | Interpretation |
|---|---|---|
| Host Python snippet with temporary workspace | Created a marker in a sibling directory outside the workspace | The snippet runner's cwd/environment scrubbing is not filesystem isolation |
| Original Bhaskar subprocess | Normal outside-file open denied; saved original open and a child /bin/cat could read the same temporary sentinel | Python monkeypatches were bypassable; historical finding qualified by the subsequent Docker commit |
| Protected .env symlink | Direct sentinel .env access denied; an innocuous symlink pointing to it allowed and read | Protected-path rules inspect the spelling rather than the canonical target |
| Chat workspace creation | Actual handler accepted an arbitrary path with repository resolution mocked to return null | The handler accepts the client-chosen root despite unsuccessful repository resolution; not a live HTTP/database test |
| Chat history ownership | A second actor retrieved the first actor's sentinel history through the actual route function | Resource ownership is absent; this was a handler probe, not a full HTTP authorization test |
| Browser IPv6/DNS-error guard | Mocked hostname resolution failure caused the safety guard to allow the URL | Browser URL checks fail open in that branch |
| Plan step removal | Removing an unrelated earlier step left a surviving dependency at index 2 in a two-item plan; execution fell back to consumer before prerequisite | Rejection corrupts dependency indices |
| Empty agent benchmark | Never-run agent scored **1.0**, verification and compile coverage both **1.0**, hallucination proxy **0.0** | Missing evidence is incorrectly presented as perfect performance |
| Daily budget interleaving | Starting at $0.99 under a $1 cap, two checks succeeded; two simulated $0.50 completions produced $1.99 | Check-then-record is not an atomic hard spending cap; no real spend occurred |
| Fresh RQ job entry point | Pipeline and worker-agent checkpointers remained InMemorySaver; zero PostgreSQL initializer calls | Shipped RQ worker path does not initialize durable savers |
| New Bhaskar Docker mode | Mocked Docker-unavailable result returned an error and refused host fallback | Missing-dependency behavior is covered; successful real-container isolation remains unverified |

## 3. Verified strengths worth preserving

1. Production startup enforces JWT/RBAC, a nondefault administrator password, an encryption key and durable workspace configuration. HttpOnly cookies, production Secure flags and authentication rate limits are implemented.
2. The shared graph checks tool names, command/path policies, submission contracts and real verification signals. Dangerous shell commands are blocked by the outer graph before handler execution.
3. Generic bash sandboxing has a read-only root filesystem, non-root execution, memory/CPU/PID/tmpfs limits and explicit timeout cleanup. Missing Docker fails closed.
4. Git worktrees, human approvals, Dev → QA → reviewer loops, bounded retries, failure escalation and event/status tracking are genuine code paths.
5. Cost profiles, small-task routing, model routing, cache breakpoints, context compression, token telemetry and spend accounting are implemented.
6. Memory has real PostgreSQL/vector queries, quality heuristics, deduplication, retrieval feedback, provenance and a human-reviewed versioned lesson lifecycle.
7. The UI implements repository/task screens, approval packages, diffs, fleet enhancement review, metrics, notifications, SSE activity and terminal tabs.
8. Strict static analysis, migration history, many tool-specific tests, frontend tests and CI checks provide a useful foundation.

Preserve these mechanisms while fixing their boundary and integration gaps. Do not “fix” a missing Docker daemon by turning sandboxing off.

## 4. Fix register

**P0:** blocks exposure to untrusted code/users or distribution of unsafe images.  
**P1:** blocks reliable execution/recovery, confidentiality guarantees or essential production operation.  
**P2:** important robustness/product gap.  
**P3:** further hardening and polish.

### Security and isolation

| ID | Priority / evidence | Finding and source | Required fix and acceptance condition |
|---|---|---|---|
| A01 | **P0 / R,S** | Arbitrary Python executes on the backend host. backend/app/tools/execution/python_snippet.py:98; backend/app/tools/execution/safe_subprocess.py:51. Scrubbing environment and setting cwd do not contain filesystem, processes or network | Route every executable tool through a worker sandbox. Test Python, Node, test suites, package scripts and nested child processes against outside-workspace sentinels; all unauthorized access must fail |
| A02 | **Historical P0; mitigation added / R,M,S,U** | Initial Bhaskar sandbox exposed saved original functions and unrestricted child-process access. backend/app/agents/bhaskar_sandbox.py:142 in the initial revision. New revision adds _run_in_docker at :416 and defaults to Docker through backend/app/config.py:1855. Mocked Docker-unavailable behavior refused host fallback | Validate the new Docker backend in a disposable execution environment. Reject the weaker process backend in production. No host mount, no fallback, quota/timeout/child-process cleanup and network restrictions must be demonstrated. The old bypass is not asserted against the new default |
| A03 | **P0 / M,S** | Actual chat handler accepts caller-supplied arbitrary repo_path with repository resolution mocked to fail. backend/app/api/chat.py:136; terminal root selection at backend/app/api/terminal.py:165; sandbox mount at backend/app/policy/sandbox.py:208. This was not a live HTTP/database authorization test | Accept an authorized repo_id and resolve its registered workspace server-side. Reject nonexistent, unauthorized, out-of-root and symlinked roots before creating sessions or mounts |
| A04 | **P0 / R,S** | check_path_in_worktree resolves for containment but returns check_path(file_path), checking the original spelling. backend/app/policy/engine.py:121; read handler at backend/app/tools/filesystem/read_file.py:125 | Check both original and canonical protected targets; address symlink race windows where possible. Test read/write/delete via file and parent-directory aliases to .env, .git and key files |
| A05 | **P0 before image distribution / S** | No applicable root/backend .dockerignore. backend/Dockerfile:18 copies the backend context, which contains backend/.env. Frontend build copies repository context at apps/web/Dockerfile:21 | Add explicit context exclusions and selective source copies; inject secrets at runtime. Build with fake-secret canaries and inspect layers/context/cache. This audit did not build or prove publication of an exposed image |
| A06 | **P0 / M,S** | Browser checks only initial goto URL; redirects, page fetches, iframes and clicks are not intercepted. DNS errors allow access; IPv4-only resolution misses IPv6. backend/app/repo_tools/browser_driver.py:47,114,153 | Enforce request-wide browser policy and network isolation. Fail closed on unresolved addresses. Validate IPv4/IPv6, redirects, rebinding and subresources in an isolated fixture network |
| A07 | **P0 before separate-customer SaaS / R,S** | Role authentication is not resource ownership. Chat models lack owner fields; history ignores actor. backend/app/models/chat.py:24; backend/app/api/chat.py:385; task listing backend/app/api/tasks.py:203. History exposure was reproduced through the handler, not a full HTTP authorization test | Define trusted-team sharing explicitly. For customer tenancy, add owner/tenant/project memberships and scoped authorization to reads, mutations, streams, artifacts and secrets. Execute a two-user/two-project access matrix |
| A08 | **P1; P0 for confidential cross-project separation / S** | Versioned lessons are globally matched and inserted without repo_id; promotion writes unscoped learning signals. backend/app/fleet/versioned_memory.py:115,158,281,584. Global LessonStore injection is unscoped at backend/app/agents/base_graph.py:1625; learning queries allow NULL repo_id at backend/app/memory/store.py:1398 | Carry scope through lesson publish/merge/promote/rollback/cache/retrieval. Separate explicitly approved global generic knowledge from private project content. Demonstrate that project A facts never appear in project B |
| A09 | **P1 / S** | URL checks validate an address before urllib/curl resolves again. backend/app/agents/tool_security.py:91,151,195 | Pin the validated address while retaining TLS hostname/SNI; revalidate every redirect. Controlled alternating DNS must never contact private endpoints |
| A10 | **P1 / S** | Screenshot accepts arbitrary host destination. backend/app/repo_tools/browser_driver.py:132; backend/app/tools/browser/browser_tools.py:219 | Generate artifact paths inside a session-owned directory; validate canonical paths and links. Reject absolute escapes, traversal and symlinks |
| A11 | **P1 / S** | Bash bridge egress is broad; test/migration variants can use host networking and migration execution receives the platform DATABASE_URL. backend/app/config.py:1200,1274; backend/app/agents/tools.py:4315 | Isolate control-plane DB/Redis from job networks. Use target-project/test credentials and controlled egress. Hostile job code must not reach control-plane services, metadata endpoints or unrelated internal networks |
| A12 | **P1 / S** | Logout removes the cookie; password change does not revoke already copied JWTs. Live-role checks do not check password/token version. backend/app/api/auth.py:206,219; backend/app/auth/revocation.py:32 | Introduce session/token versions or revocation, short access lifetimes and controlled refresh rotation. An old token must fail after password change, logout/revocation and refresh attempts |
| A13 | **P1 / S** | Sentry before_send returns events unchanged despite a “Never send secrets” comment. backend/app/main.py:74. Existing masking is not a universal telemetry guarantee | Centralize redaction/drop rules for exception text, breadcrumbs, tool inputs and attachments. Fake canaries must be absent from captured outbound events; no actual telemetry leak was demonstrated |
| A14 | **P1 / S** | Privacy export promises more than it returns: identity/roles plus capped audit rows; tasks/epics retain created_by strings and chat lacks attributable ownership. backend/app/api/privacy.py:86; backend/app/db/models.py:177,553 | Inventory attributable data, paginate exports and specify deletion/retention behavior truthfully. Do not treat the existence of a privacy endpoint as legal-compliance proof |

**Important boundary correction:** a direct ChatAgent handler can contain permissive confirmation logic, but its outer graph performs the shared command policy first (backend/app/agents/chat_agent.py:4617; backend/app/agents/base_graph.py:1080). A mocked direct-handler invocation is therefore **not** reported as a production hard-deny bypass.

### Agents, orchestration, verification and cost

| ID | Priority / evidence | Finding and source | Required fix and acceptance condition |
|---|---|---|---|
| A15 | **P1 / M,S** | /run-sync sends description to accepted runners whose real argument is doc_request, task_description, focus, error_description or refactor_instructions. backend/app/api/specialized_agents.py:771. Background dispatch already adapts kwargs at :486 | Use the shared argument adapter consistently. Exercise all 67 accepted standalone names/aliases against signature-aware fake runners |
| A16 | **P1 / S** | Research/DevOps return tuples, but background result processing expects AgentResult.summary/status/findings. backend/app/agents/research.py:109; devops.py:119; backend/app/memory/hooks.py:76; specialized_agents.py:514 | Normalize every runner return type before memory/status/artifact handling. A successful research/devops run must produce one correct completed artifact and token record |
| A17 | **P1 / M,S** | RQ worker entry point only asyncio.run()s the job; persistent savers initialize only in FastAPI lifespan. backend/app/pipeline/queue_adapter.py:151,178; backend/app/main.py:1569; docker-compose.prod.yml:169 | Initialize and close savers within the worker/job event-loop lifecycle. Prove plan approval, worker restart, API restart and cross-process resume using disposable PostgreSQL/Redis |
| A18 | **P1 / S** | PostgreSQL saver initialization falls back to MemorySaver on error and readiness does not report saver durability. backend/app/pipeline/graph.py:28; backend/app/agents/base_graph.py:69 | Fail closed for required production persistence or explicitly expose degraded mode and block affected work. A DB/saver initialization failure must never silently claim durable operation |
| A19 | **P1 / R,S** | Rejecting earlier plan steps does not renumber surviving depends_on indices. Editing depends_on is also ignored despite the explanatory text. backend/app/pipeline/graph.py:121,132,149 | Prefer stable step IDs. Otherwise remap indices and validate the resulting DAG atomically. Consumer-before-prerequisite reproduction must be fixed; invalid plans should block rather than silently lose ordering |
| A20 | **P1 when fan-out enabled / S** | Parallel subtasks share one worktree; the lock serializes git add/commit, not edits or tests. backend/app/agents/manager.py:312,722,1665 | Use per-subtask branches/worktrees with verified integration, or enforce disjoint write sets and serialize conflicting work. Test overlapping edits and QA during concurrent writes. Default sequential execution limits this risk |
| A21 | **P1 / S** | Mandatory-looking quality reviews fail open: gate exceptions are logged and converted to no blocking reason. backend/app/agents/manager.py:927; individual gate helpers also return None on failure | Give skipped, passed, failed and unavailable checks distinct states. Risk-required gates must block on unavailable evidence; test reviewer timeout, malformed output, scanner failure and dependency service outage |
| A22 | **P1/P2 / M,S** | 67 contract-declared tools lack manifest entries; 54 missing-manifest names appeared in captured runs. Unknown risk is treated as not high risk; declaration enforcement concentrates on known high-risk tools. backend/app/fleet/tool_manifest.py:1907; tool_discovery.py:145 | One authoritative schema/handler/risk/permissions registry. Fail closed on unknown side-effect tools; enforce contracts at all risk tiers and validate registry consistency in CI |
| A23 | **P1 / S** | Idempotency checks response cache before work and inserts after work, allowing simultaneous duplicate side effects. Actor/resource scope is incomplete. backend/app/middleware/idempotency.py:66,96 | Atomically reserve actor+route+resource+body-bound keys with in-progress/outcome state. Concurrent duplicates must yield one operation; mismatched reuse must conflict |
| A24 | **P1 / R,S** | Daily spending is checked before a request and recorded after completion; no reservation covers in-flight calls. Redis loss falls back to per-process totals. backend/app/fleet/spend_guard.py:98,114,131,262 | Atomically reserve estimated worst-case spend and reconcile usage. Define outage behavior and maximum allowed overshoot. Test multiple workers, restarts, stream failures and budget-edge concurrency without paid calls |
| A25 | **P1 / R,S** | No-data benchmarks score perfect. The hallucination metric is a reflection proxy, not observed factual correctness. backend/app/fleet/benchmark_manager.py:172,183,215 | Expose unknown/insufficient-data status and minimum sample counts. Never promote unseen agents on synthetic perfect scores. Track actual verifier outcomes and task quality |
| A26 | **P1/P2 / S,U** | CI regression gate tests a deliberately regressed fixture rather than this commit against a previous persistent baseline. Live eval corpus is 11 tasks and not comprehensive execution coverage. .github/workflows/ci.yml:124; backend/tests/evals/tasks.json | Store versioned baseline artifacts; run held-out repository tasks with independent outcomes. Missing judge results must be unassessed, not presented as proven quality. All critical agents and provider modes need coverage |
| A27 | **P2 / S** | Route output limits are metadata: main call hardcodes max_tokens=8096. Per-agent provider metadata is not implemented as mixed-provider execution. backend/app/agents/base_graph.py:1970; fleet/model_router.py:76 | Pass effective model limits and validated provider capabilities. Prove provider dispatch, vision/tool format handling and output/context caps with contract tests |
| A28 | **P2 / S** | Manifest timeout_s and verification_required are not centrally guaranteed. Some handlers implement separate controls. Fleet “availability” is largely static lookup, not environment probing. backend/app/fleet/tool_discovery.py:94 | Probe required executable/service dependencies and enforce consistent timeouts, cancellation, result schemas and verification in the dispatcher. Distinguish installed, connected, authorized and unavailable |

**A15 affected synchronous names:** agent_roster_doc_agent, api_docs_agent, arch_reviewer, architecture_doc_agent, architecture_reviewer, bug_fix, cicd_agent, dependency_agent, deployment_guide_doc_agent, devops, docker_agent, migration_guide_doc_agent, monitoring_agent, readme_agent, refactor_agent, research, research_agent, security_reviewer, sql_agent and tool_catalog_doc_agent. These are **20 accepted names/aliases representing 18 distinct agents**, not 20 broken implementations.

**A16 affected background names:** research, research_agent and devops. An LLM may finish useful work before tuple handling fails, so this can waste spend.

**A22 real omitted side-effect examples:** git_commit_change, memory_curate_write, memory_promote_lesson and resolve_merge_conflict. Their handlers exist; the defect is incomplete governance metadata. The shared executor still rejects tool names not advertised to the model. This is not a claim that an agent can call every arbitrary Python function.

The old backend/app/pipeline/dispatcher.py selects a capability name but invokes fixed frontend/QA/backend runners. No production caller was found. Treat it as misleading dormant infrastructure, not as the live fleet dispatch implementation.

### Deployment, UI and operations

| ID | Priority / evidence | Finding and source | Required fix and acceptance condition |
|---|---|---|---|
| A29 | **P1 / S,M** | Frontend rewrite defaults to localhost:8000; Docker build supplies no backend URL. In the frontend container this points at itself. apps/web/next.config.mjs:59; apps/web/Dockerfile:18; docker-compose.prod.yml:209 | Wire a server-side backend URL or reverse proxy at the correct build/runtime stage. Temporary build proved backend:8000 can be embedded. Verify login, authenticated API, SSE and terminal WebSockets in the actual deployment |
| A30 | **P1 / S** | UID 10001 backend runs without creating/chowning fresh /data volumes. backend/Dockerfile:13,20; docker-compose.prod.yml:131,143,183 | Add controlled ownership initialization. From fresh disposable volumes prove clone, worktree creation and background-process registry writes as the non-root user |
| A31 | **P1 / S,U** | Supplied backend image lacks Docker CLI/daemon, Node/npm/pnpm, gh and installed Playwright browsers. Production manifest supplies no isolated execution service and acknowledges sandbox failure. backend/Dockerfile; docker-compose.prod.yml:134 | Provide trusted external execution/toolchain workers and capability health checks. Do not grant unrestricted host Docker socket access as a routine shortcut. Unavailable tools must be clearly disabled |
| A32 | **P1/P2 / S** | Task list defaults to 20; frontend discards nextCursor and has no paging. backend/app/api/tasks.py:208; apps/web/lib/api.ts:115; apps/web/app/tasks/page.tsx:99 | Add cursor pagination/search. Verify discovery of more than 20 matching tasks, including older failed/blocked work |
| A33 | **P1/P2 / S** | Task is created before image upload; attachment failure makes resubmission create another task. apps/web/components/NewTaskForm.tsx:59 | Retain task ID for attachment retry or implement an idempotent supported creation workflow. Inject failed/interrupted uploads and verify one task |
| A34 | **P2 / S** | High/low priority is selected in the form but omitted from the createTask payload. NewTaskForm.tsx:22,61,301; apps/web/lib/api.ts:130 | Send and persist selected priority. Verify all three UI choices reach backend scheduling |
| A35 | **P2 / S** | Task list discards query errors; activity stop/resume ignores HTTP failure; API lacks centralized expired-session behavior. tasks/page.tsx:34; stream/[taskId]/page.tsx:287; lib/api.ts:25 | Display errors/retry/auth expiry. Only clear inputs or reconnect after success. Test 401,403,409,500 and disconnected network |
| A36 | **P2 / S** | Activity reconnect replays bounded backend history but frontend blindly appends it; arrays grow across reconnects. backend/app/services/activity_stream.py:336; stream/[taskId]/page.tsx:224 | Stable event IDs, replay cursor and deduplication; bounded/virtualized rendering. Reconnect repeatedly without duplicate events |
| A37 | **P2 / S** | Chat loses visible session/history on refresh; confirmations resolve before backend success; clean premature SSE EOF lacks reattach handling. apps/web/app/chat/page.tsx:233,325,589,612; backend/app/api/chat.py:385 | Add authorized session browser/history restoration, success-based confirmation state and retry-safe stream recovery. Verify refresh, navigation, failed approvals and premature EOF |
| A38 | **P2 / S,U** | Every text/terminal delta maps message state and smooth-scrolls; terminal package is eagerly imported. apps/web/app/chat/page.tsx:277,379; TerminalTabs import | Batch streaming updates, lazy-load terminal, virtualize long transcripts. Measure input responsiveness, memory and render time during lengthy task output |
| A39 | **P1 / S,U** | Production backup schedule is not wired into compose; restore verification checks little more than migration metadata. scripts/backup_db.sh:69; scripts/restore_db.sh:73; scripts/systemd/gridiron-backup.timer | Install automated off-host backups, alert on failures, record RPO/RTO and restore all required state into a disposable environment, including encryption key availability, repos/artifacts and queue/checkpoint decisions |
| A40 | **P1 / S** | Health can be green with no loaded fleet, no RQ worker, no sandbox or unwritable job storage. backend/app/main.py:2082,2089 | Separate liveness from readiness. Check required fleet, worker heartbeat, saver durability, storage and execution capabilities; reachable Redis alone is not a working worker |
| A41 | **P2 / S** | Browser CI uses mocked backend; load tests disable auth/rate limiting and hit lightweight endpoints. Workflow accepts token as ordinary input and directly interpolates input into shell. .github/workflows/ci.yml:291; load-test.yml:28,68,145 | Add disposable production-stack journeys and execution-load tests. Use environment secrets for tokens and safely quoted variables for inputs; fix failure-log path |
| A42 | **P2 / S** | Local run.sh exposes development DB/backend broadly, lacks durable DB volume and suppresses migration failures. run.sh:39,53,59 | Keep explicitly development-only. Production setup must use corrected manifests and fail visibly on migration problems |
| A43 | **P2 / S** | Outbound alerts are one-shot best-effort delivery; no durable retry/outbox. No inbound CI/GitHub webhook receiver was found. backend/app/services/alert.py:20; backend/app/main.py:1086 | Add signed/replay-protected incoming events when needed and durable outgoing delivery with retries/dead letters. Verify deduplication and outage recovery using fixtures |
| A44 | **P3 / S,U** | Accessibility lint is not keyboard/focus/browser accessibility proof. Modal focus trapping, complete terminal-tab navigation and automated axe checks are incomplete; frontend image runs as root; CSP permits unsafe-inline | Add keyboard/focus/axe journeys, non-root frontend runtime and feasible nonce/hash CSP. Preserve current React escaping and existing dialog labels |

### Why the shipped deployment is not enough

There is a production compose file, and it correctly enforces several secure defaults. Nevertheless, clean deployment must make **frontend → API → Redis worker → durable graph → executable tools → verified result → human approval → Git output** work together.

Currently the frontend destination, data-volume ownership, missing execution toolchain and RQ checkpoint initialization break that chain at different points. A backend /health response cannot certify the whole chain. Successful frontend compilation also cannot certify it.

Docker context rules are documented by [Docker's build-context documentation](https://docs.docker.com/build/concepts/context/): context files are available to COPY, and .dockerignore controls exclusions. Git ignore rules are not a substitute.

## 5. Agent and tool reality

The agents are role-specific wrappers around shared provider/graph machinery, with prompts, tool lists, contracts and some dedicated control flow. They are not 85 independently trained models or autonomous employees. Specialist separation is useful when it actually enforces authority and independently verifies outputs.

| Layer | Verified | Still required before calling it production-working |
|---|---|---|
| Registration | 85 contracts load; 99 modules import | Stable bootstrap in each execution process |
| Regular wrappers | 78 captured graph calls contain handlers for all supplied tools | Real tasks and outcome checks per role |
| Standalone API | 67 eligible names/aliases | Fix synchronous argument binding and tuple return normalization |
| Pipeline agents | PM/architect/decomposer graphs and human review exist | Funded E2E validation and durable cross-worker approval/resume |
| QA/reviewer | Real commands, submissions and flags exist | Adversarial job isolation; no false passes after unavailable tools or stale evidence |
| Barot | Synthesizes temporary profiles using existing read-only tools | Its full write/bash temporary scope raises NotImplementedError; do not market it as arbitrary new coding capability |
| Bhaskar | Generates Python and evaluates execution result | Secure deployment of new Docker backend; successful script execution still does not prove answer correctness |
| Fleet improvement | Scans, proposals, human-approved apply/prompt/lesson workflows exist | Scope, independent baseline, canary and rollback evidence |
| Manifest | 213 entries with risk/timeout/verification descriptions | Complete authoritative coverage and real enforcement |
| External integrations | Direct web/GitHub/Slack/Linear/API tools exist | Installed executables, credentials, grants, live service smoke tests and failure handling |

Runtime tools can differ from a contract because of phase-specific helpers, shared Git-context tools and optional features. A mismatch should be reviewed individually. Some differences are intentional; unknown side-effect permission should not become an implicit allow.

## 6. Skills, MCP, search, scraping and webhooks

| Capability | Current reality | Useful next addition |
|---|---|---|
| Skills | Role Markdown, standards, guidance, prompt registry and procedural memory | SKILL.md-style bundles with description/trigger, scoped tools, trusted references, acceptance checks, versioning and on-demand loading |
| MCP server | backend/app/mcp/server.py exposes six repository-intelligence tools over stdio | Compatibility/auth testing and documented invocation, if external clients need it |
| MCP client/connections | No client framework or configured third-party connections found; internal agents use direct Python tools by design (docs/adr/005-mcp-not-primary-tool-access.md) | Optional client gateway with explicit user grants, server allowlists, timeouts, provenance and tool-schema validation |
| Web search | DuckDuckGo query returns up to five results with capped snippets; seven contracts declare it; chat lacks direct web_search | Reliable search adapter with source dates, links, primary-source preference, provider fallback and query/result caching |
| URL fetch | Real fetch with ordinary initial/redirect checks and capped output | Address-pinned transport, MIME/size/time limits, clean extraction and provenance |
| Browser/scraping | Playwright navigation, DOM/text/action/screenshot tools exist | Secure browser workers with all-request egress rules, extraction validation and browser-based acceptance tests |
| Crawling | No dedicated managed crawler/extraction-quality pipeline found | Add only if multi-page research is a real use case: queues, budgets, deduplication, change detection, robots/rate handling and approved authenticated access |
| Incoming webhooks | No CI/GitHub receiver found | Signed events, delivery-ID deduplication, replay window, bounded payload and task/repo authorization |
| Outgoing webhooks | Alerts and Slack interactions exist | Durable outbox, retries, backoff, signing, dead letters and UI delivery status |

Recommended initial skill bundles for this use case:

1. **Repository onboarding:** map architecture and commands, identify protected areas, validate environment and create a concise persistent project guide.
2. **Bug reproduction:** isolate a failing example, collect evidence, implement the smallest fix and run targeted regression checks.
3. **API/backend work:** auth/authorization, schema validation, migrations, OpenAPI contracts and rollback decisions.
4. **Frontend work:** browser reproduction, responsive states, accessibility, screenshot evidence and console/network checks.
5. **Security review:** trust boundaries, secret handling, dependencies, hostile repository tests and finding severity.
6. **Test/verification:** choose relevant suites, prohibit claiming success without verifiers and preserve result provenance.
7. **Dependency upgrade:** official documentation lookup, compatibility checks, lockfile integrity and vulnerability verification.
8. **Release/operations:** staged rollout, health/readiness, backups, restore drills, observability and incident/rollback procedures.

Recommended MCP connections **only when the task benefits**: GitHub issue/PR access, issue tracker, official documentation, approved design references and read-only staging observability. Add database access only with explicit target-scoped read-only or test credentials. Do not connect everything merely to increase capability count.

Native direct tools may be preferable to MCP for local code operations. MCP is an integration protocol, not proof of intelligence, safety or quality.

## 7. Learning and self-improvement

Implemented learning mechanisms include retrieval of prior lessons, semantic project memory, task/failure signals, helpfulness feedback, historical agent performance, prompt versions, curator review, regression-check machinery and rollback paths.

They can improve later decisions. They can also preserve stale or incorrect advice. **This audit did not establish that task success improves over time.** The current benchmark's no-data perfect score and reflection-based hallucination proxy make that claim particularly weak.

Economy mode disables automatic lesson extraction, reflection, critique and replanning. Memory retrieval and explicit feedback may still run. Consequently “all agents continuously learn after every task” is not an accurate description of the default.

To demonstrate improvement:

- Establish a held-out suite of realistic repository tasks with hidden acceptance tests and known failure classes.
- Compare the same model and budget with memory off/on, and before/after a proposed prompt or skill change.
- Record completed-correct tasks, false-success claims, regressions, unauthorized actions, cost and latency, with uncertainty and multiple runs.
- Keep proposed lessons drafted until verified/approved; require provenance and project scope.
- Canary a new prompt or lesson version, promote only when evidence improves, and retain automatic rollback.
- Treat fetched pages, repository instructions, logs and memories as untrusted data. They must not grant tool permissions.
- Do not train model weights or silently modify the platform merely because an agent proposes an improvement.

The eight “memory tiers” in the guide are useful logical categories. Their count does not itself establish eight independent learning algorithms.

## 8. Models: what should perform which task?

### Actual configuration

At the initial revision every registered agent has an explicit row in backend/app/fleet/agent_models.json:

- **75** configured for claude-sonnet-5.
- **9** configured for claude-opus-4-8.
- **1** configured for claude-haiku-4-5-20251001.

That is configuration, **not observed effective usage**. Default COST_MODE=economy caps routed models to the router/Haiku tier, caps turns to 15 and disables optional planning auxiliaries, reflection, critique, replanning, lesson extraction and the three LLM security/architecture/dependency reviews. Balanced also omits those three reviews. Quality preserves them.

Current model documentation was checked, but your account's access, balance and live model acceptance were not queried. Existing Sonnet 5 / Opus 4.8 IDs are not called invalid merely because newer models exist.

### Suggested routing policy

This table is my workload recommendation, not a benchmark result from your project.

| Task | Recommended starting tier/model family | Escalation rule |
|---|---|---|
| Intent routing, labels, short summaries, simple extraction | Claude Haiku 4.5; optionally GPT-6 Luna through an implemented provider adapter | Escalate on ambiguity, repeated schema failure or scope/risk uncertainty |
| Routine bug fixes, API endpoints, tests, frontend components, documentation tied to code | Claude Sonnet 5.5; optionally GPT-6.1 Sol | Escalate when targeted tests fail repeatedly or multi-module dependencies remain unresolved |
| Architecture, complex concurrency/recovery bugs, security design, multi-service changes | Claude Opus 5.5; optionally GPT-6 Astra | Use selectively with bounded evidence/context, not for every turn of every task |
| Particularly difficult long-horizon reasoning | Evaluate Claude Fable 5.1 only if lower tiers demonstrably fail | Require task-level evidence that higher cost improves completed-correct outcomes |
| QA execution, linting, migration checks, dependency/security scanning | Deterministic tools first; small model for interpreting reports; stronger model for diagnosis | Tool results remain authoritative regardless of model explanation |
| Review of a risky patch | Strong reviewer with separate context/evidence, plus deterministic scanners | Independence must come from evidence and verification; a separate prompt alone is insufficient |
| Retrieval/indexing | Embedding model plus exact symbol/path search | Choose dimensions/token limits deliberately; changing from the current 1536-dimensional schema requires an evaluated index/migration plan |

The current Claude catalog distinguishes Haiku, Sonnet, Opus and Fable roles; the current OpenAI catalog distinguishes Luna, Sol and Astra. Their documented capabilities support testing this tiered approach, but they do not establish which is best on your repositories. [Claude models](https://platform.claude.com/docs/en/models/overview), [OpenAI model catalog](https://developers.openai.com/api/docs/models/all).

OpenAI integration would require a real provider adapter; changing the provider string in agent_models.json is insufficient today. The official coding guide discusses current general-purpose models for coding. [OpenAI coding guidance](https://developers.openai.com/api/docs/guides/code-generation).

**Do not upgrade model IDs blindly.** Validate tool schemas, vision blocks, thinking settings, output caps, context limits and pricing in a staging capability check. Prices need model/version-specific accounting; a string containing “sonnet” is not enough for every future generation.

For this project, I would use a **Sonnet/Sol-level coding default, deterministic verification, and risk-based Opus/Astra escalation** after the safety fixes. Use Haiku/Luna for focused low-risk work and routing. Sending every demanding task to Haiku to save tokens can increase retries or lower correctness; sending every task to the largest model increases cost without established benefit.

## 9. Token efficiency and speed

### Mechanisms that are real

- Rules-first task classification and a small fallback classification request.
- Smaller specialist context and bounded agent turns.
- System/history prompt-cache breakpoints.
- Context condensation and prioritized memory injection.
- Scoped tools and reduced schemas.
- Token accounting, per-run budget controls, daily spend ledger and circuit breakers.
- Optional parallel subtask waves and per-tier cost modes.

### Tradeoffs and gaps

1. Economy saves auxiliary calls partly by omitting review/learning features. The UI should explain the actual tradeoff.
2. Optional reflection on every quality-mode turn can add significant calls; invoke it based on failures/risk when evaluation supports that.
3. The spending guard is a threshold check, not a reservation system; concurrent requests can exceed the cap.
4. Output caps and provider routing must be effective, not just declared metadata.
5. Long tasks should send changed/relevant symbols and verified tool summaries rather than repeatedly scanning whole repositories.
6. Parallel work must be isolated; concurrency that corrupts a shared worktree is not a speed improvement.
7. Cache effectiveness must be measured through actual cache-read/write usage, not assumed from cache_control presence.
8. Use large models to resolve hard blockers and small models for focused inexpensive stages. Optimize **cost per correctly completed task**, not raw tokens alone.

### What speed can be stated honestly?

The UI test/build durations are measured local checks. The production build reported approximately **102 kB shared first-load JS**, **194 kB on chat**, **122 kB on tasks**, and **125 kB on task detail**. These are bundle observations, not latency of an agent task.

Real task time-to-first-output, queue delay, p50/p95 completion time, tool latency, concurrent task throughput, memory retrieval speed at scale and browser responsiveness under sustained streaming remain **U**.

A useful performance dashboard should break a task into queue wait, routing/planning, model time, tool execution, verification/retry, approval wait and publication time. Measure authenticated real-stack traffic separately from human waiting time and paid-agent execution.

## 10. Cursor, Claude Code and Antigravity comparison

The master guide's broad “other coding assistants are single agents” framing is outdated. Claude Code documents subagents/agent teams, skills, hooks and MCP. Antigravity documents multiple agents, skills/MCP, browser interaction and reviewable artifacts. Cursor documents integrated coding tools, MCP and permission/run modes. [Claude Code extensions](https://code.claude.com/docs/en/features-overview), [Antigravity overview](https://antigravity.google/docs/overview), [Cursor run modes](https://cursor.com/docs/agent/security/run-modes).

| Dimension | Gridiron today | What is needed to compete credibly |
|---|---|---|
| Inspectable orchestration and governance | Strong architectural opportunity: own graphs, contracts, approvals, memory and audit records | End-to-end enforcement, reliable evidence, ownership and durable workers |
| Coding UX | Developer operations console with tasks, diffs, chat and terminals | Integrated editor, file/symbol navigation, contextual diagnostics and hunk review |
| Skills/extensions | Role prompts and direct tools | Native skill bundles, discovery/on-demand loading and optional MCP client ecosystem |
| Browser/artifacts | Tools and screenshot output exist | Safe browser execution, visual acceptance tests, trace/video/network evidence and integrated preview |
| Recovery | Checkpoints/resume/retries exist in code | Production worker initialization, stable IDs, replay safety and demonstrated crash recovery |
| Verification | Strong intent and many deterministic controls | No unavailable-gate false passes; held-out real repository acceptance tests |
| Learning | Memory/curation/prompt versions | Measurable improvement and safe project separation |
| Security/trust | Auth, vault and bash sandbox are real | Uniform execution isolation, canonical protected paths and complete network/resource authorization |
| Performance/cost | Several useful optimization mechanisms | Measured correctness, task latency and cost compared under matched workloads |

Claude Code checkpointing is documented with explicit limitations, including shell/external side effects; your recovery claims should similarly say what state is actually restored. [Claude Code checkpointing](https://code.claude.com/docs/en/checkpointing).

Antigravity's documented reviewable plans, diffs and browser artifacts illustrate the product-quality target. [Antigravity artifacts](https://antigravity.google/docs/artifacts).

**A credible reason to choose Gridiron eventually:** controlled internal engineering workflows, inspectable custom policy, team-level approvals, task-specific contracts and your own auditable memory. **A credible reason not to replace established tools yet:** current boundary defects, incomplete clean deployment, failing accepted routes, weaker session/editor experience and unproven live quality.

Do not claim it “beats” those products based on 85 agents or thousands of tests. Prove a focused advantage on your use case.

## 11. Advanced additions in a sensible order

### First: reliability and trust

Uniform job sandboxing; server-resolved workspaces; protected-target checks; resource/project authorization; normalized agent APIs; stable DAG IDs; production worker persistence; mandatory risk gates; atomic idempotency/budget reservations; production capability/readiness checks.

### Next: smarter work selection

Use task complexity **and risk**, repository facts, historical verified success and tool availability to choose a specialist/model. Route auth, permissions, financial/business-critical logic, migrations and infrastructure to a stronger reviewed workflow even when a change appears small.

Use structured plans with acceptance criteria and evidence requirements. Expand context only when missing evidence requires it. Give reviewers the actual diff and verifier output, rather than the author's optimistic summary.

### Then: product parity

- Persistent, authorized conversation/workspace history with resume and navigation recovery.
- Integrated editor and click-to-open file/symbol references.
- Hunk-level accept/reject and explicit patch provenance.
- LSP diagnostics/definitions/references and incremental repository indexing.
- Secure browser preview with screenshots, traces, console/network checks and visual regression.
- Command palette and keyboard flows; clear cost, approval, unavailable-tool and recovery states.
- On-demand skill loading and optional authorized connectors.
- Signed incoming CI/issue events and durable outgoing notifications.

### Finally: measured advanced autonomy

Canary prompt/skill improvements; verified memory promotion; cost-aware failure escalation; sandboxed reusable tool synthesis; isolated multi-agent branches with an integration coordinator; benchmark-based routing; failure replay; policy/event hooks; provenance across every model/tool/artifact step.

More agents should be added only when they improve a verified task class. Consolidating redundant wrappers and contracts can make the system both cheaper and easier to maintain.

## 12. Repair sequence and expected reassessment

The numbers below are **conditional target ranges**, not guaranteed score gains. Reassessment must verify acceptance conditions; fixing a listed line without proving the behavior is insufficient.

| Stage | Work | Evidence required | Plausible readiness after success |
|---|---|---|---|
| 1. Close release blockers | A01–A11, plus clean image handling and new Bhaskar mitigation validation | Adversarial workspace/network tests; no secret canaries outside intended boundaries; clearly defined trusted-team/tenant policy | **65–70/100**, still a restricted pilot |
| 2. Make clean deployment and lifecycle reliable | A12–A24, A29–A31, A39–A40 | Fresh compose installation; session revocation/privacy checks; one complete task and approvals; RQ restart/resume; no duplicates; enforced budget behavior; successful restore drill | **75–80/100**, controlled internal production candidate |
| 3. Prove task quality and complete user flows | A25–A28, A32–A38, A41–A44 | Real-stack browser journeys; representative held-out agent tasks; honest unavailable/unknown scores; sustained authenticated load | **85–90/100**, subject to deployment-specific acceptance |
| 4. Mature team/customer operation | Scoped ownership/memory/secrets, reliable connectors, skill framework, canary improvements, incident/DR drills and external security review | Two-tenant adversarial tests, operational SLOs, repeatable rollbacks and independently reviewed evidence | **90–95/100** within the tested use case |

### Exact first work items

1. Keep executable repository/model-generated code out of the control-plane host.
2. Restrict workspace creation/mounting to authorized registered repositories.
3. Fix protected-file checks through symlinks and browser all-request network policy.
4. Keep secrets out of Docker contexts/images.
5. Fix /run-sync argument adaptation and normalize research/DevOps results.
6. Initialize durable savers in real RQ jobs; prohibit silent production fallback.
7. Fix step-ID/dependency handling and isolate parallel edits.
8. Fix frontend backend routing and fresh volume ownership; provision a safe execution service.
9. Make required gates fail closed and correct no-evidence benchmark scores.
10. Run disposable E2E, restart, authorization, budget-edge and restore acceptance checks before opening production access.

### Production acceptance checklist

- [ ] New clean deployment works from documented instructions with fresh volumes.
- [ ] No credentials appear in image/context/log/telemetry canary checks.
- [ ] Every executable path and child process respects job filesystem/network boundaries.
- [ ] Unauthorized workspace roots and protected-target aliases are denied.
- [ ] Every accepted agent entry point returns a normalized result and correct state.
- [ ] PM → plan approval → code → tests → review → final approval → output works across the actual API/worker processes.
- [ ] Worker/API restart resumes from durable state without duplicate writes or publication.
- [ ] Rejected/edited plan steps retain valid dependency and DB step identity.
- [ ] Required verification unavailable/failure states block completion.
- [ ] Auth/session revocation and project/resource isolation match the promised sharing model.
- [ ] Confidential memory and secrets never cross unauthorized project boundaries.
- [ ] Budget limits cover in-flight concurrency and defined service outages.
- [ ] Chat history, reconnect, confirmations, pagination and task priority behave correctly.
- [ ] Backups restore application data and required keys/artifacts within documented RPO/RTO.
- [ ] Representative held-out task success, false-success rate, cost and p95 latency meet agreed thresholds.

## 13. Documentation corrections

What_is/PROJECT_MASTER_GUIDE.md is useful, but it is not a reliable current production certificate.

| Guide claim | Current audited qualification |
|---|---|
| 214 operational tools | 213 manifest entries; additional real runtime names are outside that manifest |
| 62 migrations / head 062 | Alembic reports single head 063 |
| 128 paths / 143 operations | Generated schema has 131 paths / 146 operations |
| All specialist agents work through the available APIs | Registration is verified; accepted synchronous and tuple-result paths have defects |
| Universal specialist quality reviews and learning | Disabled in default economy and partly in balanced |
| Project-scoped memory throughout | Versioned lessons and global LessonStore are not fully scoped |
| Per-subtask isolated worktrees | The manager can fan out in one shared worktree; Git commit lock does not isolate writes/tests |
| Durable worker checkpoints | RQ entry point never initializes PostgreSQL savers |
| Hardened Bhaskar subprocess | Original implementation was bypassable; a separate concurrent commit adds Docker isolation, requiring production validation |
| Effective production readiness near 96% | Checklist arithmetic does not establish production readiness; the guide also mixes 452/13 and older 450/15 totals |
| Competitors are mostly single-agent assistants | Current documented products expose multi-agent and extension capabilities |
| Thousands of passing tests prove all production behavior | Counts mix unit/mock/static and opt-in live tests; full current production suite was not executed in this audit |

The old guide's 452 YES / (519 minus 50 SKIP) arithmetic is about **96.4% checklist satisfaction**, while its final answer cites an older 450/469 figure of about 95.9%. Neither is a calibrated measure of release safety.

Use machine-generated inventories and a dated evidence ledger that distinguishes implemented, enabled, deployed, tested and independently verified. Keep the code-level strengths; correct the unsupported marketing conclusions.

## 14. Coverage and limits

Important reviewed areas include:

- Main settings/lifespan, API registration, authentication/RBAC/revocation, password flow, privacy and idempotency.
- Agent graph, manager, PM/planning paths, specialized runner dispatch, registry/capabilities, model/cost routing, verification and policy.
- Tool manifests/discovery, filesystem operations, host Python/Bhaskar, bash sandbox, browser/fetch/search, direct integrations and MCP.
- DAG ordering/edits, concurrency/file locks/shared worktrees, queue entry points, checkpoints/resume/orphan recovery and events.
- Memory store/hooks/global lessons/versioned memory, prompt changes, benchmark/regression machinery and spending ledger.
- Task/chat/stream/terminal/repository/approval/fleet frontend flows, API client, error handling, bundles and accessibility controls.
- Dockerfiles, development/production compose, CI/load/browser test wiring, launcher, backups/restore and operations documentation.

This is a comprehensive risk-oriented source audit, **not a line-by-line proof of every file, a penetration test against deployed infrastructure, or live certification of all external tools**. Ancillary historical reports and vendored comparison repositories were not all re-audited.

Unknowns remain: real provider quality/access, actual external connector availability, production containers and secrets management, live PostgreSQL/Redis behavior, concurrent restart recovery, current dependency vulnerability results from live advisory databases, sustained task performance and deployment-specific network policy. The user prohibited provider use, and this audit did not install infrastructure or mutate existing services to resolve those unknowns.

## 15. Agent inventory appendix

The table below records contracts and captured tool wiring. “Captured” means a signature-aware wrapper was invoked with the graph mocked to inspect supplied tools/handlers; it does **not** mean a real LLM completed the role's task. Contract/runtime differences can be phase-specific. Missing manifest metadata does not mean the handler is missing.


| Agent | Contract tool count | Captured runtime tool count | Runtime tools lacking manifest metadata | Configured tier |
|---|---:|---:|---:|---|
| accessibility_agent | 16 | 21 | 1 | sonnet |
| agent_advisor | 8 | 8 | 3 | sonnet |
| agent_debugger | 14 | 8 | 3 | sonnet |
| agent_performance_reviewer | 15 | 9 | 2 | sonnet |
| agent_roster_doc_agent | 9 | 21 | 1 | sonnet |
| agentic_ai_architect | 19 | 23 | 1 | sonnet |
| ai_engineer | 23 | 23 | 0 | sonnet |
| api_designer_agent | 19 | 22 | 1 | sonnet |
| api_docs_agent | 24 | 24 | 0 | sonnet |
| architect | 19 | Different entry point | Not captured | opus |
| architecture_doc_agent | 18 | 27 | 0 | sonnet |
| architecture_reviewer | 27 | 28 | 2 | opus |
| backend_dev | 25 | 24 | 0 | sonnet |
| barot_agent | 0 | Different entry point | Not captured | sonnet |
| bug_fix | 23 | 28 | 0 | sonnet |
| business_analyst | 19 | 19 | 0 | sonnet |
| changelog_agent | 14 | 21 | 1 | sonnet |
| chat_agent | 190 | Different entry point | Not captured | sonnet |
| cicd_agent | 22 | 22 | 0 | sonnet |
| cleanup_agent | 25 | 25 | 1 | sonnet |
| code_explainer_agent | 16 | 22 | 1 | sonnet |
| code_quality_agent | 18 | 22 | 1 | sonnet |
| coder | 24 | 24 | 0 | sonnet |
| compliance_agent | 16 | 20 | 1 | sonnet |
| cost_estimator_agent | 16 | 22 | 1 | sonnet |
| data_pipeline_agent | 18 | 22 | 1 | sonnet |
| database_architect | 14 | 20 | 1 | sonnet |
| debugger_agent | 24 | 23 | 1 | sonnet |
| decomposer | 19 | Different entry point | Not captured | opus |
| dependency_agent | 23 | 23 | 2 | sonnet |
| dependency_security_agent | 21 | 23 | 1 | sonnet |
| deployment_guide_doc_agent | 9 | 21 | 1 | sonnet |
| devex_agent | 18 | 22 | 1 | sonnet |
| devops | 20 | 20 | 0 | sonnet |
| docker_agent | 28 | 27 | 0 | sonnet |
| docs | 20 | 20 | 0 | sonnet |
| env_checker_agent | 18 | 22 | 1 | haiku |
| evaluation_agent | 13 | 21 | 1 | sonnet |
| executive | 0 | Different entry point | Not captured | opus |
| feature_flag_agent | 18 | 22 | 1 | sonnet |
| frontend_dev | 25 | 24 | 0 | sonnet |
| incident_responder_agent | 21 | 22 | 1 | sonnet |
| infra_agent | 19 | 23 | 1 | sonnet |
| knowledge_curator | 13 | 6 | 4 | sonnet |
| load_test_agent | 19 | 23 | 1 | sonnet |
| localization_agent | 18 | 22 | 1 | sonnet |
| manager | 0 | Different entry point | Not captured | opus |
| mcp_developer_agent | 20 | 24 | 1 | sonnet |
| migration_agent | 23 | 23 | 0 | sonnet |
| migration_guide_doc_agent | 9 | 21 | 1 | sonnet |
| mobile_dev | 23 | 23 | 0 | sonnet |
| monitoring_agent | 25 | 25 | 0 | sonnet |
| onboarding_agent | 19 | 23 | 1 | sonnet |
| pair_programmer_agent | 18 | 22 | 1 | sonnet |
| performance_reviewer | 23 | 23 | 0 | sonnet |
| planner | 20 | 20 | 1 | opus |
| pm | 19 | Different entry point | Not captured | sonnet |
| prompt_engineer_agent | 17 | 22 | 1 | sonnet |
| qa | 20 | 20 | 0 | sonnet |
| quality_auditor | 18 | 12 | 1 | sonnet |
| rag_engineer_agent | 15 | 21 | 1 | opus |
| readme_agent | 23 | 23 | 0 | sonnet |
| refactor_agent | 31 | 32 | 0 | sonnet |
| release_notes_agent | 15 | 21 | 1 | sonnet |
| research | 7 | 9 | 0 | opus |
| reviewer | 19 | 19 | 0 | sonnet |
| roadmap_agent | 15 | 20 | 1 | sonnet |
| rollback_agent | 22 | 22 | 1 | sonnet |
| runbook_generator_agent | 20 | 24 | 1 | sonnet |
| schema_agent | 22 | 22 | 0 | sonnet |
| security_architect | 16 | 19 | 1 | opus |
| security_reviewer | 24 | 24 | 0 | sonnet |
| slo_agent | 18 | 22 | 1 | sonnet |
| spike_agent | 20 | 24 | 1 | sonnet |
| sprint_planner | 20 | 20 | 0 | sonnet |
| sql_agent | 25 | 25 | 0 | sonnet |
| style_reviewer | 22 | 22 | 0 | sonnet |
| tech_advisor_agent | 18 | 23 | 2 | sonnet |
| tech_debt_agent | 23 | 23 | 0 | sonnet |
| test_coverage_agent | 19 | 23 | 1 | sonnet |
| test_writer_agent | 19 | 23 | 1 | sonnet |
| tool_catalog_doc_agent | 9 | 21 | 1 | sonnet |
| user_story_generator | 12 | 20 | 1 | sonnet |
| ux_design_agent | 16 | 21 | 1 | sonnet |
| version_manager_agent | 20 | 24 | 1 | sonnet |

The configured tier is subject to cost-profile caps. Zero missing handlers were found across captured regular-wrapper tools. This appendix reports static wiring and does not waive A15/A16 entry-point defects or the live evaluation requirement.

### Audit handoff

Start with the release blockers and use the acceptance conditions in section 4 as repair tickets. Re-run the production checklist after fixes; do not replace the verdict with a count of closed Markdown items.

The observed concurrent revision 162f0658 changed Bhaskar isolation, configuration, test setup, a new Docker test file, the environment example and deployment documentation. Later revisions b830b77f, cc4f1e4b and f7006e9d changed scan budgets, enhancement APPLY isolation and Barot delegation. Further scratchpad/test changes were also in progress at handoff. Those changes were authored outside this audit and preserved. Runtime evidence for the old subprocess is historical; the new Docker mode requires its own deployment validation. The source audit does not certify later moving revisions or attribute those improvements to this audit.



after implement this :
Fixing the reported issues and passing their acceptance checks could raise readiness from 53/100 to roughly 85–90/100. Completing the additional maturity roadmap targets 90–95/100.
Progress	Target readiness
Fix security and isolation blockers	65–70/100
Fix deployment, agent execution and recovery	75–80/100
Verify task quality and complete UI flows	85–90/100
Prove project isolation, reliable integrations, backups and operational maturity	90–95/100


These are estimated targets. The higher rating comes from demonstrating that the fixes work, including restart recovery and real task completion—not simply closing the issues in the file.