import type { BrowserContext, Page } from "@playwright/test";

/**
 * Shared E2E helpers. Every spec mocks the backend via page.route() — no
 * live Postgres/agent fleet, matching this batch's deterministic-CI design.
 */

/**
 * Builds a JWT-*shaped* fake token (header.payload.signature, unsigned) —
 * not a real signed JWT, but enough for lib/auth.ts's client-side
 * decodeJwtPayload() (which never verifies a signature; the server's real
 * signature-checked auth is the actual boundary) to read a `role` claim
 * out of it. Gap-closure Stage 1.4 added UI-level role gating
 * (isApprover()) on Approve/Reject buttons in review/approvals/epics/fleet
 * pages; the previous plain-string fake token had no payload segment at
 * all, so decodeJwtPayload() silently returned null and every
 * isApprover()-gated button rendered as if the user were a viewer —
 * breaking e2e/review.spec.ts, which predates the role-gating feature and
 * expects the buttons to be visible.
 */
function buildFakeToken(role: string): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "e2e-test-user", role })
  ).toString("base64");
  return `e2e-fake-header.${payload}.e2e-fake-signature`;
}

/**
 * Sets the auth cookie (read by middleware.ts to gate page navigation) and
 * localStorage token (read by lib/auth.ts's getToken()/isAuthenticated(),
 * which drives NavBar's UI state) — mirrors exactly what a real login()
 * call does via setToken(), without driving the login form for every spec
 * that isn't specifically testing login itself. Defaults to "approver" so
 * existing specs (written before role gating existed) keep seeing the same
 * full-access UI; pass "viewer" to test the restricted-UI path instead.
 */
export async function authenticate(
  context: BrowserContext,
  role: string = "approver"
): Promise<void> {
  const token = buildFakeToken(role);
  await context.addCookies([
    {
      name: "gridiron_token",
      value: encodeURIComponent(token),
      url: "http://localhost:3100",
    },
  ]);
  await context.addInitScript((t) => {
    window.localStorage.setItem("gridiron_token", t);
  }, token);

  // NavBar renders on every page and polls these three endpoints in the
  // background (fleet pending count, approvals pending count, and an SSE
  // stream) regardless of which page a spec is actually testing. No spec
  // mocks them individually, so previously they fell through page.route()
  // entirely, hit the real network, and got proxied server-side by
  // next.config.mjs's rewrites() to NEXT_PUBLIC_API_URL (localhost:8000) —
  // which doesn't exist in the e2e job, producing ECONNREFUSED spam in the
  // webServer log on every run. Harmless to test correctness (NavBar's own
  // fetches are wrapped in try/catch and fail silently), but noisy and
  // unnecessary real-network activity in a suite designed to need zero live
  // backend. Registered on the context (not a single page) so it applies
  // fleet-wide across every spec automatically via this same authenticate()
  // call every spec's beforeEach already makes. Individual specs' own
  // page.route() calls for these same paths (if any) still take precedence
  // since they're registered later, per Playwright's route-matching order.
  await context.route("**/api/fleet/requests?*", (route) => route.fulfill(json([])));
  await context.route("**/api/approvals/pending", (route) =>
    route.fulfill(json({ approvals: [] }))
  );
  await context.route("**/api/fleet/requests/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: "" })
  );
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
