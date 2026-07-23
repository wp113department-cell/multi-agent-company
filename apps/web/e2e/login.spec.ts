import { expect, test } from "@playwright/test";
import { json } from "./fixtures";

test.describe("Login", () => {
  test("signs in and redirects to /repo on success", async ({ page }) => {
    await page.route("**/api/auth/login", (route) =>
      route.fulfill(json({ access_token: "e2e-fake-token" }))
    );
    // /repo is where a successful login redirects to (LoginPage's
    // router.push("/repo")) — mock its API calls too so the destination
    // page doesn't error out after the redirect.
    await page.route("**/api/repo", (route) =>
      route.fulfill(json({ repos: [], activeRepoPath: "." }))
    );

    await page.goto("/login");
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill("gridiron123");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/repo/);
  });

  test("shows an error message on invalid credentials", async ({ page }) => {
    await page.route("**/api/auth/login", (route) =>
      route.fulfill(json({ detail: "Invalid username or password" }, 401))
    );

    await page.goto("/login");
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("Invalid username or password")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("unauthenticated navigation to a protected page redirects to /login", async ({
    page,
  }) => {
    await page.goto("/tasks");
    await expect(page).toHaveURL(/\/login\?from=%2Ftasks/);
  });
});
