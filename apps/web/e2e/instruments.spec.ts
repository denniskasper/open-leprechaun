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

// A token added by hand, arriving the way a refused sync sends the Admin: the
// symbol is already filled in, and the identity typed in any casing lands
// lowercased. A unique contract per run keeps the row unambiguous.
test("a token a sync could not resolve is added by hand", async ({ page }) => {
  const tail = String(Date.now()).slice(-10);
  const contract = `0xE2E${"0".repeat(27)}${tail}`;
  const symbol = `E2T${tail.slice(-5)}`;

  await page.goto(`/instruments?add=${symbol}`);
  const form = page.getByRole("region", { name: "Add coin or currency" });
  await expect(form.getByLabel("Symbol", { exact: true })).toHaveValue(symbol);

  await form.getByLabel("Name", { exact: true }).fill(`E2E Token ${tail}`);
  await form.getByLabel("Chain", { exact: true }).fill("Ethereum");
  // Too short for a hex address: named in place, and nothing can be sent.
  await form.getByLabel("Contract address", { exact: true }).fill("0xE2E");
  await expect(form.getByText(/40 hex characters/)).toBeVisible();
  await expect(form.getByRole("button", { name: "Add token" })).toBeDisabled();

  await form.getByLabel("Contract address", { exact: true }).fill(contract);
  await form.getByRole("button", { name: "Add token" }).click();

  await expect(form).toBeHidden();
  const row = page.getByRole("row", { name: new RegExp(symbol) });
  await expect(row.getByText(new RegExp(contract.toLowerCase().slice(-10)))).toBeVisible();
  await expect(row.getByText(/ethereum/)).toBeVisible();
});

// A symbol missing only as a cash movement's currency resolves in the cash
// family alone, so the sync's link names the kind and the form opens on it —
// added as a token it would leave the next sync refusing just the same.
test("a currency a sync could not resolve opens the form on Currency", async ({ page }) => {
  await page.goto("/instruments?add=ZZQ&kind=cash");
  const form = page.getByRole("region", { name: "Add coin or currency" });

  await expect(form.getByRole("button", { name: "Currency", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(form.getByLabel("Code", { exact: true })).toHaveValue("ZZQ");
  await expect(form.getByRole("button", { name: "Add currency" })).toBeVisible();
});

// A native coin's symbol is its identity: a second one is not a shared
// symbol to caution about but an Instrument that already exists, and the
// form says so before anything is sent. A token wearing the same symbol is
// still a second Instrument, allowed with the caution.
test("a native coin that already exists is named before submitting", async ({ page, request }) => {
  const symbol = `E2N${String(Date.now()).slice(-6)}`;
  const created = await request.post("/api/instruments", {
    data: { kind: "native", symbol, name: `E2E Coin ${symbol}`, chain: "e2e" },
  });
  expect(created.status()).toBe(201);

  await page.goto(`/instruments?add=${symbol}&kind=native`);
  const form = page.getByRole("region", { name: "Add coin or currency" });

  await expect(form.getByText(/already holds this identity/)).toBeVisible();
  await expect(form.getByText(/A second one is allowed/)).toBeHidden();
  await expect(form.getByRole("button", { name: "Add native coin" })).toBeDisabled();

  await form.getByRole("button", { name: "Token", exact: true }).click();
  await expect(form.getByText(/A second one is allowed/)).toBeVisible();
  await expect(form.getByText(/already holds this identity/)).toBeHidden();
});

// Every field's rule is held in the form, in the API's own words, so no
// refusal comes back as a sentence the form cannot place.
test("a two-letter peg and a blank name are refused in place", async ({ page }) => {
  await page.goto("/instruments?add=E2P");
  const form = page.getByRole("region", { name: "Add coin or currency" });

  await form.getByLabel("Pegged to (optional)").fill("US");
  await expect(form.getByText("A currency code is three letters, like USD.")).toBeVisible();
  await form.getByLabel("Name", { exact: true }).fill("   ");
  await expect(form.getByText("A name cannot be blank.")).toBeVisible();
  await expect(form.getByRole("button", { name: "Add token" })).toBeDisabled();

  await form.getByLabel("Pegged to (optional)").fill("USD");
  await form.getByLabel("Name", { exact: true }).fill("E2E Pegged");
  await expect(form.getByText(/three letters/)).toBeHidden();
  await expect(form.getByRole("button", { name: "Add token" })).toBeEnabled();
});
