import { defineConfig, devices } from "@playwright/test";
import { apiHost, apiPort, repoRoot, webPort } from "./env";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "html" : "list",
  use: {
    baseURL: `http://localhost:${webPort}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  // Postgres is expected to be up already — `pnpm test:e2e` starts it. These two
  // are the servers a developer would otherwise start by hand with `pnpm dev`.
  webServer: [
    {
      command: "apps/api/.venv/bin/python -m open_leprechaun",
      cwd: repoRoot,
      url: `http://${apiHost}:${apiPort}/api/health`,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
    {
      command: "pnpm dev",
      url: `http://localhost:${webPort}`,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
  ],
});
