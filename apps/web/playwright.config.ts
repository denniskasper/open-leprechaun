import { defineConfig, devices } from "@playwright/test";
import { apiHost, e2eApiPort, e2eDatabaseUrl, e2eWebPort, repoRoot } from "./env";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "html" : "list",
  use: {
    baseURL: `http://localhost:${e2eWebPort}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  // Postgres is expected to be up already — `pnpm test:e2e` starts it. The run
  // has its own API, web server and database (env.ts), so it never reuses a
  // dev server or writes into the development data.
  webServer: [
    {
      // The end-to-end database is created and migrated before the API starts.
      command:
        "apps/api/.venv/bin/python apps/web/e2e/database.py && apps/api/.venv/bin/python -m open_leprechaun",
      cwd: repoRoot,
      url: `http://${apiHost}:${e2eApiPort}/api/health`,
      env: {
        API_PORT: String(e2eApiPort),
        DATABASE_URL: e2eDatabaseUrl(),
        // No scheduled price update or sync may reach a live provider behind a
        // test run's back.
        SCHEDULER_ENABLED: "false",
      },
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
    {
      command: "pnpm dev",
      url: `http://localhost:${e2eWebPort}`,
      // Vite's loadEnv lets these win over .env: its own port, and the proxy
      // aimed at the end-to-end API.
      env: { API_PORT: String(e2eApiPort), WEB_PORT: String(e2eWebPort) },
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
  ],
});
