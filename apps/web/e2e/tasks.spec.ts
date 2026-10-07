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

  test("a failed Start shows the server error on the task page", async ({ page }) => {
    await mockTaskDetailApis(page);
    await page.route("**/api/tasks/42", (route) =>
      route.fulfill(json({ ...SAMPLE_TASK, status: "pending", plan: null, diff: null }))
    );
    await page.route("**/api/tasks/42/run", (route) =>
      route.fulfill(json({ detail: "The task could not start. Try again." }, 503))
    );
    await page.goto("/tasks/42");
    await page.getByRole("button", { name: /^Start \(/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: "The task could not start" }))
      .toHaveText("The task could not start. Try again.");
  });

  test("Chat from a task selects that task's project", async ({ page }) => {
    await mockTaskDetailApis(page);
    await page.route("**/api/tasks/42", (route) =>
      route.fulfill(json({ ...SAMPLE_TASK, projectId: 7 }))
    );
    await page.route("**/api/projects", (route) => route.fulfill(json({ projects: [
      { id: 8, name: "Other Project", localPath: "/w/other", status: "ready" },
      { id: 7, name: "Task Project", localPath: "/w/task", status: "ready" },
    ] })));
    await page.goto("/tasks/42");
    await page.getByRole("link", { name: "Chat with the team" }).click();
    await expect(page).toHaveURL(/\/chat\?project=7$/);
    await expect(page.getByLabel("Project", { exact: true })).toHaveValue("/w/task");
  });
});
