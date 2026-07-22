# Day 16 Plan — Image Input Pipeline

Per `docs/FLEET_ENHANCEMENT_PLAN.md` lines 1099-1141. Goal: user uploads an image of a website
design, agents extract requirements from it and build to match.

## Research (REPO-FIRST)

- `repos/cline/apps/vscode/src/core/prompts/responses.ts:351` `formatImagesIntoBlocks()` — confirms
  the exact Anthropic `ImageBlockParam` shape: `{type: "image", source: {type: "base64",
  media_type, data}}`, built from a `data:image/png;base64,...` data URL by splitting on the first
  comma. Simple, no extra research needed here beyond confirming the shape matches the plan's own
  pseudocode exactly.
- `repos/roo-code/src/core/mentions/resolveImageMentions.ts` +
  `src/core/tools/helpers/imageHelpers.ts` — confirms the plan's own 5MB-per-file/20MB-total/
  20-image limits are real, load-bearing constants in a real project (`DEFAULT_MAX_IMAGE_FILE_SIZE_MB
  = 5`, `DEFAULT_MAX_TOTAL_IMAGE_SIZE_MB = 20`, `MAX_IMAGES_PER_MESSAGE = 20`), and the
  fail-soft-skip-oversized-images-but-continue pattern. **Deliberately narrower format list than
  roo-code's** (which also supports svg/bmp/ico/tiff/avif for local file-mention reading): the
  Anthropic Messages API's vision support only accepts `image/jpeg`, `image/png`, `image/gif`,
  `image/webp` as valid `media_type` values — svg/bmp/ico/etc. would be rejected by the API itself,
  so the plan's own narrower "png, jpg, jpeg, gif, webp" list is the objectively correct one for
  this specific use case, not an arbitrary simplification.

## Codebase grounding

- **`POST /api/tasks/extract-pdfs`** (`api/tasks.py`) is an exact precedent for this day's upload
  endpoint shape: `files: list[UploadFile] = File(...)`, per-file size validation, extension
  validation. Reused directly rather than inventing a new upload pattern.
- **`NewTaskForm.tsx`**'s PDF-attachment UI (state array of `File`, add/remove list, extraction
  error state) is the exact precedent for the image upload zone. One real difference: PDFs extract
  text client-side with no server dependency before task creation exists; images must be persisted
  server-side against a real `task_id` (the plan's own schema is `task_images(task_id, ...)`), so
  the New Task form's submit flow becomes two-phase: create the task first, then upload each
  selected image against the new task's real id — a small, well-contained change to the existing
  `mutationFn`.
- **`run_agent_graph()`**'s `messages: [{"role": "user", "content": initial_message}]` — confirmed
  by reading `call_llm()` (`base_graph.py`) that `content` flows straight into
  `client.messages.create(messages=messages, ...)` with no string-only processing anywhere in the
  main call path (`_trim_messages()` only slices by message count, never inspects `content`) — safe
  to make `content` a list of Anthropic content blocks instead of a plain string. `_AgentRunStateBase.messages`
  is already typed `list[dict[str, Any]]`, so no type changes needed there. A few auxiliary,
  non-critical call sites (`planner_node`'s facts/plan prompts, lesson-extraction context) read
  `messages[0]["content"]` expecting a string for embedding into a secondary prompt — with a list of
  blocks these degrade to an ugly-but-harmless `str(list)` stringification rather than crashing;
  out of scope to rewrite for this day (they're reflection/memory enhancements, not the main
  task-execution path the plan's success criteria is about).
- **Plan's own DB schema doesn't match this project's real schema** (`UUID PRIMARY KEY`, `tasks(id)`)
  — adapted to the real, established convention: `BigInteger` autoincrement PK, FK to
  `dev_tasks.id` (matches every other migration in this project, e.g. Day 14's `DevTask` columns).
- **Which real call sites need `images` threaded through**, traced explicitly (per the Days 11-15
  gap-closure's own lesson — a feature only wired into one of several real entry points is a real
  gap, not a false negative): `pm_node`/`architect_node` (`pipeline/graph.py`'s real, only planning
  pipeline — there's no second "simple mode" planning path the way Day 15 found for coding), and
  `run_frontend_dev()`/`run_reviewer()` (`manager.py`'s subtask loop, the one real dev-agent
  dispatch path — `run_backend_dev` intentionally excluded, matches the plan's own agent list of
  exactly 4: pm, architect, frontend_dev, reviewer).

## Design

**Migration 017 + `TaskImage` model** — `id` (BigInteger PK), `task_id` (FK `dev_tasks.id`,
`ondelete=CASCADE`), `base64_data` (Text), `mime_type` (String(50)), `display_order` (Int, default
0), `created_at` (server_default `now()`).

**Repository**: `create_task_image`, `list_task_images` (metadata only — id/mimeType/order/
createdAt, never the base64 blob, to keep list responses small), `get_task_image` (single row,
including the base64 blob, for the raw-bytes endpoint), `delete_task_image`.

**API** (`api/tasks.py`, alongside the existing PDF-extraction section):
- `POST /api/tasks/{id}/images` — multipart upload, same validation shape as `extract-pdfs`: max 20
  files per call, 5MB per file, 20MB running total across the task's existing + new images,
  extension allowlist mapped to real Anthropic media types.
- `GET /api/tasks/{id}/images` — metadata list (for thumbnails).
- `GET /api/tasks/{id}/images/{image_id}` — raw image bytes with the correct `Content-Type`, for
  `<img src=...>` — avoids embedding large base64 blobs in JSON list responses that get polled.
- `DELETE /api/tasks/{id}/images/{image_id}`.

**`run_agent_graph()`**: new `images: list[dict[str, str]] | None = None` param (`[{"media_type":
..., "data": <base64>}, ...]`). When present, `content` becomes `[{"type": "text", "text":
initial_message}] + [image blocks]` instead of the plain string, in both the real LangGraph path
and the Groq-bypass path (kept consistent, even though Groq is temporary/removable per project
convention).

**Pipeline wiring**:
- `PipelineState` gains `images: list[dict[str, str]]`.
- `run_planning_pipeline()` fetches the task's images (if `db` provided) and populates
  `initial_state["images"]`.
- `pm_node`/`architect_node` read `state.get("images", [])` and pass to `run_agent_graph(images=...)`.
- `launch_manager()` fetches the task's images once (it has `db`) and threads them through
  `run_manager()` → the per-subtask `run_frontend_dev`/`run_reviewer` calls (backend_dev excluded).

**Frontend**: `NewTaskForm.tsx` gains an image picker (mirrors the PDF list UI) — thumbnails via
`URL.createObjectURL`, submit flow becomes create-task-then-upload-images. Task detail page gets an
image gallery section reading `GET /api/tasks/{id}/images` and rendering `<img
src="/api/tasks/{id}/images/{id}">` thumbnails.

## Success criteria (from the plan)

Upload a screenshot of a webpage → `pm_node` receives it as a real `ImageBlockParam` → `architect`
produces a plan informed by the visual → `frontend_dev` builds matching UI. Tests for the upload
endpoint + base64 round-trip (no real LLM call needed, matching the plan's own stated test scope).
