import { defineConfig } from "@playwright/test";

// UI end-to-end tests: the real app (Vite dev server) in Chromium against a real local engine.
// Run with `pnpm e2e`. Set PW_CHANNEL=chrome or msedge to use an installed browser instead of
// Playwright's own Chromium.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1, // one engine, shared by every test
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1400, height: 860 },
    channel: process.env.PW_CHANNEL || undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "pnpm exec vite --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
