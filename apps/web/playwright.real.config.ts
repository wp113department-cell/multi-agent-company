import { defineConfig, devices } from "@playwright/test";

// Production audit 12: real-stack journeys (no mocks). Unlike
// playwright.config.ts, this starts nothing — start the backend and production
// frontend first. E2E_BASE_URL can point to an isolated Docker frontend.
export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
