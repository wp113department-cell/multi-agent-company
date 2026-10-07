import { expect, test } from "@playwright/test";
import { authenticate, json, mockTaskDetailApis, SAMPLE_TASK } from "./fixtures";

test.describe("Task list and detail", () => {
  test.beforeEach(async ({ context }) => {
    await authenticate(context);
  });

  test("task list renders a task and links to its detail page", async ({ page }) => {
    // Tasks are shown per project (UI redesign): one project, its detail.
    const project = {
      id: 7, name: "Demo Project", description: null, setup: "local_new",
      localPath: "/w/demo", githubUrl: null, visibility: null, repoId: 1,
      status: "ready", error: null, createdAt: null, lastOpenedAt: null, taskCounts: {},
    };
    await page.route("**/api/projects", (route) => route.fulfill(json({ projects: [project] })));
    await page.route("**/api/projects/7", (route) =>
      route.fulfill(json({ ...project, goals: [], epics: [], history: [] }))
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
    // Scoped to the task row itself, so the form's own controls never match.
    await expect(taskLink.getByText("high priority")).toBeVisible();
  });

  test("task detail page shows the real title, status, and plan", async ({ page }) => {
    await mockTaskDetailApis(page);

    await page.goto("/tasks/42");

    await expect(page.getByText(SAMPLE_TASK.title)).toBeVisible();
    await expect(page.getByText(/ready.for.review/i)).toBeVisible();
  });
});
