import type { BrowserContext, Page } from "@playwright/test";

/**
 * Shared E2E helpers. Every spec mocks the backend via page.route() — no
 * live Postgres/agent fleet, matching this batch's deterministic-CI design.
 */

const FAKE_TOKEN = "e2e-fake-token";

/**
 * Sets the auth cookie (read by middleware.ts to gate page navigation) and
 * localStorage token (read by lib/auth.ts's getToken()/isAuthenticated(),
 * which drives NavBar's UI state) — mirrors exactly what a real login()
 * call does via setToken(), without driving the login form for every spec
 * that isn't specifically testing login itself.
 */
export async function authenticate(context: BrowserContext): Promise<void> {
  await context.addCookies([
    {
      name: "gridiron_token",
      value: encodeURIComponent(FAKE_TOKEN),
      url: "http://localhost:3100",
    },
  ]);
  await context.addInitScript((token) => {
    window.localStorage.setItem("gridiron_token", token);
  }, FAKE_TOKEN);
}

/** JSON mock for a page.route() handler. */
export function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

export const SAMPLE_AGENTS = [
  {
    agentId: "1",
    name: "architect",
    capabilityTags: ["design", "architecture", "read_only"],
    toolList: ["read_file", "list_files", "submit_plan"],
    promptRef: "roles/architect.md",
    version: "1.0",
    successRate: 1.0,
    avgRetries: 0.0,
    lastComputedAt: "2026-07-09T12:25:21Z",
    createdAt: "2026-07-09T12:25:21Z",
  },
  {
    agentId: "2",
    name: "backend_dev",
    capabilityTags: ["code", "backend", "python"],
    toolList: ["read_file", "write_file", "bash", "git_diff", "submit_patch"],
    promptRef: "roles/backend_dev.md",
    version: "1.0",
    successRate: 0.5,
    avgRetries: 1.5,
    lastComputedAt: "2026-07-09T12:25:21Z",
    createdAt: "2026-07-09T12:25:21Z",
  },
];

export const SAMPLE_TASK = {
  id: 42,
  title: "Add rate limiting to the API",
  description: "Use slowapi to rate-limit /api/tasks endpoints.",
  status: "ready_for_review",
  plan: "1. Add slowapi\n2. Wire middleware\n3. Add tests",
  diff: "diff --git a/app/main.py b/app/main.py\n+from slowapi import Limiter\n",
  filesTouched: ["backend/app/main.py"],
  project: "gridiron-backend",
  priority: "high",
  assignedAgent: "coder",
  finalSummary: "Diff ready — 1 files changed",
  repoId: null,
  repoName: null,
  createdAt: "2026-07-23T10:00:00Z",
  updatedAt: "2026-07-23T10:05:00Z",
  logs: [
    {
      logId: 1,
      taskId: 42,
      category: "diff",
      message: "Diff ready — 1 files changed",
      extraData: null,
      createdAt: "2026-07-23T10:05:00Z",
    },
  ],
};

/** Mocks every endpoint app/tasks/[id]/page.tsx fetches for SAMPLE_TASK. */
export async function mockTaskDetailApis(page: Page): Promise<void> {
  await page.route("**/api/tasks/42", (route) => route.fulfill(json(SAMPLE_TASK)));
  await page.route("**/api/tasks/42/pipeline", (route) => route.fulfill(json(null, 404)));
  await page.route("**/api/tasks/42/artifacts", (route) => route.fulfill(json([])));
  await page.route("**/api/tasks/42/pr", (route) =>
    route.fulfill(json({ branchName: null, prUrl: null, prStatus: "none" }))
  );
  await page.route("**/api/tasks/42/images", (route) => route.fulfill(json({ images: [] })));
}
