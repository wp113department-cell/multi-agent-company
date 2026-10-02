# AUDIT 03 — MASTER MEMORY AUDIT
## Gridiron AI Developer Department — the three engineering-memory systems

**Audit ID:** MEM-03 | **Report file:** `files/Qoder_audit report/03_MEMORY_AUDIT.md`
**JSON sidecar:** `files/Qoder_audit report/json/AUDIT_03_MEMORY.json`
**Run date:** 2026-10-02
**Auditor:** Qoder (read-only audit — no code was modified by this audit)
**Baseline:** `c927c44bf410e188287f32b2cf54e0529c642025` ("Production audits 09 and 11", 2026-10-02 11:11 +0530). All evidence gathered against this checkout.
**Baseline note / working-tree drift:** during evidence collection, two tracked files appeared modified by a *different, concurrent process* (another audit/repair session — its comments say "Production audit 12"): `backend/app/api/epics.py` and `backend/app/api/fleet_dashboard.py` (route-shadowing fixes; also untracked `What_is/AUDIT_REPORT/evidence/*`). Neither file is part of the memory layer; every citation below was verified against the unmodified memory-layer files at `c927c44b`. This audit modified no code.
**Standards followed:** `files/Audit/00b_AUDIT_STANDARDS.md` (evidence schema + JSON sidecar + no-padding rule)
**Method:** full reads of `app/memory/store.py` (2216 lines), `app/fleet/versioned_memory.py` (799), `app/memory/hooks.py`, `app/api/memory.py`, `LessonStore` (base_graph.py:432-680), plus targeted reads of `main.py` loops, `retention.py`, migrations, `memory_write.py`, `config.py`; grep-based caller sweeps; every finding tied to file:line.

---

## 0. GROUND TRUTH — the memory layer as actually built

`PROJECT.md` does not exist in this repository (Audit 01 §0); "per PROJECT.md" claims below were re-derived from code.

**Three memory systems (as the brief defines them) — all three exist and are wired:**

| # | System | Storage | Write path | Read path | Lifecycle |
|---|---|---|---|---|---|
| 1 | `LessonStore` | in-process `list[Lesson]`, capacity `lesson_store_capacity`=1000 | `_extract_and_store_lesson` → `add()` (best-effort DB copy via `_persist_lesson_async`; `refresh_from_db` pulls other processes' rows back in) | `memory_hook_node` → `format_for_injection` (keyword/Jaccard, top-3) | Jaccard dedup at add (0.8, config.py:768-775); LLM compression at capacity (model_router, max_tokens=400, 10s isolated client, outside lock — base_graph.py:486-597); FIFO fallback |
| 2 | `memory_embeddings` | Postgres + pgvector, 1536-dim, HNSW (migration `004_phase6_tables.py:88-91`) | 8 `embed_*` writers (task/failure/architecture/learning/procedure/preference/bug/prompt_change) | `query_memory_context` (7 sub-queries) → `format_full_memory_context`; `query_similar_tasks` in pipeline prefetch; `/api/memory/search`, `/patterns`, `/analytics` | near-dup reuse at 0.97 with `pg_advisory_xact_lock` (store.py:320-372); deterministic quality gate (reject/draft/publish); composite ranking (similarity .6/recency .15/reuse .1/importance .1/verified .05/usefulness .05); retention 180 d; consolidation opt-in (default OFF) |
| 3 | `versioned_lessons` | Postgres + pgvector, HNSW (migration `020_versioned_lessons_hnsw.py:27-28`) | `publish()` — call site `_extract_and_store_lesson` (base_graph.py:3212), gated on a real VOYAGE key (3207) | `/api/memory/lessons`; promoted lessons sync into `memory_embeddings` (learning category, versioned_memory.py:281-309, 714) | DRAFT → PUBLISHED → SUPERSEDED / MERGED_INTO → ARCHIVED, human-gated `promote()` (knowledge_curator APPLY after dashboard approval); `rollback()` wired at api/memory.py:200-240; `archive_expired()` reads `lesson_retention_days` (default 180, config.py:1703-1706) |

**Fourth (file-based) store — not in the brief's three, but real and reachable:** the `memory_write` chat tool writes per-repo JSON files into the source tree — `backend/app/memory/<md5-slug>_store.json` (`app/tools/agents/memory_write.py:123-131`); **484 such files exist**, gitignored via `backend/.gitignore:13`. See MEM-03-004/§7.

**Verified counts / key mechanisms:**
- All 8 `embed_*` categories are written at their correct sites (task: outcome=completed/blocked + default `category='task'`, models.py:754-756; failure store.py:1117-1118; architecture 907-908; learning 1270-1271; procedure 1492-1493; preference 1668-1669; bug 1871-1872; prompt_change 1991-1992).
- Repo scoping filter `(repo_id IS NULL OR repo_id = :repo_id)` present in **all 9 SQL sites** (dedup 352 + all 8 queries: 618, 1017, 1176, 1372, 1559, 1766, 2096, 2172).
- Every `embed_*`/`query_*`/lifecycle function has a real (non-test) caller — **no orphaned memory functions found** (sweep in §4). `embed_prompt_change`'s caller is `embed_prompt_change_sync` (prompt_registry.py:354,370); `reembed_zero_vector_rows`' only scheduled caller is main.py:280.
- `MemoryEmbedding.created_at` is present in the ORM model with `server_default=func.now()` (models.py:763-765) — the historical missing-created_at crash is still fixed.
- Retention loops all leader-gated in `lifespan` (main.py:1671, 1678-1684, 1685-1691, 1692-1698).
- Merge/consolidation LLM calls are bounded and cheap: `model_router` default `claude-haiku-4-5-20251001` (config.py:35-38), `max_tokens` 512/768 (versioned_memory.py:577, 452), ≤3 merge calls/cycle cap (`memory_embeddings_consolidation_max_groups_per_cycle`=3), ≤20 merges/promote.

---

## 1. Executive summary

All three systems are real, structurally sound, and correctly wired — this layer's engineering is genuinely strong: TOCTOU-safe dedup (`pg_advisory_xact_lock`), two-stage HNSW retrieval, write-path quality gate that never hides data it drafted, a human-gated lesson lifecycle with real rollback and archival, leader-elected maintenance loops, and a cross-process lesson refresh. Four medium/low-severity correctness defects and two low hygiene issues were found, all with small fixes: (1) `query_similar_tasks` — the single most-used memory query — has **no category filter**, so "similar past tasks" is actually "similar anything" (failures, preferences, bugs render as tasks too, duplicated across sections of every agent's injected memory block); (2) the zero-vector repair pass is **unreachable whenever `MEMORY_CONSOLIDATION_ENABLED=false`** because a `continue` skips it; (3) `query_memory_context` re-embeds the same description **7 times** across 7 sequential sub-queries on every agent run; (4) zero-vector rows are still inserted when no Voyage key is configured (repair no-ops, 50-row/day cap), which the plain reading of base_graph.py:3199-3204 contradicts. The brief's described merge lifecycle ("V_merged published" at publish time) is **stale** — the current, human-gated design (#89/#406/#464) is correct and verified; a related per-topic-lock vs fleet-wide-similarity race is noted. One cross-cutting infrastructure discovery (leader-election pool undersized: 16 connections vs 20 loop tasks, fatal `TimeoutError` for the tail tasks) is flagged for Audit 04/06 rather than scored here.

---

## 2. Layer score

**Score: 80 / 100**

Deductions: three Medium (category-mixing in the primary query, MEM-03-001; repair loop unreachable under a supported config, MEM-03-002; 7× duplicate embeddings + serialized sub-queries per agent run, MEM-03-003) and three Low (zero-vector write accumulation, MEM-03-004; API category filter omissions, MEM-03-005; publish merge race, MEM-03-006). No Critical/High. Everything else on the brief's Phase 1/2/3 checklists verified clean with evidence (§4-§6).

---

## 3. Findings (evidence schema)

### MEM-03-001 — [MEDIUM] `query_similar_tasks` has no category/outcome filter: "similar past tasks" returns rows from all 8 categories

- id: MEM-03-001
- severity: Medium
- file: `backend/app/memory/store.py`
- location: `query_similar_tasks` → candidates CTE (the only `query_*` without a category/outcome predicate)
- line: 609-621 (WHERE = embedding NOT NULL + `vector_norm(embedding) > 0` + `archived = false` + repo filter only); contrast siblings: 1013 (`outcome='architecture'`), 1172 (`outcome='failure'`), 1368 (`category='learning'`), 1555 (`category='procedure'`), 1762 (`category='preference'`), 2092 (`category='bug'`), 2168 (`category='prompt_change'`)
- finding: Task rows are stored with `outcome='completed'|'blocked'` and the model-default `category='task'` (models.py:754-756), while every other write site stores a distinct outcome/category. `query_similar_tasks` filters on **neither**, so a failure/preference/bug/prompt-change row is returned as a "similar past task". Because `query_memory_context` (684-696) also runs the 7 category-specific queries, the same non-task row can appear **twice** in one injected block — once under "Similar past tasks" (format_memory_context, 837-851) and once under its own section (format_full_memory_context, 757-834).
- evidence: `store.py:609-621` (no category predicate); write sites cited in §0; `models.py:754-756` (`category` default `'task'`); the "tasks" section is consumed by (a) `memory_hook_node` on **every agent run** (base_graph.py:1652-1670), (b) the pipeline prefetch feeding PM/Architect/Decomposer (pipeline/graph.py:245-258 → state.py:24 → pm.py:130-131,156 / architect.py:146,160 / decomposer.py:153,159), (c) `GET /api/memory/search` (api/memory.py:157-159). No test pins the expected behavior: `test_b4_memory_categories.py:248-294` only exercises the archived filter; `test_context_query_returns_all_seven_sections_and_formats_them` (143-188) seeds all categories with the same text and only asserts non-emptiness.
- production_impact: The top-3 "similar past tasks" slots injected into every agent's prompt can be entirely non-task rows, mislabeled by their outcome string; duplicated rows waste the 3000-token injection budget (memory_injection_token_budget, config.py:673-680) and dilute retrieval precision. Silent — nothing logs the mixing.
- confidence: High (SQL verified; absence of filter is unambiguous)
- recommendation: Add `AND category = 'task'` (or `outcome IN ('completed','blocked')`) to the candidates CTE; add a real-DB test seeding all 8 categories and asserting the tasks section contains only task rows.
- effort: Small

### MEM-03-002 — [MEDIUM] Zero-vector repair is unreachable when `MEMORY_CONSOLIDATION_ENABLED=false` — a `continue` skips it

- id: MEM-03-002
- severity: Medium
- file: `backend/app/main.py`
- location: `_versioned_lesson_consolidation_loop` — consolidation branch vs the "Also repair" block
- line: 256-284 (`continue` at 259-260; repair block at 273-284)
- finding: The loop body is `sleep → try { if not memory_consolidation_enabled: continue; consolidate() } → also reembed_zero_vector_rows()`. When an operator sets `MEMORY_CONSOLIDATION_ENABLED=false` (a documented, supported switch — config.py:1715-1717, loop docstring 250-253), the `continue` restarts the loop and **skips the zero-vector repair block entirely**. `reembed_zero_vector_rows` has no other scheduled caller in production (grep: main.py:277-280 is the only call site; store.py:425 def; tests only).
- evidence: main.py:259-260 vs 273-284; the comment at 273-274 ("Also repair memory rows stored with a zero embedding…") documents the repair as an independent concern, but control flow couples it to the consolidation switch. `reembed_zero_vector_rows` no-ops without a key (store.py:432-433) and repairs ≤50 rows/cycle (limit default at 426).
- production_impact: After a Voyage outage (or any backlog of dead rows), an operator who disables consolidation — precisely the cost-conscious configuration — silently loses the only automatic recovery path for rows that were deliberately written "stored… but dead" (test_b4_memory_store.py:260-285). Dead rows stay unsearchable until (a) a key appears and repair runs, or (b) 180-day retention archives them.
- confidence: High (deterministic control flow)
- recommendation: Move the repair block above the `continue` (own try/except, own cadence), or restructure as two independent guarded sections; give repair its own switch if the coupling is unwanted by design.
- effort: Small

### MEM-03-003 — [MEDIUM] `query_memory_context` re-embeds the same text 7× and runs 7 sub-queries serially — on every agent run's critical path

- id: MEM-03-003
- severity: Medium
- file: `backend/app/memory/store.py` (+ `backend/app/agents/base_graph.py` caller)
- location: `query_memory_context` / `query_memory_context_sync` / `memory_hook_node`
- line: store.py:684-696 (7 sequential awaits); each sub-query independently calls `_embed(description)` (594-598, 1159-1161, 1355-1357, 1542-1544, 1749-1751, 2081-2083, 2157-2159); sync bridge store.py:708-754 (throwaway engine at 733, own `asyncio.run` at 743); caller base_graph.py:1652-1654
- finding: For one identical `description`, the 7 sub-queries each perform their own Voyage embedding round-trip (via `_embed`, which also runs the sync client in a thread — correct per-call but repeated 7×) and are awaited strictly serially, followed by up to 7 `record_memory_access` updates. The sync bridge additionally creates a throwaway DB engine + a fresh event loop per agent run. With `VOYAGE_API_KEY` set (the production-config case), this is 7 duplicate HTTP calls for one text, per agent run start; with no key it short-circuits cheaply (zero-vector, 597-598).
- evidence: cited lines; callers: every agent run (memory_hook_node, base_graph.py:1629-1678), so the cost multiplies by concurrent runs (`max_concurrent_agent_runs`=20, config.py:804-805); the pipeline prefetch (graph.py:257) calls only `query_similar_tasks` (single embed) — the 7× cost is the agent-run path.
- production_impact: ~1-3 s of serialized provider latency added before every agent's inference when the key is configured (plus 7 DB round-trips); 20 concurrent runs emit 140 embedding requests for 20 unique texts. Invisible in metrics except the aggregate `memory_retrieval` phase timing.
- confidence: High (code path); latency magnitude provider-dependent (Medium on exact seconds)
- recommendation: Embed once in `query_memory_context`, pass the vector (or a lazy embedder) into the sub-queries; consider `asyncio.gather` for the independent reads; optionally reuse a single engine for the sync bridge.
- effort: Medium

### MEM-03-004 — [LOW] Zero-vector rows are still inserted with no Voyage key (default config); repair is a no-op then and capped at 50 rows/day afterwards

- id: MEM-03-004
- severity: Low
- file: `backend/app/memory/store.py` (+ inaccurate claim in `base_graph.py` comment)
- location: write path `embed_task_outcome` (and siblings) vs `_embed` / `_find_near_duplicate` / `reembed_zero_vector_rows`
- line: store.py:394-395 (no key → zero vector), 320-321 (dedup silently skipped for zero vector), 513-557 (insert proceeds — **no zero-vector gate**), 425-462 (`limit: int = 50` at 426; `if not voyage_api_key: return 0` at 432-433); base_graph.py:3199-3204 (comment)
- finding: With `voyage_api_key` unset (the config default, config.py:41-43) and `memory_enabled=true` (default), every agent run still inserts task-outcome/failure/architecture rows with a zero embedding: dedup is skipped, the quality gate passes real content, and the insert is unconditional. Those rows are invisible to every query (`vector_norm(embedding) > 0`, 616-617) and can never self-heal — repair explicitly no-ops without a key. The base_graph.py:3199-3204 comment justifies skipping the versioned-lesson publish with "same 'meaningless without a key' logic app.memory.store already uses" — but store.py's zero-vector logic is **query-side only**; it does not skip these writes, so the claimed precedent is not what the code does.
- evidence: cited lines; `tests/test_b4_memory_store.py:260-285` proves "stored… but dead" is the *intended* behavior for a provider outage (write now, repair later) — the no-key case shares that path but has no recovery until a key is configured, then repairs ≤50 rows per 24 h cycle (main.py:280, once per `memory_consolidation_interval_hours`=24).
- production_impact: In any deployment without a Voyage key: `memory_embeddings` grows with permanently unusable rows (agent-name/quality analytics will count them; the composite ranking never sees them); if a key is added later, a large backlog clears at ≤50 rows/day. The misleading comment raises the risk that reviewers believe no such rows exist (this audit's brief itself leaned on that claim).
- confidence: High (behavior) / Medium (whether "preserve raw text for later embedding" was a deliberate product decision — no comment or test states it for the no-key case)
- recommendation: Gate the write on a real key (skip insert when `voyage_api_key` absent — mirroring the versioned-publish gate at base_graph.py:3207), or keep write-and-repair but say so explicitly in the `_embed` docstring and raise/uncouple the repair rate; fix the base_graph.py:3199-3204 wording.
- effort: Small

### MEM-03-005 — [LOW] `/api/memory/patterns?category=` omits the `prompt_change` category and silently ignores unknown values

- id: MEM-03-005
- severity: Low
- file: `backend/app/api/memory.py`
- location: `_VALID_CATEGORIES` + `get_memory_patterns` filter
- line: 25-38 (set has 7 values — no `prompt_change`); 60-63 (`if category and category in _VALID_CATEGORIES:` — otherwise returns everything, no 4xx)
- finding: `prompt_change` has been a real, written category since #405 (store.py:1991-1992; query at 2168; writer caller prompt_registry.py:354,370) but is absent from the endpoint's filter set and its own description string (memory.py:46). A request for it (or any typo like `?category=failures`) falls through the `in` check and returns the **unfiltered** aggregate/recent list instead of an error or a filtered result.
- evidence: cited lines; the set's own comment (30-34) shows it was maintained by hand once (procedure/preference/bug added) and missed the newer category.
- production_impact: A dashboard filtering by category can silently display an all-categories feed; consumers cannot distinguish "no data" from "filter ignored". Read-only surface — no data corruption.
- confidence: High
- recommendation: Single shared category constant (e.g. export the 8 values from store/models) used by both the API and writers; return 422 for unknown values.
- effort: Small

### MEM-03-006 — [LOW] `publish()` locks per topic but merges against all published lessons fleet-wide — concurrent cross-topic publishes can create duplicate version rows in one lineage

- id: MEM-03-006
- severity: Low
- file: `backend/app/fleet/versioned_memory.py`
- location: `_publish` (lock key vs similarity scope), `_insert`, `_most_recent_draft_for_lineage`
- line: 621 (`_lesson_lock(topic)`), 622 + 115-138 (`_find_most_similar_published` — global, `state='published'`, no topic filter), 642-650 (merged draft reuses `existing_row.lesson_id` with `version=existing_row.version + 1`), 141-172 (`_insert` — no uniqueness constraint), 218-244 (promote picks latest draft by version, no tiebreaker)
- finding: Two concurrent `publish()` calls on *different* topics take *different* advisory locks but each performs a fleet-wide similarity check. If both texts are ≥ `memory_merge_similarity_threshold` (0.85) against the *same* published lesson, both insert a merged draft with the same `lesson_id` and the same `version` number. `promote()` then selects one draft by `version DESC LIMIT 1` with no secondary ordering (tie → arbitrary pick); the other stays draft and could be promoted later, publishing a second same-lineage row without flipping the first (promote only flips `supersedes_id`).
- evidence: cited lines. The design docstrings claim serialization by topic (67-112) and the consolidation sweep has its own `__consolidation_sweep__` lock (684) — but `publish()` never takes it.
- production_impact: Duplicate draft/published versions within one lineage after concurrent similar lesson extraction (publish is called per agent run when a key is set, base_graph.py:3212). Data is not lost; history/version numbering becomes ambiguous and rollback can flip the "wrong" sibling. Narrow concurrency window, requires two ≥0.85-similar publishes against one lesson on different topics.
- confidence: Medium (mechanism verified in code; real-world frequency unproven)
- recommendation: Constrain the match to the same topic inside the lock, take a global publish/merge lock (reuse `__consolidation_sweep__`), or add a DB uniqueness constraint on `(lesson_id, version)` plus a tiebreaker in `_most_recent_draft_for_lineage`.
- effort: Small–Medium

---

## 4. Phase 1 checklist results (correctness)

| Check | Result | Evidence |
|---|---|---|
| No-key fallback degrades gracefully | YES for reads and the versioned system; writes still insert dead rows (MEM-03-004). Reads: all 7 queries + dedup short-circuit on zero vector (store.py:320, 597, 1160, 1356, 1543, 1750, 2082, 2158); LessonStore is key-free (keyword/Jaccard); versioned publish skipped without key (base_graph.py:3207-3214); no crash path found | cited lines |
| `versioned_memory.publish()` still gated on real VOYAGE key at its call site | YES — `if _get_settings().voyage_api_key:` then `publish(...)` at base_graph.py:3207-3214 | base_graph.py read |
| Similarity queries target the correct table/column | YES — `memory_embeddings` queries all use `embedding <=> CAST(:vec AS vector)` + `vector_norm>0` + `archived=false` (e.g. 618-620); `_find_most_similar_published` queries `versioned_lessons` `state='published'` (115-138). No cross-table querying found | store.py / versioned_memory.py reads |
| Merge-on-conflict lifecycle matches actual state transitions | VERIFIED against the **current human-gated design** (brief's description is stale): publish inserts/merges as `draft` (624-651, merged draft keeps lineage + `supersedes_id`); `promote()` flips `supersedes_id → superseded`, draft `→ published` (671-673), optional N-way sweep flips others `→ merged_into` (682-690), then syncs to `memory_embeddings` (714); `rollback()` flips published↔superseded (740-779); `archive_expired()` reads `lesson_retention_days` from settings (783-788, config.py:1703-1706) → `archived` (247-278). Matches the VersionedLesson lifecycle string; nothing auto-publishes | versioned_memory.py read + `test_b4_memory_categories.py:297-335` |
| Category correctness at every write site | YES for all 8 (see §0 cites). `?category=` filter: applies for its 7 known values (memory.py:60-63) but omits `prompt_change` and silently ignores unknown values (MEM-03-005) | store.py + memory.py reads |
| Retention/archival scheduled; `LESSON_RETENTION_DAYS` from config | YES — `_versioned_lesson_archive_loop` 24 h (main.py:224-243), leader-gated (1678-1684); call reads `settings.lesson_retention_days` (versioned_memory.py:783-788), env-var-bound (config.py:1703-1706); `memory_embeddings_retention_days` consumed by the generic retention service (retention.py:240-244) which is leader-gated (main.py:1671) | cited lines |
| Real callers for every memory function (zero-caller sweep) | **No orphans.** 8 `embed_*` all have producers (hooks.py for task/failure/architecture; record_learning; `_maybe_store_procedure` base_graph.py:4155; record_preference; known_issues_write; prompt_registry.py:354,370). `publish` ← base_graph.py:3212; `promote` ← knowledge_curator APPLY (memory_promote_lesson); `rollback` ← api/memory.py:221; `archive_expired` ← main.py:237-238; `consolidate_published_lessons` ← main.py:263-264; `reembed_zero_vector_rows` ← main.py:280. `query_failures`/etc. are reached via `query_memory_context` | grep sweep `app/` |
| `memory_context` really flows PM → Architect → Decomposer | YES — pipeline prefetch `query_similar_tasks`+`format_memory_context` (graph.py:245-258) → state field (state.py:24) → appended to the user message text in all three: `f"{memory_block}…"` pm.py:130-131,156; architect.py:146,160; decomposer.py:153,159. (Chat has its own `_memory_read_context`, chat_agent.py:4887-4889.) Caveat: content mix per MEM-03-001 | cited lines |
| `created_at` on the ORM model (historical crash) | Still fixed — models.py:763-765 | models.py read |
| HNSW indexes present in migration DDL | YES — `memory_embeddings_embedding_hnsw` (004_phase6_tables.py:88-91, `vector_cosine_ops`), `versioned_lessons_embedding_hnsw` (020_versioned_lessons_hnsw.py:27-28). Query shapes are index-accelerated (bare `ORDER BY <=> … LIMIT` inside the CTE; composite expression only re-ranks the small candidate set) | migration reads |

---

## 5. Phase 2 — isolation & security

- **Repo scoping is real and uniform:** the `(repo_id IS NULL OR repo_id = :repo_id)` filter is present in the dedup check and all 8 queries (9 SQL sites — §0 counts). Write-side `repo_id` threading verified at every real caller: `manager.py:1044`, `specialized_agents.py:508,796`, `main.py:1267` (doc-agent trigger), `base_graph.py:3326` (procedures), `hooks.py:58,87,107,130` (signature passes through). Unscoped/global rows remain deliberately visible as legacy fallback (documented INV-2/INV-8 semantics; test proof in `test_memory_project_scoping_queries.py:72-131`). Learning signals are intentionally unscoped. VERIFIED CLEAN.
- **No unauthenticated memory-write API:** all memory endpoints are reads or gated actions — `GET /patterns`, `/analytics`, `/search`, `/lessons` require `require_authenticated`; `POST /lessons/{id}/rollback` requires `require_approver`; `POST /{id}/feedback` requires `require_authenticated` and only flips a usefulness counter. No endpoint writes memory content. Content writes flow only through agent tool calls / pipeline hooks / prompt deploy. VERIFIED CLEAN.
- **LLM merge bounded and cheap:** `model_router` = Haiku tier by default (config.py:35-38); `max_tokens` 512 (`_merge_via_llm`, versioned_memory.py:556,577) / 768 (`_merge_via_llm_n`, 421,452) / 400 (LessonStore compression, base_graph.py:581-582); caps: ≤20 merges per promote (config.py:1719-1722), ≤200 candidate scan (1723-1726), ≤3 LLM merge calls per consolidation cycle and OFF by default (1752-1779). No user-controlled input can drive an unbounded generation. VERIFIED CLEAN.
- **Prompt-injection surface of memory content** (LLM-written text re-injected into future prompts) is noted here but scored under Audit 05 (Security) per the division of audits.

---

## 6. Phase 3 — performance

- **Embedding calls:** one per row write (single-text — batching would not apply) and **7 per agent run read** via `query_memory_context` (MEM-03-003, the main finding here). The `_embed` client itself is correctly non-blocking (`asyncio.to_thread`, store.py:405-410) with 3 attempts/backoff.
- **HNSW usage:** indexes exist (§4); query shapes allow the index to serve the ANN ordering; `vector_norm(embedding) > 0` / `archived=false` / repo predicates act as post-filters on the indexed scan (standard pgvector behavior). No full-scan-by-construction shape found.
- **N+1 patterns:** MEM-03-003 (7 sequential sub-queries + 7 duplicate embeds + per-run throwaway engine in the sync bridge). The pipeline prefetch path is single-query (graph.py:257). `record_memory_access` is bounded to the returned row ids per query.
- **Hot-path protection done right:** LessonStore's at-capacity LLM compression runs outside the store lock, with an isolated 10 s zero-retry client that cannot trip the shared circuit breaker (base_graph.py:486-597; config.py:795-798). VERIFIED CLEAN.

---

## 7. Cross-audit discovery (not scored in this layer) — leader-election engine pool is undersized: 16 connections vs 20 loop tasks

Found while auditing the memory maintenance loops; scored under Audit 04/06 to avoid double-counting.

- `_leader_loop_names` lists **16** names (main.py:1625-1642) and is used verbatim to size the shared engine: `pool_size=16, max_overflow=0` (1643-1647). But **20** `_run_as_leader` tasks are created (1665-1792). The 4 missing names: `versioned_lesson_consolidation`, `memory_embeddings_consolidation`, `agent_historical_performance_rollup`, `documentation_score_compute`.
- Each lock-winning loop holds its pooled connection for its entire lifetime by design — the session-scoped `pg_advisory_lock` requires it (`async with engine.connect()` wraps `await run_loop()`, main.py:1374-1399).
- With `LEADER_ELECTION_ENABLED=true` (**default**, config.py:1642-1643), 18 loops hold connections under default config (two loops, `failed_rq_job_sweep`/`redis_streams_drain`, exit immediately in default backend) and 20 with `QUEUE_BACKEND=rq` + Redis Streams enabled — both above 16. Excess checkout attempts wait on QueuePool and raise after SQLAlchemy's default 30 s `pool_timeout` (no override at 1341-1343); `_run_as_leader` has no try/except around `engine.connect()`, so those background tasks die for the process lifetime (unretrieved task exception). Expected victims are the tail-by-creation-order loops (e.g. `prompts_score_compute`, `documentation_score_compute`, `enhancement_quality_monitor`, `dependency_auto_dispatch`), but the exact set is scheduling/config dependent.
- Impact: 2–4 singleton maintenance loops silently never run in a default-configured deployment. Recommendation (for the fix owner): derive the pool size from the actual task count (or a single source of truth), add `pool_timeout` + try/except with retry in `_run_as_leader`.

---

## 8. Verdict and fix order

**Verdict: READY** — the memory layer is real, durable, and well-engineered; the findings are quality/correctness refinements, not structural failures. Fix MEM-03-001 first (it silently degrades what every agent reads), then MEM-03-002 (restores an advertised repair path), then MEM-03-003 (removes 7× duplicate provider calls per run).

Fix order:
1. MEM-03-001 add `category='task'` predicate + regression test [Small]
2. MEM-03-002 move/lift the zero-vector repair out of the consolidation `continue` path [Small]
3. MEM-03-003 embed once per `query_memory_context` (pass vector / gather sub-queries) [Medium]
4. MEM-03-004 decide: skip zero-vector writes without a key, or document write-and-repair; fix the base_graph comment [Small]
5. MEM-03-005 shared category constant + 422 on unknown `?category=` [Small]
6. MEM-03-006 serialize/scope the publish-time merge (lock or uniqueness constraint) [Small–Medium]
