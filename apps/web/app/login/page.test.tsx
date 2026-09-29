import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../../lib/auth", () => ({ login: vi.fn() }));

// Production audit 2026-09-29: the dev-login shortcut (with the dev admin
// password) must only exist under `next dev`, never in a production build.
// DEV_LOGIN_ENABLED is read at module load, so each case re-imports the page.
async function renderWithNodeEnv(env: string) {
  vi.stubEnv("NODE_ENV", env);
  vi.resetModules();
  const { default: LoginPage } = await import("./page");
  render(<LoginPage />);
}

describe("LoginPage", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("hides the Developer Login shortcut outside development", async () => {
    await renderWithNodeEnv("production");
    expect(screen.queryByText("Developer Login")).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
  });

  it("shows the Developer Login shortcut under next dev", async () => {
    await renderWithNodeEnv("development");
    expect(screen.getByText("Developer Login")).toBeTruthy();
  });

  it("no longer links to the POST-only /api/auth/setup endpoint", async () => {
    await renderWithNodeEnv("production");
    expect(document.querySelector('a[href="/api/auth/setup"]')).toBeNull();
  });
});
