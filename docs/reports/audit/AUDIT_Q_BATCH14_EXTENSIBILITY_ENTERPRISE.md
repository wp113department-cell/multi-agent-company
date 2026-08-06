# Batch 14 — Extensibility, Enterprise Readiness, Company-Scale/Multi-Project, Workspace Isolation, Version Awareness, UX Intelligence, Accessibility

Covers §47, §48, §77, §94, §95, §98, §99, §100. Evidence-only, file:line cited.

---

## §47 Extensibility

| Checkpoint | Verdict | Evidence |
|---|---|---|
| New agent via role/tools/prompt/memory config only, no orchestration code change | **PARTIAL** | `capability_registry`/`agent_registry` population is genuinely automatic — a real runtime scan (`ensure_all_agents_registered`) imports every `app/agents/*.py` file at startup, so `AGENT_CONTRACT` + `_register()` + a matching role file is enough to appear in both registries with zero code changes. **But the one HTTP path that actually runs a worker agent on a task (`POST /api/specialized-agents/{name}/run`) requires a manual, hardcoded entry in `specialized_agents.py::_REGISTRY`** (a `name → (module, function)` dict) — no dynamic fallback exists; an unregistered name raises `ValueError`. |
| New agent auto-joins / becomes dispatchable | **NO** | Same finding — `FleetManager.select()` would pick a new agent up automatically for capability scoring, but its own `dispatch()` explicitly does not call the agent; the only real invocation path still requires the manual `_REGISTRY` edit. |

**§47 overall: PARTIAL, and specifically not what the question asks for.** Two of three "automatic" layers are real; the one that matters most (can this agent actually run) is not.

---

## §48 Enterprise Readiness

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Multiple users | **PARTIAL** | No normalized `User` table — credentials are a JSON array inside a single `system_settings` row, explicitly documented as a deliberate Phase-1 shortcut. Multiple distinct logins are possible, but the data model is a settings blob, not a users table. |
| Multiple projects/workspaces | **NO** | `repo_id` is the *only* isolation dimension found anywhere — no `Workspace`/`Organization`/`Tenant` concept exists at all. |
| Concurrent sessions | **PARTIAL — one real race fixed, one real gap remains** | A genuine cross-repo dispatch race (background task picking up whichever repo happens to be globally "active" at execution time, not the repo the task was created against) was found **and fixed** — confirmed by a real regression test (`test_repo_scoping_race_fix.py`) exercising two repos activated back-to-back. However, the underlying in-process singletons (agent registry, capability registry, `LessonStore`) from Batch 5 still mean two concurrent users on the same backend process share one mutable namespace — not corrupted across repos anymore, but not isolated per-user/session either. |
| Enterprise authentication (SSO/SAML/OAuth) | **NO** | Zero references anywhere; username/password → JWT only. |
| Audit logging | **PARTIAL** | Reference to Batch 11 finding (real, but 2000-entry in-memory query cap). |
| Role-based access | **PARTIAL** | Reference to Batch 6/11 finding (real RBAC, inconsistently applied to some routes). |
| Usage analytics | **NO** | Only fleet-wide, process-global, in-process (reset-on-restart) metrics exist. No per-user or per-workspace usage dashboard of any kind. |

**§48 overall: NO/PARTIAL.** This system is currently architected for **single-installation, small-team use** — every "enterprise" checkpoint that implies multi-tenancy (workspaces, per-org analytics, SSO) is absent, while the security fundamentals that would need to exist *underneath* multi-tenancy (RBAC, audit logging, credential encryption) are real, if imperfect. This is an honest, coherent state — the security groundwork is there; the multi-tenant structure on top of it is not.

---

## §77 / §94 Company-Scale Readiness / Multi-Project Management

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Agent lifecycle (hire/retire/replace/promote) | **NO, with one real adjacent exception** | `AgentState` enum has only `IDLE/SLEEP/RUNNING/ERROR` — no `DISABLED`/`DEPRECATED`/`RETIRED`. **Real exception**: agent *prompts* (not the agent entity itself) have a genuine version lifecycle — `PromptVersion` rows with `draft→in_review→approved→deployed→superseded→rejected` status and lineage tracking. This doesn't retire an agent, but it's real, adjacent infrastructure. |
| Full cross-repo isolation | **PARTIAL** | `repo_id` scoping is real but **not universal**. Confirmed FK-scoped: `DevTask`, `Epic`, `MemoryEmbedding`, `VersionedLesson`, 3 score tables. Confirmed scoped only by a raw string `repo_path` (no DB-level collision protection): `IndexedFile`, `CallEdge`, `CodeEmbedding` (the last explicitly documented as predating the `Repo` model). Confirmed scoped only by `task_id`/`epic_id`, not `repo_id` directly: `Artifact`, `Event`, `PendingApproval`, `EpicScratchpad`. Some tables are correctly global by design (`Policy`, `UserRole`, `Agent`, `SystemSetting`) — not a gap, just noted for completeness. |

**§77/§94 overall: PARTIAL.** The isolation story is more nuanced than a single "repo_id everywhere" claim would suggest — some tables use a real FK, some use a matching string with no enforced uniqueness, and credentials (see §95) are global by explicit design.

---

## §95 Workspace Isolation

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Credentials scoped per-repo/project | **NO — confirmed global by explicit design** | `credential_vault.py`'s own module docstring states plainly: "Global-scoped (this project has no 'project' entity...)". `ProjectCredentials`, despite its name, is backed by a single global settings key — one set of API keys/tokens for the entire installation, not per-repo. This is a real, named limitation in the code's own words, not a bug this audit discovered independently. |
| Agents use the correct repo_path consistently | **PARTIAL** | For the two dispatch entry points that matter (`run_specialized_agent`/`_sync`), an explicit `repo_path` correctly resolves from the task's own `repo_id` first — the race identified in §48 was fixed here. A global fallback (`settings.target_repo_path`/`get_active_repo_path()`) still exists and is reachable for repo-less tasks or any direct function call that supplies neither `repo_path` nor a resolvable `task_id` — a narrower, legitimate fallback rather than the systemic race that was fixed. |

**§95 overall: PARTIAL.** Task/repo isolation for the primary dispatch path is genuinely solid (with a real, tested fix for a real prior race). Credentials being explicitly, deliberately global is the one clear, named gap — worth flagging precisely because the code itself is honest about it rather than pretending otherwise.

---

## §98 Version Awareness

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Git tags / semver | **PARTIAL** | Real tools exist (`git_tag`, `semver_bump` — genuinely bump `pyproject.toml`/`package.json`/`VERSION` in place) — but they're wired **only into the interactive chat agent's tool set**, not into any of the 84 specialized worker agents. Usable, but only through one surface. |
| Migration state reasoning | **YES** | Real AST-based `list_migrations` tool parses every migration file (revision id, down_revision, docstring) without executing it — wired into a real, registered agent (`migration_guide_doc_agent`, though note this agent's *role file* is one of the 4 confirmed-missing from Batch 10, so it would crash if invoked as-is). |

**§98 overall: PARTIAL.**

---

## §99 User Experience Intelligence

| Checkpoint | Verdict | Evidence |
|---|---|---|
| Detect confusion / beginner vs expert mode | **NO** | Zero references anywhere — consistent with Batch 12's broader finding that intent/state classification is largely absent. |
| Generate diagrams | **PARTIAL — real tool, template-only output** | A real `generate_diagram` tool exists, wired into chat — but it's a fixed-template stub: for a requested diagram kind, it returns one hardcoded skeleton with the user's description inserted only as a comment, plus a literal "customize the template above" note. It does not analyze real code/data to populate diagram content — content-filling is deferred back to the calling LLM's next turn. |
| Summarize long outputs (distinct from input condensation) | **NO** | Confirmed distinct from the (real, strong) input-context condensation found in Batch 13. For a single long tool *result*, only hard character/line truncation exists — no LLM-generated output summary. |

**§99 overall: NO/PARTIAL.** The diagram tool is a good example of a pattern seen elsewhere in this audit (Batch 10's git/PR generation): real scaffolding, generative substance deferred to the calling LLM.

---

## §100 Accessibility

| Checkpoint | Verdict | Evidence |
|---|---|---|
| ARIA/semantic HTML | **NO — minimal** | Only 2 of 48 checked `.tsx` files have any `aria-*` attribute at all. |
| a11y linting | **NO** | No `eslint-plugin-jsx-a11y` in the ESLint config or `package.json`. |
| Internationalization | **NO** | No i18n library present. |

**§100 overall: NO.** This is a straightforward, unambiguous gap — the frontend has essentially no accessibility tooling or markup investment.

---

## Summary — Batch 14 (16 checkpoints across 8 sections)

- **YES:** 1
- **PARTIAL:** 10
- **NO:** 5

**Findings worth flagging above the rest:**
1. **The extensibility story has a real, specific gap**: two of three registration layers are genuinely automatic (a real architectural strength), but the one that determines whether a new agent can actually be *run* still requires a manual dispatch-table edit — worth fixing given how close the system already is to the "no orchestration code change" goal.
2. **A real, previously-unknown cross-repo dispatch race was found already fixed in the codebase**, with a purpose-built regression test — this is a positive signal about the team's own rigor, not just a finding.
3. **Credential scoping is deliberately, self-documented global** — not a hidden gap, but worth surfacing clearly for anyone assuming per-project credential isolation exists.
4. **Accessibility is the clearest, least nuanced gap in this batch** — no hedging needed, it's simply not invested in yet.

**Production Enhancement Plan (highest-value item):** Replace `specialized_agents.py`'s hardcoded `_REGISTRY` dict with the same dynamic-scan pattern already used successfully for `capability_registry`/`agent_registry` (`ensure_all_agents_registered`'s `Path.glob`+`importlib` approach) — this is proven, working code in the same file tree, just not applied to the one registry that gates actual execution.
