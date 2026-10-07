import { expect, test } from "@playwright/test";
import { authenticate, json } from "./fixtures";

// UI redesign (2026-10-07): the Agents page shows the full built-in catalog by
// category and the user's own agents (create / run / delete).
const CATALOG = {
  total: 3,
  categories: [
    {
      name: "Developers",
      description: "Write and change the code.",
      count: 2,
      agents: [
        { name: "backend_dev", displayName: "Backend Dev", purpose: "Writes server code.", tools: ["read_file"], capabilities: ["backend"], available: true, state: "sleep", risk: "medium" },
        { name: "frontend_dev", displayName: "Frontend Dev", purpose: "Builds the UI.", tools: ["read_file"], capabilities: [], available: true, state: "sleep", risk: "medium" },
      ],
    },
    {
      name: "Testing",
      description: "Prove the code works.",
      count: 1,
      agents: [{ name: "qa", displayName: "QA", purpose: "Runs the tests.", tools: ["run_tests"], capabilities: [], available: true, state: "sleep", risk: "low" }],
    },
  ],
};

test.describe("Agents", () => {
  test.beforeEach(async ({ context }) => {
    await authenticate(context);
    await context.route("**/api/team/agents", (route) => route.fulfill(json(CATALOG)));
    await context.route("**/api/team/tools", (route) =>
      route.fulfill(json({ tools: [{ name: "read_file", description: "Read a file" }, { name: "list_files", description: "List files" }] }))
    );
  });

  test("shows categories with counts and opens one", async ({ page }) => {
    await page.route("**/api/team/custom-agents", (route) => route.fulfill(json({ agents: [] })));
    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Your AI team" })).toBeVisible();
    await expect(page.getByText("3 built-in specialists", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: /Developers/ }).click();
    await expect(page.getByText("Backend Dev")).toBeVisible();
    await expect(page.getByText("Frontend Dev")).toBeVisible();
  });

  test("creates an agent", async ({ page }) => {
    let created: unknown = null;
    await page.route("**/api/team/custom-agents", async (route) => {
      if (route.request().method() === "POST") {
        created = route.request().postDataJSON();
        return route.fulfill(json({ id: 1, name: "Readme Checker", purpose: "x", tools: ["read_file"], capabilities: [], createdBy: null, createdAt: null }, 201));
      }
      return route.fulfill(json({ agents: [] }));
    });
    await page.goto("/agents");
    await page.getByRole("button", { name: /Create Agent/ }).click();
    await page.getByLabel("Agent name").fill("Readme Checker");
    await page.getByLabel("What should it do?").fill("Check that the README explains setup.");
    await page.getByRole("dialog").getByRole("button", { name: "Create agent" }).click();
    await expect.poll(() => created).toMatchObject({ name: "Readme Checker" });
  });
});
