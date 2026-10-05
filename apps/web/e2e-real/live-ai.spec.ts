import { expect, test, type Page } from "@playwright/test";

/**
 * Audit 12 journeys C, D and G (PENDING_TESTS_API_KEYS.md L8–L10) — REAL LLM.
 *
 * Same real stack as journeys.spec.ts (production Next build → FastAPI →
 * Postgres, nothing mocked), but these spend real model tokens, so they are
 * off unless LIVE_AI=1. Run them only with the backend started in economy
 * mode, under the spend cap, with TARGET_REPO_PATH pointing at a THROWAWAY
 * git repo (a copy of backend/tests/fixtures/demo-repo) — never this project.
 *
 *   LIVE_AI=1 LIVE_REPO=/path/to/throwaway E2E_USER=… E2E_PASS=… \
 *     pnpm exec playwright test -c playwright.real.config.ts live-ai.spec.ts
 */

const LIVE = process.env.LIVE_AI === "1";
const REPO = process.env.LIVE_REPO ?? "";
const USER = process.env.E2E_USER ?? "audit12";
const PASS = process.env.E2E_PASS ?? "";
// Re-check D/G against an already-coded task without paying for C+D again.
const REUSE_TASK = Number(process.env.LIVE_TASK_ID ?? 0);

test.describe.configure({ mode: "serial" });
test.skip(!LIVE || !REPO, "live-AI journeys: set LIVE_AI=1 and LIVE_REPO (spends real tokens)");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill(PASS);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/repo/);
}

async function waitForStatus(page: Page, id: number, wanted: RegExp, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    const r = await page.request.get(`/api/tasks/${id}`);
    last = String((await r.json()).status ?? "");
    if (wanted.test(last)) return last;
    if (/^(blocked|failed|rejected|cancelled)$/.test(last)) break;
    await page.waitForTimeout(5_000);
  }
  throw new Error(`task ${id}: expected status ${wanted}, last seen "${last}"`);
}

let taskId = 0;

test("C — Smart Run routes a small task; the plan waits for approval, then coding starts", async ({
  page,
}) => {
  test.setTimeout(300_000);
  if (REUSE_TASK) {
    taskId = REUSE_TASK;
    test.skip(true, `reusing task ${REUSE_TASK} (LIVE_TASK_ID)`);
  }
  await login(page);
  await page.goto("/tasks");
  // "backend" + "python" route by keyword rules to ONE backend specialist
  // (no planning agents, no routing LLM call). subtract() is new: the demo
  // repo already has greet() and multiply().
  await page.getByLabel("Task title").fill(`live L8 subtract ${Date.now()}`);
  await page
    .getByLabel("Task description")
    .fill(
      "Backend Python only: add subtract(a: int, b: int) -> int returning a - b to demo_module.py.",
    );
  const created = page.waitForResponse(
    (r) => r.url().endsWith("/api/tasks") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Submit task" }).click();
  const body = await (await created).json();
  taskId = body.id ?? body.task?.id;
  expect(taskId, "created task id").toBeTruthy();

  await page.goto(`/tasks/${taskId}`);
  await page.getByRole("button", { name: /Smart Run/ }).click();

  // Human gate: nothing is coded before the plan is approved.
  const approve = page.getByRole("button", { name: "Approve Plan & Start Coding" }).first();
  await expect(approve).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/backend_dev/).first()).toBeVisible();
  await approve.click();
  // POST /approve starts the routed specialist (it used to call /run → 400).
  // Coding has started once the status leaves the plan state: coding/testing,
  // or ready_for_review WITH a diff if it already finished.
  await expect
    .poll(
      async () => {
        const t = await (await page.request.get(`/api/tasks/${taskId}`)).json();
        return /^(coding|testing)$/.test(t.status) || (t.status === "ready_for_review" && !!t.diff)
          ? "started"
          : String(t.status);
      },
      { timeout: 60_000, intervals: [2_000] },
    )
    .toBe("started");
});

test("D — the agent codes it in a worktree; the committed diff is reviewed and approved", async ({
  page,
}) => {
  test.setTimeout(600_000);
  expect(taskId, "journey C must create the task first").toBeTruthy();
  await login(page);
  // "ready_for_review" also means "plan waiting"; code is ready once a diff exists.
  const deadline = Date.now() + 540_000;
  let task: { status?: string; diff?: string | null } = {};
  while (Date.now() < deadline) {
    task = await (await page.request.get(`/api/tasks/${taskId}`)).json();
    if (task.status === "ready_for_review" && task.diff) break;
    if (/^(blocked|failed|rejected|cancelled)$/.test(String(task.status))) break;
    await page.waitForTimeout(5_000);
  }
  expect(task.status, "coding did not finish").toBe("ready_for_review");
  expect(task.diff ?? "").toContain("subtract");

  // Code review happens on the task page (the Review page lists plans and
  // epics awaiting approval, not finished diffs): the diff is shown there.
  await page.goto(`/tasks/${taskId}`);
  await expect(page.getByText(/def subtract/).first()).toBeVisible({ timeout: 30_000 });

  // The diff is HEAD...agent/task-<id>, so it is non-empty only when the
  // agent's work was really committed on the task branch. A git-push approval
  // is only recorded for GitHub-cloned repos; this throwaway repo has no remote
  // (tests must never push), so that request is not asserted here.

  await page.goto(`/tasks/${taskId}`);
  await page.getByRole("button", { name: "Approve & Complete" }).click();
  await waitForStatus(page, taskId, /^completed$/, 30_000);
});

test("G — repository chat streams an answer about the repo", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await page.goto("/chat");
  await page.getByPlaceholder("/absolute/path/to/repo").fill(REPO);
  await page.getByRole("button", { name: "Start Session" }).click();
  const box = page.getByPlaceholder(/Ask anything about the codebase/);
  await expect(box).toBeVisible({ timeout: 30_000 });
  await box.fill("Which functions does demo_module.py define? Answer in one short sentence.");
  await box.press("Enter");
  // Both names only appear if the model really read the file.
  await expect(page.getByText(/greet/).last()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/multiply/).last()).toBeVisible();
});
