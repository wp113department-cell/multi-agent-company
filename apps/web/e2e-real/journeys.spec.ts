import { expect, test, type Page, type Response } from "@playwright/test";

/**
 * Production audit 12 — REAL-STACK journeys. Nothing is mocked: the browser
 * drives the production Next build, which talks to a real FastAPI backend
 * and real Postgres. Requires (see playwright.real.config.ts):
 *   - backend on E2E_API_URL (default :8000), production frontend on
 *     E2E_BASE_URL (default :3100)
 *   - a throwaway user E2E_USER / E2E_PASS (approver role)
 *   - a ready project (the demo seeder supplies these)
 * Journeys that need a paid LLM call (plan generation, agent execution,
 * chat answers) are not here — they are in PENDING_TESTS_API_KEYS.md.
 */

const USER = process.env.E2E_USER ?? "audit12";
const PASS = process.env.E2E_PASS ?? "";
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

async function disableTour(page: Page) {
  await page.addInitScript(() => localStorage.setItem("mac_tour_done_v1", "1"));
}

async function login(page: Page, { showTour = false }: { showTour?: boolean } = {}) {
  if (!showTour) await disableTour(page);
  await page.goto("/login");
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill(PASS);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/start/);
}

async function openProjectTasks(page: Page): Promise<number> {
  const response = await page.request.get("/api/projects");
  expect(response.status()).toBe(200);
  const { projects } = await response.json() as { projects: { id: number; status: string }[] };
  const project = projects.find((p) => p.status === "ready");
  expect(project, "a ready project is required; load demo data before these journeys").toBeTruthy();
  await page.goto(`/tasks?project=${project!.id}`);
  await expect(page.getByLabel("Project", { exact: true })).toHaveValue(String(project!.id));
  await expect(page.getByLabel("What should be done?")).toBeEnabled();
  return project!.id;
}

test.describe.configure({ mode: "serial" });

test("A1 — wrong password is refused and stays on /login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(USER);
  await page.getByLabel("Password").fill("definitely-wrong");
  const resp = page.waitForResponse("**/api/auth/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  expect((await resp).status()).toBe(401);
  await expect(page).toHaveURL(/\/login/);
  // the backend's own message is shown, not a bare "HTTP 401" (audit 14)
  await expect(page.getByText("Invalid username or password")).toBeVisible();
});

test("A2 — real login sets an httpOnly session cookie", async ({ page, context }) => {
  await login(page);
  const cookie = (await context.cookies()).find((c) => c.name === "gridiron_token");
  expect(cookie, "session cookie missing").toBeTruthy();
  expect(cookie!.httpOnly).toBe(true);
});

test("A3 — API without a session is rejected (401)", async ({ playwright }) => {
  const anon = await playwright.request.newContext({ baseURL: API_URL });
  try {
    const r = await anon.get("/api/tasks");
    expect(r.status()).toBe(401);
  } finally {
    await anon.dispose();
  }
});

test("B — create a task in the UI, it is persisted and opens in detail", async ({ page }) => {
  await login(page);
  const title = `audit12 real journey ${Date.now()}`;
  const projectId = await openProjectTasks(page);
  const description = `${title}\nCreated by the audit 12 real-stack journey.`;
  await page.getByLabel("What should be done?").fill(description);
  const created = page.waitForResponse(
    (r) => r.url().endsWith("/api/tasks") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  const resp = await created;
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  const id = body.id ?? body.task?.id;
  expect(id, "created task id").toBeTruthy();
  expect(body.projectId).toBe(projectId);

  // Persisted: read back through the real API with the real session.
  const back = await page.request.get(`/api/tasks/${id}`);
  expect(back.status()).toBe(200);
  const saved = await back.json();
  expect(saved.title).toBe(title);
  expect(saved.description).toBe(description);
  expect(saved.projectId).toBe(projectId);

  // Visible in the list and in its own detail page.
  await page.goto(`/tasks?project=${projectId}`);
  await expect(page.getByText(title).first()).toBeVisible();
  await page.goto(`/tasks/${id}`);
  await expect(page.getByText(title).first()).toBeVisible();
});

test("Guided tour — first login opens it, and the navbar can replay it", async ({ page }) => {
  await login(page, { showTour: true });
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: /^Welcome to / })).toBeVisible();
  await dialog.getByRole("button", { name: "Next", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "Start", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Skip tour" }).click();
  await expect(dialog).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem("mac_tour_done_v1"))).toBe("1");
  await page.getByRole("button", { name: "Tour", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: /^Welcome to / })).toBeVisible();
  await dialog.getByRole("button", { name: "Skip tour" }).click();
  await expect(dialog).toBeHidden();
});

const PAGES = [
  "/start",
  "/repo",
  "/tasks",
  "/approvals",
  "/review",
  "/fleet",
  "/agents",
  "/metrics",
  "/cost",
  "/settings",
  "/epics",
  "/goals",
  "/roadmap",
  "/chat",
  "/console",
  "/onboarding",
];

test("Page tour — every page renders against the real backend with no 5xx or error screen", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await login(page);
  const problems: string[] = [];
  const onResp = (r: Response) => {
    if (r.url().includes("/api/") && r.status() >= 500) problems.push(`${r.status()} ${r.url()}`);
  };
  page.on("response", onResp);
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  for (const path of PAGES) {
    // A missing page (404) must fail the tour, not pass it silently
    // (Qoder cross-check PROD-12-105: "/stream" had no page and still "passed").
    const doc = await page.goto(path, { waitUntil: "load" });
    if (!doc || doc.status() >= 400) problems.push(`${path}: HTTP ${doc?.status()}`);
    // Live SSE streams keep the network busy, so "networkidle" never fires;
    // give each page's initial data requests time to complete instead.
    await page.waitForTimeout(2_500);
    if (/\/login/.test(page.url())) problems.push(`${path}: bounced to /login`);
    const crashed = await page.getByText(/something went wrong|application error/i).count();
    if (crashed) problems.push(`${path}: error boundary shown`);
  }
  expect(problems, problems.join("\n")).toEqual([]);
});

test("Alerts — a task that gets blocked shows up in the in-app bell", async ({ page }) => {
  await login(page);
  const projectId = await openProjectTasks(page);
  const stamp = Date.now();
  const mk = async (title: string, dependsOn?: number[]) => {
    const r = await page.request.post("/api/tasks", {
      data: { title, description: "audit 08 alerts journey", project_id: projectId, depends_on: dependsOn },
    });
    expect(r.status()).toBe(201);
    return (await r.json()).id as number;
  };
  const first = await mk(`audit08 alert dep ${stamp}`);
  const blockedTitle = `audit08 alert blocked ${stamp}`;
  const second = await mk(blockedTitle, [first]);

  // Real dependency gate: refuses to start and blocks the task ($0, no agent run).
  const run = await page.request.post(`/api/tasks/${second}/run`, { data: {} });
  expect(run.status()).toBe(409);
  const blocked = await page.request.get(`/api/tasks/${second}`);
  expect(blocked.status()).toBe(200);
  expect(await blocked.json()).toMatchObject({ status: "blocked", blockedReason: "dependency", projectId });

  await page.goto(`/tasks?project=${projectId}`);
  // Project-scoped filters show the actual API-created dependency failure.
  await page.getByRole("tab", { name: /^Blocked/ }).click();
  await expect(page.getByText(blockedTitle, { exact: true })).toBeVisible();
  await expect(page.getByText(`audit08 alert dep ${stamp}`, { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: /^Pending/ }).click();
  await expect(page.getByText(`audit08 alert dep ${stamp}`, { exact: true })).toBeVisible();
  await expect(page.getByText(blockedTitle, { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: /^All/ }).click();
  const bell = page.getByRole("button", { name: /Notifications, \d+ unread/ });
  await expect(bell).toBeVisible({ timeout: 20_000 });
  await bell.click();
  const entry = page.getByRole("dialog", { name: "Task alerts" }).getByText(blockedTitle);
  await expect(entry).toBeVisible();
  await entry.click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${second}$`));
});

test("A5 — an account that must change its password is blocked until it does", async ({ page }) => {
  const user = process.env.E2E_FLAG_USER;
  const pass = process.env.E2E_FLAG_PASS;
  test.skip(!user || !pass, "needs a throwaway account with must_change_password=true");
  await disableTour(page);
  await page.goto("/login");
  await page.getByLabel("Username").fill(user!);
  await page.getByLabel("Password").fill(pass!);
  await page.getByRole("button", { name: "Sign in" }).click();

  // Server refuses ordinary API calls until the password is changed.
  await expect(page.getByRole("form", { name: "Change password" })).toBeVisible();
  const blocked = await page.request.get("/api/tasks?limit=1");
  expect(blocked.status()).toBe(403);
  expect((await blocked.json()).error.reason).toBe("password_change_required");

  const fresh = `New-${Date.now()}-pass`;
  await page.getByLabel("New password", { exact: true }).fill(fresh);
  await page.getByLabel("Confirm new password").fill(fresh);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page).toHaveURL(/\/start/);
  expect((await page.request.get("/api/tasks?limit=1")).status()).toBe(200);
});

test("A4 — logout ends the session; protected pages redirect to /login", async ({ page }) => {
  await login(page);
  const r = await page.request.post("/api/auth/logout");
  expect(r.status()).toBe(204);
  expect((await page.request.get("/api/tasks?limit=1")).status()).toBe(401);
  await page.goto("/tasks");
  await expect(page).toHaveURL(/\/login/);
});
