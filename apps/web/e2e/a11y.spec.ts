import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { authenticate, json, SAMPLE_TASK } from "./fixtures";

/**
 * A44 accessibility (2026-10-16): automated axe checks on the main pages,
 * keyboard-only login, and the guided tour behaving as a real dialog
 * (focus moves in, stays in, Escape closes it). Backend mocked as in the
 * other specs.
 */

const project = {
  id: 7, name: "Demo Project", description: null, setup: "local_new",
  localPath: "/w/demo", githubUrl: null, visibility: null, repoId: 1,
  status: "ready", error: null, createdAt: null, lastOpenedAt: null, taskCounts: {},
};

async function mockApp(page: Page) {
  await page.route("**/api/projects", (r) => r.fulfill(json({ projects: [project] })));
  await page.route("**/api/projects/7", (r) =>
    r.fulfill(json({ ...project, goals: [], epics: [], history: [] })),
  );
  await page.route("**/api/tasks?*", (r) => r.fulfill(json({ tasks: [SAMPLE_TASK], nextCursor: null })));
  await page.route("**/api/tasks/counts*", (r) => r.fulfill(json({ counts: {}, total: 1 })));
  await page.route("**/api/chat/sessions*", (r) => r.fulfill(json({ chats: [] })));
}

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.length} element(s) — ${v.help}`);
}

test.describe("Accessibility", () => {
  test("login page has no serious accessibility problems and works by keyboard", async ({ page }) => {
    await page.goto("/login");
    expect(await seriousViolations(page)).toEqual([]);

    const user = page.getByLabel(/username/i);
    await user.focus();
    await page.keyboard.type("someone");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel(/password/i)).toBeFocused();
  });

  for (const path of ["/tasks", "/chat"]) {
    test(`${path} has no serious accessibility problems`, async ({ page, context }) => {
      await authenticate(context);
      await mockApp(page);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await seriousViolations(page)).toEqual([]);
    });
  }

  test("the guided tour is a real dialog for keyboard users", async ({ page, context }) => {
    await authenticate(context);
    await context.addInitScript(() => window.localStorage.removeItem("mac_tour_done_v1"));
    await mockApp(page);
    await page.goto("/tasks");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // focus is inside the tour and stays there
    await expect(dialog.getByRole("button", { name: /next|get started/i })).toBeFocused();
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
});
