import { expect, test } from "@playwright/test";
import { authenticate, json } from "./fixtures";

const SAMPLE_BATCH_REVIEW = {
  epics: [],
  tasks: [
    {
      taskId: 42,
      title: "Add rate limiting to the API",
      description: "Use slowapi to rate-limit /api/tasks endpoints.",
      status: "ready_for_review",
      epicId: null,
      age: 2.5,
      createdAt: "2026-07-23T10:00:00Z",
    },
  ],
  totalPendingReview: 1,
};

test.describe("Daily Batch Review — approve/reject", () => {
  test.beforeEach(async ({ context }) => {
    await authenticate(context);
  });

  test("renders a pending task with Approve/Reject actions", async ({ page }) => {
    await page.route("**/api/epics/batch-review", (route) =>
      route.fulfill(json(SAMPLE_BATCH_REVIEW))
    );

    await page.goto("/review");

    await expect(page.getByText("Add rate limiting to the API")).toBeVisible();
    await expect(page.getByText("1 pending")).toBeVisible();
    // exact: true — "Approve All (1)" also contains "Approve" as a substring.
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  });

  test("clicking Approve calls the pipeline/approve endpoint and refreshes", async ({
    page,
  }) => {
    let approveCalled = false;
    let batchReviewCallCount = 0;

    await page.route("**/api/epics/batch-review", (route) => {
      batchReviewCallCount += 1;
      const remaining = approveCalled
        ? { epics: [], tasks: [], totalPendingReview: 0 }
        : SAMPLE_BATCH_REVIEW;
      return route.fulfill(json(remaining));
    });
    await page.route("**/api/tasks/42/pipeline/approve", (route) => {
      approveCalled = true;
      return route.fulfill(json({ approved: true }));
    });

    await page.goto("/review");
    await expect(page.getByText("Add rate limiting to the API")).toBeVisible();

    await page.getByRole("button", { name: "Approve", exact: true }).click();

    await expect(page.getByText("Nothing pending review")).toBeVisible();
    expect(approveCalled).toBe(true);
    expect(batchReviewCallCount).toBeGreaterThanOrEqual(2);
  });

  test("shows the empty state when nothing is pending", async ({ page }) => {
    await page.route("**/api/epics/batch-review", (route) =>
      route.fulfill(json({ epics: [], tasks: [], totalPendingReview: 0 }))
    );

    await page.goto("/review");

    await expect(page.getByText("Nothing pending review")).toBeVisible();
  });
});
