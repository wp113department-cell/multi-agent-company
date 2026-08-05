# Cluster R — Epic Repository Assignment: Architecture Design Proposal

Status: **Phase 1 (schema + API schema) and Phase 2 (execution-path wiring) both implemented and
production verified, 2026-08-05.** Phase 1: migration 031, `Epic.repo_id` model field/relationship,
`CreateEpicRequest.repo_id`. Phase 2: `resolve_epic_repo_path()`, `_launch_epic_manager()`/
`run_epic_manager()`/`_run_epic_manager_body()` threading `repo_id`/`repo_path`, and the
`_planning_node` `DevTask(repo_id=...)` fix (§1.3's real correction). See
`IMPLEMENTATION_PROGRESS.md`'s matching entries for full evidence (Phase 1: 10 tests, real-Postgres
migration verification; Phase 2: 7 tests including a full run through the real graph; both phases'
tests proven to fail without their implementation; full regression after Phase 2: 3870 passed/0
failed; `mypy --strict` clean throughout). **Phase 3 (the optional-vs-required `repo_id` product
decision, UI default, and the frontend repo picker — §7/§10 step 6) is not started** — scoped for
independent review before implementation, per explicit user instruction.

## 0. Executive summary

Epics — the top-level unit of work in this system — have no way to record which repository their
work happens against. `CreateEpicRequest` has exactly two fields (`title`, `description`); the
`Epic` model has no `repo_id` column. Every real epic today silently falls back to
`settings.target_repo_path` (the process-global active repo), the exact "resolve at the wrong
time, from the wrong source" class of risk Day 4 fixed for individual tasks — except epics were
never brought under that fix because they never had a `repo_id` to resolve from.

The fix is small and almost entirely mechanical: `DevTask` already solved this exact problem
(`repo_id: int | None`, FK to `repos.id`, resolved into a filesystem path via
`resolve_task_repo_path()`), and Cluster O's Phase 1b already threaded an `EpicManagerState["repo_id"]`
field through the epic-manager graph in anticipation of this — it just has nothing real to carry
today. This design gives `Epic` the same `repo_id` column `DevTask` has, threads it through the one
new code path that needs it, and lets Cluster O's existing wiring start working with no further
changes to the memory-scoping call sites themselves.

**One real correction found during this review, not assumed from the original backlog note**:
`EpicManagerState`'s own docstring (`app/agents/manager.py:798-807`) claims that once epics gain a
real repo_id, downstream scoping "starts scoping automatically with no further code change here."
That's only half true — see §1.3.

## 1. Current state — verified, not assumed

### 1.1 Schema layer

`Epic` (`app/db/models.py:345-364`) has no `repo_id` column, no `repo` relationship, and no index
on anything repo-related. Confirmed by reading the class directly — not inferred from the API
shape. Contrast with `DevTask` (`app/db/models.py:63-127`), which has had `repo_id` since migration
`007_task_repo.py`:

```python
repo_id: Mapped[int | None] = mapped_column(
    BigInteger, ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
)
repo: Mapped["Repo | None"] = relationship("Repo", foreign_keys=[repo_id])
```

`Repo` (`app/db/models.py:465-484`) is the existing first-class repo entity: `id`, `github_url`,
`name`, `local_path`, `status` (`cloning|ready|error`), `is_active`. Nothing about it needs to
change — this is purely a new consumer of an existing table.

### 1.2 API layer

`CreateEpicRequest` (`app/api/epics.py:33-36`):

```python
class CreateEpicRequest(BaseModel):
    title: str
    description: str
    complexity_multiplier: float = 1.0
```

Contrast with `CreateTaskRequest` (`app/api/tasks.py:41-51`), which already has
`repo_id: int | None = None` as an optional field, exactly the shape to mirror. `create_epic()`
(`app/api/epics.py:87-125`) constructs `Epic(...)` with no repo field, and fires
`asyncio.create_task(_launch_epic_manager(epic_id, body.description))` — `_launch_epic_manager`
(`app/api/epics.py:349-358`) takes only `epic_id`/`goal`, never a repo. `approve_epic_cost()`
(`app/api/epics.py:229-257`) re-launches the same way on the cost-approval path — same gap, second
call site.

### 1.3 Execution / graph layer — the real finding

`run_epic_manager(epic_id, goal, db, repo_path: str | None = None)` (`app/agents/manager.py:760-779`)
has exactly one real caller (`_launch_epic_manager`), which never passes `repo_path`. It is always
`None` in production today. `_run_epic_manager_body`'s initial graph state
(`app/agents/manager.py:1444-1472`) sets `"repo_path": repo_path` (always `None`) and has **no**
`repo_id` key at all in the initial state.

The graph (`build_epic_manager_graph`, `app/agents/manager.py:1382-1432`) runs, in order:
`resource_check → cost_estimate → planning → conflict_check → coding → finalize`.

- `_resource_check_node` (first node, line 817) and `_cost_estimate_node` (line 940) both read
  `state.get("repo_path")` — a **string** — falling back to `settings.target_repo_path`. This means
  the very first thing the epic manager does (a real RAM/CPU/disk check against a real filesystem
  path) already needs the correct path, before planning even starts.
- `_planning_node` (line 1009) creates the epic's one real `DevTask`:
  ```python
  task = DevTask(
      title=goal[:500],
      description=goal,
      status="planning",
      epic_id=epic_id,
  )
  ```
  **No `repo_id=` is passed.** The node then returns `"repo_id": task.repo_id` — which is always
  `None`, because nothing set it on the object being read from. `EpicManagerState["repo_id"]`
  (declared line 808) is documented as "resolved in `_planning_node` from the epic's own
  internally-created `DevTask.repo_id`" — i.e. today it's an *output* of planning, derived from a
  field nobody populates.
- `_finalize_node` (line ~1200) correctly calls `embed_task_outcome(..., repo_id=state.get("repo_id"))`
  on both the halted path (line 1289) and the completed path (line 1337) — this is Cluster O's
  Phase 1b memory-scoping wiring, and it is genuinely correct and forward-compatible **once
  `state["repo_id"]` is non-`None`**. No changes needed at either call site.

**The correction**: the existing docstring's claim ("no further code change here") is accurate for
the two `embed_task_outcome()` call sites, but not for `_planning_node`'s `DevTask(...)`
construction. Today, causality runs `DevTask.repo_id → state["repo_id"]` (and `DevTask.repo_id` is
never set, so this is vacuous). The fix must flip this: `Epic.repo_id` is the real source of truth,
so causality needs to run `Epic.repo_id → initial state["repo_id"] → DevTask(repo_id=...)` — i.e.
`_planning_node`'s `DevTask(...)` call itself needs a one-line change
(`repo_id=state.get("repo_id")`), not just upstream plumbing. Documenting this now so it isn't
missed as "already handled" when implementation starts.

### 1.4 A proven, correct repo-resolution precedent already exists

`resolve_task_repo_path(task: DevTask) -> str | None` (`app/db/repository.py:64-89`):

```python
def resolve_task_repo_path(task: DevTask) -> str | None:
    if task.repo is not None and task.repo.status == "ready":
        return task.repo.local_path
    return None
```

This is the pattern `tasks.py` independently arrived at three separate times before being factored
out — the single source of truth is always the DB-persisted `repo_id`, resolved to a path through
`Repo.status == "ready"`, never the mutable `app.api.repo._active_repo_path` global. `get_task()`
(`app/db/repository.py:57-61`) eager-loads `.repo` via `selectinload` so this never needs an extra
query. This is exactly the shape a new `resolve_epic_repo_path(epic: Epic) -> str | None` should
mirror — not a new resolution strategy, a second instance of the same one.

### 1.5 Frontend

`app/epics/page.tsx` (web) has a creation form with only `title`/`description` state — no repo
selector, matching the backend's current `CreateEpicRequest` exactly. `lib/api.ts::createEpic()`
(line 288) has no `repoId` parameter. Contrast with `components/NewTaskForm.tsx`, which already has
a working repo `<select>` (lines ~299-320) bound to `repoId: number | null` state and passed to
`createTask({ ..., repoId })` (`lib/api.ts:123-128`, `repo_id: input.repoId ?? null`). The frontend
change is additive and has a direct, working precedent to copy — not novel UI design.

## 2. True source of repository ownership

Same answer as Cluster O's ADR 006, applied one level up: **`Epic.repo_id`** is the single source
of truth for which repository an epic's work happens in, resolved to a filesystem path only through
`Repo.local_path` gated on `Repo.status == "ready"` — never the `_active_repo_path` global, never a
string path passed around independently of the FK. `DevTask.repo_id` (Cluster O's own source of
truth for *task*-level memory scoping) is *populated from* `Epic.repo_id` at the one place a
task is created for an epic (`_planning_node`) — it is not a competing source, it is downstream of
it, exactly the way `DevTask.repo_id` today is set once at task-creation time and never updated
(INV-7, `app/db/repository.py:98-100`) — this design preserves that same "set once, at creation,
never mutated" invariant for the new epic→task inheritance.

## 3. Data flow — where `repo_id` must originate and where it must travel

```
CreateEpicRequest.repo_id (new, optional, mirrors CreateTaskRequest.repo_id)
        │
        ▼
create_epic(): Epic(repo_id=body.repo_id, ...)  — persisted once, at creation
        │
        ▼
_launch_epic_manager(epic_id, goal): loads Epic (selectinload .repo),
        resolve_epic_repo_path(epic) → repo_path string
        │
        ▼
run_epic_manager(epic_id, goal, db, repo_id=epic.repo_id, repo_path=repo_path)
        │
        ▼
_run_epic_manager_body(): initial_state = {..., "repo_id": repo_id, "repo_path": repo_path}
        │
        ├──► _resource_check_node   (reads repo_path — already correct shape, just needs a real value)
        ├──► _cost_estimate_node    (reads repo_path — same)
        ├──► _planning_node         (NEW: DevTask(repo_id=state.get("repo_id"), ...))
        │        │
        │        └──► task.repo_id now correctly inherited from the epic
        │
        └──► _finalize_node         (embed_task_outcome(repo_id=state.get("repo_id"))) — unchanged,
                                      already correct, was just fed None before
```

Existing epics (created before this migration) get `repo_id = NULL` — identical real behavior to
today (falls back to `settings.target_repo_path`), matching Cluster O's own Q8 precedent
("NULL means legacy/unscoped"). No backfill, no forced choice, strictly additive and
backward-compatible: any caller that doesn't send `repo_id` (including today's frontend, until it's
updated) keeps working exactly as it does now.

## 4. Migration

New file `migrations/versions/031_epic_repo_id.py`, mirroring `007_task_repo.py` /
`024_memory_project_scoping.py`'s exact shape (nullable FK, `ondelete="SET NULL"`, dedicated index):

```python
def upgrade() -> None:
    op.add_column(
        "epics",
        sa.Column("repo_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_epics_repo_id_repos",
        "epics", "repos",
        ["repo_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_epics_repo_id", "epics", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_epics_repo_id", table_name="epics")
    op.drop_constraint("fk_epics_repo_id_repos", "epics", type_="foreignkey")
    op.drop_column("epics", "repo_id")
```

No data migration needed — nullable column, no existing rows touched.

## 5. API changes

- `CreateEpicRequest`: add `repo_id: int | None = None`.
- `create_epic()`: pass `repo_id=body.repo_id` into `Epic(...)`.
- `_epic_to_response()`, `list_epics()`, `get_epic()`: add `"repoId": epic.repo_id` to every
  response dict — parity with `DevTask`'s existing `"repoId": task.repo_id`
  (`app/api/tasks.py:100`), needed for the frontend to show/filter by repo at all.
- `_launch_epic_manager(epic_id, goal)` → `_launch_epic_manager(epic_id, goal, repo_id)`: loads the
  `Epic` (eager-loading `.repo`), resolves `repo_path` via the new `resolve_epic_repo_path()`,
  passes both into `run_epic_manager()`.
- `approve_epic_cost()`'s re-launch call site gets the same treatment — currently drops repo
  context on re-launch too (a second, smaller instance of the same root gap, same fix).

## 6. Non-API changes

- `app/db/models.py::Epic`: add `repo_id` column + `repo` relationship (mirrors `DevTask` exactly).
- `app/db/repository.py`: new `resolve_epic_repo_path(epic: Epic) -> str | None`, identical shape to
  `resolve_task_repo_path()`. Whatever query loads `Epic` for this purpose needs
  `selectinload(Epic.repo)`, mirroring `get_task()`.
- `app/agents/manager.py`:
  - `run_epic_manager()` / `_run_epic_manager_body()`: add `repo_id: int | None = None` parameter,
    thread into `initial_state["repo_id"]`.
  - `_planning_node()`: the one required logic change — `DevTask(..., repo_id=state.get("repo_id"))`.
  - `EpicManagerState` docstring (lines 798-807): update to reflect the corrected causality (§1.3) —
    documentation debt, not a functional risk, but should not ship stale.
- Frontend (`apps/web`): `lib/api.ts::createEpic()` gains `repoId?: number | null`, serialized as
  `repo_id`; `app/epics/page.tsx` gains a repo `<select>`, copying `NewTaskForm.tsx`'s existing
  pattern (fetch repos, bind to state, optional — no forced selection, consistent with
  `CreateTaskRequest.repo_id`'s own optionality).

## 7. Open design questions (not resolved unilaterally, flagged per Agents-scoping precedent)

1. **Required vs. optional at creation**: `CreateTaskRequest.repo_id` is optional and this design
   mirrors that by default. An alternative is making it required for new epics (forcing an explicit
   choice, no silent global fallback) — a product decision, not an engineering one; recommend
   optional-with-fallback for consistency and zero frontend breakage, but flagging for confirmation
   before implementation.
2. **UI defaulting**: should the new repo `<select>` default to the currently-active repo (mirroring
   whatever default `NewTaskForm.tsx` uses today), or start unselected? Same category of decision as
   #1, deferred to whoever implements the frontend piece.

Both are small, reversible choices that don't change the backend design above regardless of the
answer — noted so they aren't silently decided by whoever writes the code.

## 8. Risk analysis

- **Backward compatibility**: strictly additive. Nullable column, optional API field, existing
  callers (frontend not yet updated, any script hitting the API directly) keep working identically.
- **Blast radius**: touches `app/api/epics.py`, `app/agents/manager.py`, `app/db/models.py`,
  `app/db/repository.py`, one new migration, and (optionally, same PR or follow-up) two frontend
  files. No changes to `Repo`, `DevTask`, Cluster O's memory-scoping call sites, or Cluster Q's
  scoring modules — none of them need to know this changed.
- **Regression surface**: `_planning_node`'s `DevTask(...)` change is the only line that touches
  already-running production logic; every other change either adds a new optional field or a new
  function. The existing 3853-test suite's epic-manager tests (`test_agents_manager.py` and
  siblings — to be confirmed by name before implementation) are the regression gate; a repo_id=None
  epic must continue behaving byte-for-byte identically to today.
- **Cross-repo leakage**: none introduced — this design only ever *adds* scoping information that
  didn't exist before; it cannot cause data that was previously scoped to become unscoped.

## 9. Estimated implementation size

**S-M**, consistent with the original backlog entry's own estimate — confirmed, not revised, after
this review. One migration (mechanical, 3 precedents to copy from), one model field, ~5 real call
sites in `manager.py`/`epics.py` (2 of which are the existing, already-correct
`embed_task_outcome()` sites needing no change), one new small helper function, and an optional
frontend pass with a direct working component to copy. No new subsystem, no new design pattern —
entirely an application of Cluster O's own established `repo_id` convention one level up the
domain model.

## 10. Suggested implementation order (not started — awaiting go-ahead)

1. Migration 031 + `Epic.repo_id`/`Epic.repo` model fields — smallest independently-testable unit.
2. `resolve_epic_repo_path()` in `app/db/repository.py`, mirroring `resolve_task_repo_path()`,
   with its own unit tests (ready/not-ready/None-repo cases, same test shape as the task version).
3. `CreateEpicRequest.repo_id` + `create_epic()` persisting it + response fields (`repoId`) — API
   surface, testable independently of the graph changes.
4. `_launch_epic_manager()` / `run_epic_manager()` / `_run_epic_manager_body()` threading, plus the
   `_planning_node()` fix — the graph/execution-path change, needs an end-to-end test proving a real
   epic created with a real `repo_id` produces a `DevTask` with that same `repo_id`, and that
   `embed_task_outcome()` is called with a non-`None` `repo_id` on both the halted and completed
   paths (mirroring Cluster O Phase 1b's own verification style).
5. `approve_epic_cost()`'s re-launch call site — same fix, second call site.
6. Frontend repo selector — optional, can ship in the same pass or as an immediate follow-up once
   the backend is production verified, since the API accepting `repo_id` doesn't require the UI to
   send it.

Each step gets its own production-verification pass (real Postgres, tests proven to fail without
the change, `mypy --strict`, full regression) before moving to the next — same discipline used for
every Cluster Q slice.
