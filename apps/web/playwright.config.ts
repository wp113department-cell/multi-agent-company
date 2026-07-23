import { defineConfig, devices } from "@playwright/test";

// Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): zero E2E infra
// existed anywhere in this project. All specs mock the backend via
// page.route() fixtures (see e2e/fixtures.ts) — deterministic in CI, no
// live Postgres/agent fleet required, matching the plan's explicit design
// choice. webServer starts a real `next build && next start` against those
// mocks, not `next dev`, so this exercises the real production build.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3100",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    // `next start -p` directly — `pnpm run start -- -p 3100` was tried first
    // and is broken: pnpm's `--` passthrough combines with the "start"
    // script's own `next start` to produce `next start -- -p 3100`, which
    // Next's CLI misparses (`-p 3100` gets treated as a project-directory
    // argument, not a port flag) — confirmed by actually running it, not
    // assumed.
    command: "pnpm run build && npx next start -p 3100",
    url: "http://localhost:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
    },
  },
});
