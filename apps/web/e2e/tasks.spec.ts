import { expect, test } from "@playwright/test";
import { authenticate, json, mockTaskDetailApis, SAMPLE_TASK } from "./fixtures";

test.describe("Task list and detail", () => {
  test.beforeEach(async ({ context }) => {
    await authenticate(context);
  });

  test("task list renders a task and links to its detail page", async ({ page }) => {
    await page.route("**/api/repo", (route) =>
      route.fulfill(json({ repos: [], activeRepoPath: "." }))
    );
    await page.route("**/api/tasks?*", (route) =>
      route.fulfill(json({ tasks: [SAMPLE_TASK], nextCursor: null }))
    );
    await page.route("**/api/tasks", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill(json({ tasks: [SAMPLE_TASK], nextCursor: null }));
      }
      return route.continue();
    });

    await page.goto("/tasks");

    const taskLink = page.getByRole("link", { name: SAMPLE_TASK.title });
    await expect(taskLink).toBeVisible();
    // Scoped to the task row itself — NewTaskForm's priority <select> also
    // has a "High priority" option, which Playwright's case-insensitive
    // getByText would otherwise also match.
    await expect(taskLink.getByText("high priority")).toBeVisible();
  });

  test("task detail page shows the real title, status, and plan", async ({ page }) => {
    await mockTaskDetailApis(page);

    await page.goto("/tasks/42");

    await expect(page.getByText(SAMPLE_TASK.title)).toBeVisible();
    await expect(page.getByText(/ready.for.review/i)).toBeVisible();
  });
});
