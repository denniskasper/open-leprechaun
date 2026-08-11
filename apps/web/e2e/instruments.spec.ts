import { expect, test } from "@playwright/test";

// The Instruments screen's ticket-44 surface, end to end: a fund created
// over the API stands unclassified and unpriced, and the Admin classifies it
// inline — the category then wears its source. The fund is created with a
// unique ISIN per run so every locator is unambiguous beside leftovers of an
// interrupted earlier run. The add-security search is not exercised here: it
// reaches the live provider, which an offline run must not depend on.
test("an unclassified fund is classified inline, its source shown", async ({ page, request }) => {
  const isin = `ZZ${String(Date.now()).slice(-9)}0`;
  const created = await request.post("/api/securities", {
    data: { isin, name: `E2E Fund ${isin}`, symbol: `EF${isin.slice(-4)}`, type: "fund" },
  });
  expect(created.status()).toBe(201);

  await page.goto("/instruments");
  const row = page.getByRole("row", { name: new RegExp(isin) });
  // Nothing prices a security yet — an unknown value, never zero.
  await expect(row.getByText("unpriced")).toBeVisible();

  await row.getByRole("button", { name: "Classify" }).click();
  await page.getByLabel("Teilfreistellung").selectOption("aktienfonds");
  await page.getByLabel("Distribution policy").selectOption("accumulating");
  await page.getByRole("button", { name: "Save classification" }).click();

  await expect(row.getByText(/Aktienfonds/)).toBeVisible();
  // The source of the value is shown — this one the Admin stated.
  await expect(row.getByText("admin")).toBeVisible();
});
