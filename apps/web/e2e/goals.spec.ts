import { expect, test } from "@playwright/test";
import { authenticate, json } from "./fixtures";

// G11 (2026-10-19): on the Roadmap page a goal is broken into epics of the
// selected project, and each epic is started by the user.

const PROJECT = {
  id: 7,
  name: "Shop",
  description: null,
  setup: "local_existing",
  localPath: "/work/shop",
  githubUrl: null,
  visibility: null,
  repoId: 3,
  status: "ready",
  error: null,
  createdAt: null,
  lastOpenedAt: null,
  taskCounts: {},
};

const GOAL_ID = "11111111-1111-1111-1111-111111111111";
const EPIC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const EPIC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

function goal(startedA: boolean) {
  return {
    goalId: GOAL_ID,
    text: "Customers can pay online",
    status: startedA ? "in_progress" : "proposed",
    summary: "Take card payments and send receipts.",
    projectId: 7,
    epicIds: [EPIC_A, EPIC_B],
    epics: [
      { epicId: EPIC_A, title: "Payment page", description: "Card form.", status: startedA ? "pending" : "proposed" },
      { epicId: EPIC_B, title: "Receipts", description: "Email a receipt.", status: "proposed" },
    ],
  };
}

test.describe("Roadmap — goals broken into epics", () => {
  test.beforeEach(async ({ context, page }) => {
    await authenticate(context);
    await page.route("**/api/projects", (r) => r.fulfill(json({ projects: [PROJECT] })));
    await page.route("**/api/roadmap?*", (r) => r.fulfill(json({ roadmap: null })));
  });

  test("a goal is broken into epics and an epic is started", async ({ page }) => {
    let created: { text?: string; project_id?: number } | null = null;
    let started: string | null = null;
    await page.route("**/api/goals?project_id=7", (r) =>
      r.fulfill(json(created ? [goal(started !== null)] : [])),
    );
    await page.route("**/api/goals", (r) => {
      created = r.request().postDataJSON();
      return r.fulfill(json(goal(false), 201));
    });
    await page.route(`**/api/epics/${EPIC_A}/start`, (r) => {
      started = EPIC_A;
      return r.fulfill(json({ epicId: EPIC_A, status: "pending", costEstimate: 0.4 }));
    });

    await page.goto("/roadmap");
    await page.getByRole("textbox", { name: "Goal" }).fill("Customers can pay online");
    await page.getByRole("button", { name: "Break into epics" }).click();

    await expect(page.getByText("Payment page", { exact: true })).toBeVisible();
    await expect(page.getByText("Receipts", { exact: true })).toBeVisible();
    await expect(page.getByText("Not started")).toBeVisible();
    expect(created).toEqual({ text: "Customers can pay online", project_id: 7 });

    await page.getByRole("button", { name: "Start" }).first().click();
    await expect(page.getByRole("link", { name: "Open (pending)" })).toHaveAttribute(
      "href",
      `/epics/${EPIC_A}`,
    );
    await expect(page.getByText("In progress")).toBeVisible();
    expect(started).toBe(EPIC_A);
  });

  test("an error from the AI is shown", async ({ page }) => {
    await page.route("**/api/goals?project_id=7", (r) => r.fulfill(json([])));
    await page.route("**/api/goals", (r) =>
      r.fulfill(json({ error: { code: "500", message: "Executive agent error: model unavailable" } }, 500)),
    );
    await page.goto("/roadmap");
    await page.getByRole("textbox", { name: "Goal" }).fill("Anything");
    await page.getByRole("button", { name: "Break into epics" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "model unavailable" })).toBeVisible();
  });
});
