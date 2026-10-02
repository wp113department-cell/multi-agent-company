import { defineConfig, devices } from "@playwright/test";

// Production audit 12: real-stack journeys (no mocks). Unlike
// playwright.config.ts, this starts nothing — run the real backend on :8000
// and `next start -p 3100` first (see e2e-real/journeys.spec.ts).
export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
