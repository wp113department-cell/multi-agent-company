import { expect, test } from "@playwright/test";
import { json } from "./fixtures";

test.describe("Login", () => {
  test("signs in and redirects to /repo on success", async ({ page }) => {
    // Matches the backend's real LoginResponse shape (app/api/auth.py) —
    // {token_type, role, username, must_change_password}, no access_token
    // in the body since the JWT itself travels only as an httpOnly cookie.
    // The Set-Cookie header here stands in for that cookie so
    // middleware.ts's auth check (which looks for the gridiron_token
    // cookie) lets the post-login navigation to /repo through.
    await page.route("**/api/auth/login", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "set-cookie": "gridiron_token=e2e-fake-session-token; Path=/" },
        body: JSON.stringify({
          token_type: "bearer",
          role: "approver",
          username: "admin",
          must_change_password: false,
        }),
      })
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
