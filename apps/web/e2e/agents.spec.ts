import { expect, test } from "@playwright/test";
import { authenticate, json, SAMPLE_AGENTS } from "./fixtures";

test.describe("Agent Registry", () => {
  test.beforeEach(async ({ context }) => {
    await authenticate(context);
  });

  test("renders every registered agent with KPI summary", async ({ page }) => {
    await page.route("**/api/agents", (route) => route.fulfill(json(SAMPLE_AGENTS)));

    await page.goto("/agents");

    await expect(page.getByRole("heading", { name: "Agent Registry" })).toBeVisible();
    const table = page.getByRole("table");
    await expect(table.getByRole("cell", { name: "architect", exact: true })).toBeVisible();
    await expect(
      table.getByRole("cell", { name: "backend_dev", exact: true })
    ).toBeVisible();
    // Registered agents KPI = 2
    await expect(page.getByText("Registered agents")).toBeVisible();
  });

  test("filters the table by capability tag", async ({ page }) => {
    await page.route("**/api/agents", (route) => route.fulfill(json(SAMPLE_AGENTS)));

    await page.goto("/agents");
    const table = page.getByRole("table");
    await expect(table.getByRole("cell", { name: "architect", exact: true })).toBeVisible();

    await page.getByLabel("Capability").selectOption("backend");

    await expect(table.getByRole("cell", { name: "architect", exact: true })).toHaveCount(0);
    await expect(
      table.getByRole("cell", { name: "backend_dev", exact: true })
    ).toBeVisible();
  });

  test("shows the empty state with zero registered agents", async ({ page }) => {
    await page.route("**/api/agents", (route) => route.fulfill(json([])));

    await page.goto("/agents");

    await expect(page.getByText("No agents registered yet.")).toBeVisible();
  });
});
