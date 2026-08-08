import { expect, test, type APIRequestContext } from "@playwright/test";

// Manual create, edit and delete, end to end from the UI (ticket 13). The
// ledger event exercised is a standalone fee in EUR: EUR is the one
// Instrument every database is born with — the migration chain mints it —
// while the Platform and Account are arranged over the API, tolerating an
// earlier run having left them behind.

async function arrangeAccount(request: APIRequestContext): Promise<void> {
  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Ledger", kind: "bank" },
  });
  let platformId: number;
  if (platform.status() === 201) {
    platformId = ((await platform.json()) as { id: number }).id;
  } else {
    const all = (await (await request.get("/api/platforms")).json()) as {
      id: number;
      name: string;
      kind: string;
    }[];
    platformId = all.find((entry) => entry.name === "E2E Ledger" && entry.kind === "bank")!.id;
  }
  await request.post(`/api/platforms/${platformId}/accounts`, { data: { name: "Fees" } });
}

test("the Admin records, revises and removes a Transaction end to end", async ({
  page,
  request,
}) => {
  await arrangeAccount(request);
  // A note only this run wrote, so every locator below is unambiguous even
  // beside leftovers of an interrupted earlier run.
  const note = `e2e fee ${Date.now()}`;

  await page.goto("/transactions");
  await page.getByRole("button", { name: "Record Transaction" }).click();

  const form = page.getByRole("form", { name: "Record a Transaction" });
  await form.getByLabel("Type").selectOption("fee");
  await form.getByLabel("Note").fill(note);
  await form.getByLabel("Account").selectOption({ label: "Fees" });
  await form.getByLabel("Instrument").selectOption({ label: "EUR — Euro" });
  await form.getByLabel("Quantity").fill("4.90");
  await form.getByRole("button", { name: "Record", exact: true }).click();

  const row = page.getByRole("row").filter({ hasText: note });
  await expect(row).toBeVisible();
  await expect(row.getByText("−4.90 EUR")).toBeVisible();

  await row.getByRole("button", { name: "Edit" }).click();
  const revision = page.getByRole("form", { name: "Revise the Transaction" });
  await revision.getByLabel("Quantity").fill("5.90");
  await revision.getByRole("button", { name: "Save revision" }).click();
  await expect(row.getByText("−5.90 EUR")).toBeVisible();

  // Removal asks once: the first press arms the button, the second acts.
  await row.getByRole("button", { name: "Remove" }).click();
  await row.getByRole("button", { name: "Confirm removal" }).click();
  await expect(page.getByRole("row").filter({ hasText: note })).toHaveCount(0);
});

test("the Admin records an Opening Balance and the ledger wears the estimated marker", async ({
  page,
  request,
}) => {
  // Both variants of ticket 15 through the browser's own controls: the form
  // opens on the date-known variant, the Admin reads why conservative dating
  // exists and picks it, and the recorded row can never pose as a real
  // movement. EUR is the only guaranteed Instrument, so it stands in; the
  // declaration under test is structural, not economic.
  await arrangeAccount(request);
  const note = `e2e opening balance ${Date.now()}`;

  await page.goto("/transactions");
  await page.getByRole("button", { name: "Record Transaction" }).click();

  const form = page.getByRole("form", { name: "Record a Transaction" });
  await form.getByLabel("Type").selectOption("opening_balance");
  await form.getByLabel("Note").fill(note);

  // The declaration section explains both variants and which figures the
  // choice affects; the instant's label follows the variant.
  const declaration = form.getByRole("group", { name: "What is reconstructed" });
  await expect(declaration.getByText("The date is used as given")).toBeVisible();
  await expect(declaration.getByText("genuinely unknown")).toBeVisible();
  await expect(form.getByLabel("Acquired at")).toBeVisible();
  await declaration.getByLabel("Date and basis both reconstructed").check();
  await expect(form.getByLabel("Known history begins at")).toBeVisible();
  await declaration.getByLabel("Estimated basis (EUR)").fill("120.50");

  await form.getByLabel("Account").selectOption({ label: "Fees" });
  await form.getByLabel("Instrument").selectOption({ label: "EUR — Euro" });
  await form.getByLabel("Quantity").fill("120.50");
  await form.getByRole("button", { name: "Record", exact: true }).click();

  const row = page.getByRole("row").filter({ hasText: note });
  await expect(row.getByText("date & basis reconstructed")).toBeVisible();
  await expect(row.getByText("est. €120.50")).toBeVisible();

  await row.getByRole("button", { name: "Remove" }).click();
  await row.getByRole("button", { name: "Confirm removal" }).click();
  await expect(page.getByRole("row").filter({ hasText: note })).toHaveCount(0);
});

test("the leg editor expresses more than two legs, with a fee charged against one", async ({
  page,
  request,
}) => {
  // The ticket's headline shape — both sides of a trade plus a fee as its
  // own attached leg — driven through the browser's own controls. EUR is the
  // only Instrument guaranteed here, so every leg wears it; the balance
  // under test is structural, not economic.
  await arrangeAccount(request);
  const note = `e2e trade ${Date.now()}`;

  await page.goto("/transactions");
  await page.getByRole("button", { name: "Record Transaction" }).click();

  const form = page.getByRole("form", { name: "Record a Transaction" });
  await form.getByLabel("Note").fill(note);
  for (const leg of ["Leg 1", "Leg 2"]) {
    const fieldset = form.getByRole("group", { name: leg });
    await fieldset.getByLabel("Account").selectOption({ label: "Fees" });
    await fieldset.getByLabel("Instrument").selectOption({ label: "EUR — Euro" });
    await fieldset.getByLabel("Quantity").fill("100.00");
  }
  await form.getByRole("button", { name: "Add leg" }).click();
  const fee = form.getByRole("group", { name: "Leg 3" });
  await fee.getByLabel("Account").selectOption({ label: "Fees" });
  await fee.getByLabel("Instrument").selectOption({ label: "EUR — Euro" });
  await fee.getByLabel("Quantity").fill("0.40");
  await fee.getByLabel("Charged against").selectOption({ label: "Leg 2 — EUR" });
  await form.getByRole("button", { name: "Record", exact: true }).click();

  const row = page.getByRole("row").filter({ hasText: note });
  await expect(row.getByText("−100.00 EUR")).toBeVisible();
  await expect(row.getByText("+100.00 EUR")).toBeVisible();
  await expect(row.getByText("−0.40 EUR")).toBeVisible();
  // Exact and lowercase: the microlabel's capitals are CSS text-transform,
  // and the "Fees" account name would otherwise match too.
  await expect(row.getByText("fee", { exact: true })).toBeVisible();

  await row.getByRole("button", { name: "Remove" }).click();
  await row.getByRole("button", { name: "Confirm removal" }).click();
  await expect(page.getByRole("row").filter({ hasText: note })).toHaveCount(0);
});
