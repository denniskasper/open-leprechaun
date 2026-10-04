import { expect, test } from "@playwright/test";

// The whole path first: Postgres answers the API, the API derives each step,
// and the browser lists them. What the development database happens to hold
// decides which steps are done, so only what every instance shows is asserted.
test("the checklist lists the walk from a password to a report", async ({ page }) => {
  await page.goto("/first-run");

  const steps = page.getByRole("list", { name: "Steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(7);
  await expect(steps.getByRole("heading")).toHaveText([
    "Set a password",
    "Enable two-factor",
    "Add Platforms and Accounts",
    "Connect or import",
    "Reconcile",
    "Resolve blockers",
    "Generate a report",
  ]);
  await expect(steps.nth(1)).toContainText("optional");
});

function step(key: string, overrides: object = {}) {
  return { key, done: false, optional: false, detail: `About ${key}.`, resolve_path: "/", ...overrides };
}

const HALFWAY = {
  complete: false,
  items: [
    step("password", { done: true, detail: "The Admin password is set.", resolve_path: "/setup" }),
    step("two_factor", { optional: true, resolve_path: "/settings/security" }),
    step("platforms_and_accounts", {
      detail: "No Platform yet — add each place that holds value, then an Account under it.",
      resolve_path: "/settings/platforms",
    }),
    step("connect_or_import", { resolve_path: "/imports" }),
    step("reconcile", { optional: true, resolve_path: "/settings/connections" }),
    step("blockers", { resolve_path: "/tax/overview" }),
    step("report", { resolve_path: "/tax/overview" }),
  ],
};

test("an open step says why and links to the screen that completes it", async ({ page }) => {
  await page.route("**/api/first-run-checklist", (route) => route.fulfill({ json: HALFWAY }));
  await page.goto("/first-run");

  await expect(page.getByRole("region", { name: "Progress" })).toContainText("1 / 5");
  const steps = page.getByRole("list", { name: "Steps" }).getByRole("listitem");
  // A done step offers nothing to do; the first open required step is next.
  await expect(steps.nth(0)).toContainText("done");
  await expect(steps.nth(0).getByRole("link")).toHaveCount(0);
  const next = steps.nth(2);
  await expect(next).toContainText("next");
  await expect(next).toContainText("No Platform yet");

  await next.getByRole("link", { name: "Open Platforms" }).click();

  await expect(page).toHaveURL(/\/settings\/platforms$/);
  await expect(page.getByRole("heading", { name: "Platforms", level: 1 })).toBeVisible();
});

test("every open step's link lands on a screen", async ({ page }) => {
  await page.route("**/api/first-run-checklist", (route) => route.fulfill({ json: HALFWAY }));
  await page.goto("/first-run");
  const steps = page.getByRole("list", { name: "Steps" }).getByRole("listitem");

  for (const [index, heading] of [
    [1, "Security"],
    [3, "Imports"],
    [4, "Connections"],
    [5, "Multi-year overview"],
    [6, "Multi-year overview"],
  ] as const) {
    await steps.nth(index).getByRole("link").first().click();
    await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await page.goBack();
  }
});

test("a finished walk says so and offers nothing more to do", async ({ page }) => {
  await page.route("**/api/first-run-checklist", (route) =>
    route.fulfill({
      json: {
        complete: true,
        items: HALFWAY.items.map((item) => ({ ...item, done: item.key !== "two_factor" })),
      },
    }),
  );
  await page.goto("/first-run");

  await expect(page.getByText("the walk is complete")).toBeVisible();
  // Two-factor stays offered: optional is not the same as done.
  await expect(page.getByRole("list", { name: "Steps" }).getByRole("link")).toHaveCount(1);
});

test("a checklist that cannot be loaded says what failed and offers a retry", async ({ page }) => {
  await page.route("**/api/first-run-checklist", (route) => route.fulfill({ status: 500, json: {} }));
  await page.goto("/first-run");

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("The first-run checklist could not be loaded");
  await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
});

const YEAR = {
  year: 2031,
  blockers: [],
  private_sales: null,
  other_income: null,
  capital_income: null,
};

test("a report is generated from the overview, and a refusal is shown in the API's words", async ({
  page,
}) => {
  let reports: object[] = [];
  let refuse = true;
  await page.route("**/api/multi-year-overview", (route) => route.fulfill({ json: { years: [YEAR] } }));
  await page.route("**/api/reports", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ json: reports });
    }
    if (refuse) {
      return route.fulfill({ status: 409, json: { detail: "No flat_rate is configured for 2031." } });
    }
    reports = [{ id: 9, year: 2031, status: "draft", generated_at: "2031-10-04T09:00:00Z", stale: false }];
    return route.fulfill({ status: 201, json: { id: 9 } });
  });
  await page.goto("/tax/overview");
  const row = page.getByRole("listitem", { name: "2031 report" });
  await expect(row).toContainText("No report yet");

  await row.getByRole("button", { name: "Generate report" }).click();
  await expect(page.getByRole("alert")).toContainText("No flat_rate is configured for 2031.");

  refuse = false;
  await row.getByRole("button", { name: "Generate report" }).click();

  await expect(page.getByRole("status").filter({ hasText: "2031 report was generated" })).toBeVisible();
  await expect(row).toContainText("Draft");
  await expect(row.getByRole("link", { name: "Appendix PDF" })).toHaveAttribute(
    "href",
    "/api/reports/9/appendix.pdf",
  );
});
