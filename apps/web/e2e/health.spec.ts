import { expect, test } from "@playwright/test";

// The walking skeleton's whole claim, asserted end to end: Postgres answers the
// API, the API answers the browser, and the browser puts it on screen.
test("the browser shows that the API answered and its database is reachable", async ({ page }) => {
  await page.goto("/");

  const readout = page.getByRole("region", { name: /operational/i });

  await expect(readout).toBeVisible();
  await expect(readout.getByText("/api/health")).toBeVisible();
  await expect(readout.getByText("ok", { exact: true })).toBeVisible();
  await expect(readout.getByText("up", { exact: true })).toBeVisible();
});
