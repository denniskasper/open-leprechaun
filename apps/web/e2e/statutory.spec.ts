import { expect, test } from "@playwright/test";

// The statutory configuration store, end to end from the UI (ticket 09): the
// migration-carried deliverable year is complete with its sources shown, and
// entering, correcting and unsetting a value works through the browser's own
// controls. The year exercised is 2030 — one no migration seeds — and the
// spec unsets what it set, so a re-run meets the store it expects.

test("the deliverable year arrives complete, with every value citing its source", async ({
  page,
}) => {
  await page.goto("/settings/statutory");

  const year = page.getByRole("region", { name: "Statutory values 2026" });
  await expect(year.getByText("complete")).toBeVisible();
  await expect(year.getByText("25 %", { exact: true })).toBeVisible();
  await expect(year.getByText("§ 32d Abs. 1 Satz 1 EStG")).toBeVisible();
  await expect(year.getByText("BMF-Schreiben v. 13.01.2026 (Basiszins zum 2.1.2026)")).toBeVisible();
});

test("the Admin adds a year, enters a value, is refused a percentage, and unsets it", async ({
  page,
}) => {
  await page.goto("/settings/statutory");

  await page.getByRole("button", { name: "Add year" }).click();
  const addForm = page.getByRole("form", { name: "Add a year" });
  await addForm.getByLabel("Year").fill("2030");
  await addForm.getByRole("button", { name: "Add", exact: true }).click();

  const year = page.getByRole("region", { name: "Statutory values 2030" });
  await expect(year.getByText(/required values unset/)).toBeVisible();

  const row = year.getByRole("article", { name: "Abgeltungsteuer rate 2030" });
  await row.getByRole("button", { name: "Set" }).click();
  const form = page.getByRole("form", { name: "Set Abgeltungsteuer rate for 2030" });

  // A percentage where a fraction belongs: "25" passes the input's decimal
  // pattern, so the refusal is the API's own sentence, surfaced verbatim.
  await form.getByLabel(/Value/).fill("25");
  await form.getByLabel("Source").fill("e2e: § 32d Abs. 1 Satz 1 EStG");
  await form.getByRole("button", { name: "Store" }).click();
  await expect(form.getByRole("alert")).toContainText("0.25");

  await form.getByLabel(/Value/).fill("0.25");
  await form.getByRole("button", { name: "Store" }).click();
  await expect(row.getByText("25 %", { exact: true })).toBeVisible();
  await expect(row.getByText("e2e: § 32d Abs. 1 Satz 1 EStG")).toBeVisible();

  // Unset it again so the store returns to the state a re-run expects.
  await row.getByRole("button", { name: "Edit" }).click();
  await page
    .getByRole("form", { name: "Correct Abgeltungsteuer rate for 2030" })
    .getByRole("button", { name: "Unset" })
    .click();
  await expect(row.getByText("not set", { exact: true })).toBeVisible();
});

test("the elections change and survive a reload", async ({ page }) => {
  await page.goto("/settings/statutory");

  const elections = page.getByRole("region", { name: "Elections" });
  await elections.getByLabel("Filing status").selectOption({ label: "Married, filing jointly" });
  await expect(elections.getByLabel("Filing status")).toHaveValue("joint");

  await page.reload();
  await expect(elections.getByLabel("Filing status")).toHaveValue("joint");

  // Back to the default, so a re-run meets the election it expects.
  await elections.getByLabel("Filing status").selectOption({ label: "Single" });
  await expect(elections.getByLabel("Filing status")).toHaveValue("single");
});
