import { expect, test } from "@playwright/test";

// The whole path, asserted end to end: Postgres answers the API, the API
// states what it knows about itself, and the browser puts it on screen. What
// the development database happens to hold decides the verdict, so only what
// every instance shows is asserted here.
test("the health panel states providers, Connections, tasks and storage", async ({ page }) => {
  await page.goto("/");

  const providers = page.getByRole("region", { name: "Data providers" });
  await expect(providers.getByText("coingecko")).toBeVisible();
  await expect(providers.getByText("defillama")).toBeVisible();
  await expect(providers.getByText("ecb")).toBeVisible();

  await expect(page.getByRole("region", { name: "Connections" })).toBeVisible();

  const tasks = page.getByRole("region", { name: "Scheduled tasks" });
  await expect(tasks.getByText("Crypto price update")).toBeVisible();
  // The e2e API runs with its scheduler off, and the panel says so.
  await expect(tasks.getByText(/does not answer schedules/)).toBeVisible();

  const storage = page.getByRole("region", { name: "Storage" });
  await expect(storage.getByText("Database")).toBeVisible();
  await expect(storage.getByText("Reference rates")).toBeVisible();
});

const QUIET = {
  checked_at: "2026-10-04T09:00:00Z",
  connections: [],
  tasks: [],
  scheduler_enabled: true,
  storage: {
    database_bytes: 52428800,
    crypto_daily_closes: 1200,
    security_daily_closes: 300,
    reference_rates: 90,
  },
};

function provider(name: string, overrides: object = {}) {
  return {
    name,
    feeds: "crypto_prices",
    state: "ok",
    last_success_at: "2026-10-04T08:45:00Z",
    last_error_at: null,
    last_error: null,
    affected_instruments: [],
    ...overrides,
  };
}

test("one failing provider is named with its Instruments, and links to where it is resolved", async ({
  page,
}) => {
  await page.route("**/api/health/report", (route) =>
    route.fulfill({
      json: {
        ...QUIET,
        providers: [
          provider("coingecko"),
          provider("defillama", {
            state: "outage",
            last_error_at: "2026-10-04T09:00:00Z",
            last_error: "defillama answered HTTP 502.",
            affected_instruments: [{ id: 7, symbol: "KAS", name: "Kaspa" }],
          }),
        ],
      },
    }),
  );
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "1 problem" })).toBeVisible();
  const problem = page.getByRole("list", { name: "Problems" }).getByRole("listitem").first();
  await expect(problem.getByRole("heading", { name: "defillama is not answering" })).toBeVisible();
  await expect(problem.getByRole("list", { name: "Affected Instruments" })).toContainText("KAS");
  // The other provider is stated as working, not swept into the failure.
  const providers = page.getByRole("region", { name: "Data providers" });
  await expect(
    providers.getByRole("listitem").filter({ hasText: "coingecko" }).getByText("Answering"),
  ).toBeVisible();

  await problem.getByRole("link", { name: "Run the update again" }).click();

  await expect(page).toHaveURL(/\/settings\/scheduled-tasks$/);
  await expect(page.getByRole("heading", { name: "Scheduled tasks", level: 1 })).toBeVisible();
});

test("with nothing wrong the panel reads operational", async ({ page }) => {
  await page.route("**/api/health/report", (route) =>
    route.fulfill({ json: { ...QUIET, providers: [provider("coingecko")] } }),
  );
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Operational" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Problems" })).toHaveCount(0);
});
