# Fleet Day 16 Test Report — Image Input Pipeline
Date: 2026-07-22

## What was built

Per `docs/DAY16_PLAN.md`, grounded in REPO-FIRST research before any design (CLAUDE.md rule).

### Research

- `repos/cline/apps/vscode/src/core/prompts/responses.ts:351` `formatImagesIntoBlocks()` —
  confirmed the exact Anthropic `ImageBlockParam` shape (`{type: "image", source: {type: "base64",
  media_type, data}}`), matching the plan's own pseudocode exactly.
- `repos/roo-code/src/core/mentions/resolveImageMentions.ts` +
  `src/core/tools/helpers/imageHelpers.ts` — confirmed the plan's 5MB-per-file/20MB-total/
  20-image limits are real, load-bearing constants in a real project. Deliberately used a
  **narrower** format allowlist than roo-code's (png/jpg/jpeg/gif/webp only, not
  svg/bmp/ico/tiff/avif): the Anthropic Messages API's vision support only accepts those 4 media
  types — a wider list would let files through the upload endpoint that the API itself would
  reject at inference time.
- **`POST /api/tasks/extract-pdfs`** (existing) was an exact precedent for the upload endpoint
  shape (`files: list[UploadFile] = File(...)`, per-file validation) — reused directly.
- **`NewTaskForm.tsx`**'s PDF-attachment UI was the exact precedent for the image picker, with one
  real difference handled: PDFs extract text client-side with no server dependency; images must
  persist against a real `task_id`, so the New Task form's submit flow became two-phase
  (create task, then upload each image against the new task's id).

### What was built

- Migration 017 + `TaskImage` model (`id`, `task_id` FK `dev_tasks.id` CASCADE, `base64_data`,
  `mime_type`, `display_order`, `created_at`) — adapted from the plan's own UUID/`tasks(id)`
  pseudocode schema to this project's real `BigInteger`/`dev_tasks` convention.
- Repository: `create_task_image`, `list_task_images` (metadata only), `get_task_image`,
  `delete_task_image`.
- API (`api/tasks.py`): `POST/GET /api/tasks/{id}/images`, `GET/DELETE
  /api/tasks/{id}/images/{image_id}` (raw bytes with correct `Content-Type`, for `<img src=...>` —
  avoids embedding base64 blobs in polled JSON responses).
- `run_agent_graph()` gained an `images: list[dict[str, str]] | None = None` param — when present,
  the first user message becomes a real Anthropic multimodal content block list instead of a plain
  string, in both the real LangGraph path and the Groq-bypass path.
- Pipeline wiring: `PipelineState` gained `images`; `run_planning_pipeline()` fetches the task's
  images once (mirrors the existing `memory_context` pre-fetch pattern exactly) and populates
  `initial_state["images"]`; `pm_node`/`architect_node` read `state.get("images", [])` and forward
  to `run_agent_graph()`. `launch_manager()` fetches images once and threads them through
  `run_manager()` → `run_frontend_dev()`/`run_reviewer()` (NOT `run_backend_dev`, matching the
  plan's exact 4-agent list: pm, architect, frontend_dev, reviewer).
- Frontend: `NewTaskForm.tsx` gained an image picker (thumbnails via `URL.createObjectURL`,
  create-task-then-upload-images submit flow); task detail page gained a reference-image gallery
  reading `GET /api/tasks/{id}/images` and rendering `<img src="/api/tasks/{id}/images/{id}">`.

## A real, load-bearing correctness check done before wiring (not assumed)

Read `call_llm()` (`base_graph.py`) to confirm `content` flows straight into
`client.messages.create(messages=messages, ...)` with no string-only processing anywhere in the
main call path (`_trim_messages()` only slices by message count, never inspects `content`) — safe
to make `content` a list of blocks. A few non-critical auxiliary call sites (`planner_node`'s
facts/plan prompts, lesson-extraction context) read `messages[0]["content"]` expecting a string;
with a list of blocks these degrade to a harmless `str(list)` stringification rather than crashing
— explicitly scoped out of this day (reflection/memory enhancements, not the main task-execution
path the plan's success criteria is about).

## Days 11-15 gap-closure lesson applied

Per the standing lesson from the 2026-07-22 gap-closure audit ("a feature only wired into one of
several real entry points is a real gap, not a false negative"): explicitly traced whether the
plan's 4-agent list (pm, architect, frontend_dev, reviewer) has any second real entry point the way
Day 15's bootstrap missed "simple" pipeline mode. Confirmed it does not — all 4 agents only exist
in the "full" pipeline path (`launch_planning_pipeline`/`launch_manager`); "simple" mode's
`launch_planner`/`launch_coder` use entirely different agent identities (`planner`, `coder`) that
are not part of Day 16's plan-specified scope. No gap found.

## Frontend verification

- `tsc --noEmit` — clean.
- `eslint` on all 3 changed files — clean.
- `npm run build` — succeeds; only the same 2 pre-existing unrelated warnings from before this day.

## Real-caller verification

```
create_task_image() → api/tasks.py (upload endpoint)
list_task_images()  → api/tasks.py (list endpoint) + api/agents.py (launch_manager) +
                       pipeline/graph.py (run_planning_pipeline)
get_task_image()    → api/tasks.py (bytes + delete endpoints)
delete_task_image() → api/tasks.py (delete endpoint)
images= forwarded   → frontend_dev.py, reviewer.py, architect.py, pm.py, manager.py (x2)
```
3rd clean day in a row — zero orphaned modules.

## Test Results

```
pytest tests/ -q
→ 2664 passed, 0 failed, 55 skipped, 17 deselected, 20 warnings in 90.60s (11 new tests)

mypy app/ --strict
→ 0 errors

Frontend: tsc --noEmit (clean), eslint (clean), npm run build (succeeds)
```

11 new backend tests (`test_task_images.py`): upload/list/get-bytes/delete round trip against a
real DB, rejection of unsupported formats/oversized files/over-count uploads, 404 handling,
`run_agent_graph()`'s multimodal content-block construction (both with and without images, to lock
in backward compatibility), `run_frontend_dev()`/`run_reviewer()` image forwarding, and
`run_planning_pipeline()`'s DB image fetch.

## Verdict
✅ GREEN FLAG — DAY 16 COMPLETE. Ready for Day 17 (Credential Vault).
