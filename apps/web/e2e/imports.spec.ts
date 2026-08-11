import { expect, test, type APIRequestContext } from "@playwright/test";

// The import framework end to end from the UI (ticket 31): a batch committed
// over the API appears on the Imports screen and its rows wear the imported
// marker in the ledger; a bulk re-type marks them overridden by hand; the
// reversal removes the batch as a unit. Each run works in its own Account
// under its own source, so leftovers of an interrupted earlier run cannot
// collide with the registry's deduplication key.

async function arrangeAccount(request: APIRequestContext, name: string): Promise<number> {
  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Imports", kind: "exchange" },
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
    platformId = all.find((entry) => entry.name === "E2E Imports" && entry.kind === "exchange")!.id;
  }
  const account = await request.post(`/api/platforms/${platformId}/accounts`, {
    data: { name },
  });
  return ((await account.json()) as { id: number }).id;
}

test("a wallet's exported file previews before it writes and commits as one batch", async ({
  page,
  request,
}) => {
  // The BitBox connector reads the seeded BTC; without it the journey cannot
  // resolve the file's symbol — consistent with how the transfers journey
  // treats a missing seed.
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    symbol: string;
    family: string;
  }[];
  test.skip(
    !instruments.some((entry) => entry.symbol === "BTC" && entry.family === "crypto"),
    "The seeded BTC Instrument is missing.",
  );

  const run = Date.now();
  await arrangeAccount(request, `CSV ${run}`);

  // A real BitBoxApp export: local-time timestamps without an offset,
  // amounts in satoshi, one unconfirmed row the connector must name.
  const exported = [
    "Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note",
    `7/26/25 21:51,received,2500000,satoshi,,,bc1qa,tx-${run}-a,First deposit`,
    `7/27/25 09:10,received,1000000,satoshi,,,bc1qa,tx-${run}-b,`,
    `,received,999,satoshi,,,bc1qa,tx-${run}-pending,`,
    "",
  ].join("\n");

  await page.goto("/imports");
  await page.getByRole("button", { name: "Import a file" }).click();
  const panel = page.getByRole("region", { name: "Import a file" });
  await panel.getByLabel("Connector").selectOption({ label: "BitBox" });
  await panel.getByLabel("Into Account").selectOption({ label: `CSV ${run}` });

  // The connector declares its file and its venue's clock before anything is parsed.
  await expect(panel.getByText("BitBoxApp")).toBeVisible();
  await expect(
    panel.getByText("Bare timestamps are read as Europe/Berlin time and converted to UTC."),
  ).toBeVisible();

  await panel.getByLabel("Exported file").setInputFiles({
    name: `bitbox-${run}.csv`,
    mimeType: "text/csv",
    buffer: Buffer.from(exported),
  });

  // The preview names what would land and what the connector left out —
  // before any of it exists.
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel.getByText("2 rows to create")).toBeVisible();
  await expect(panel.getByText("1 unconfirmed transaction left out — not facts yet.")).toBeVisible();

  // Committing is its own act; the batch appears with the file's own name
  // and its per-Account provenance.
  await panel.getByRole("button", { name: "Commit import" }).click();
  await expect(panel.getByText("2 rows created")).toBeVisible();
  const batch = page.getByRole("row").filter({ hasText: `bitbox-${run}.csv` });
  await expect(batch.getByText("2 rows")).toBeVisible();
  await expect(batch.getByText(/^bitbox:\d+$/)).toBeVisible();

  // Leave the ledger as found: reversal removes the batch as a unit.
  await batch.getByRole("button", { name: "Reverse" }).click();
  await batch.getByRole("button", { name: "Confirm reversal" }).click();
  await expect(page.getByRole("row").filter({ hasText: `bitbox-${run}.csv` })).toHaveCount(0);
});

test("an import lands as a reversible batch whose rows wear their provenance", async ({
  page,
  request,
}) => {
  const run = Date.now();
  const account = await arrangeAccount(request, `Run ${run}`);
  const eur = (
    (await (await request.get("/api/instruments")).json()) as { id: number; symbol: string }[]
  ).find((instrument) => instrument.symbol === "EUR")!.id;

  const committed = await request.post("/api/imports", {
    data: {
      source: `e2e-csv-${run}`,
      label: `statement-${run}.csv`,
      account_id: account,
      rows: [
        {
          external_id: "row-1",
          type: "transfer_in",
          occurred_at: "2026-03-14T12:00:00Z",
          legs: [{ role: "in", quantity: "25.00", instrument_id: eur }],
        },
      ],
    },
  });
  expect(committed.status()).toBe(201);

  // The ledger row wears the imported marker with its source.
  await page.goto("/transactions");
  const row = page.getByRole("row").filter({ hasText: `e2e-csv-${run}` });
  await expect(row.getByText(`imported · e2e-csv-${run}`)).toBeVisible();

  // A bulk re-type through the toolbar: the row changes type and is marked
  // overridden by hand — the Admin's now, so a re-import will not revert it.
  await row.getByRole("checkbox").check();
  const toolbar = page.getByRole("group", { name: "Bulk repair" });
  await toolbar.getByLabel("Re-type as").selectOption("staking_reward");
  await toolbar.getByRole("button", { name: "Re-type" }).click();
  await expect(row.getByText("Staking reward")).toBeVisible();
  await expect(row.getByText("overridden by hand")).toBeVisible();

  // The batch stands on the Imports screen; reversal asks once, then removes
  // it — and the overridden row, the Admin's own now, survives it.
  await page.goto("/imports");
  const batch = page.getByRole("row").filter({ hasText: `statement-${run}.csv` });
  await expect(batch.getByText("1 row · 1 overridden")).toBeVisible();
  await batch.getByRole("button", { name: "Reverse" }).click();
  await batch.getByRole("button", { name: "Confirm reversal" }).click();
  await expect(page.getByRole("row").filter({ hasText: `statement-${run}.csv` })).toHaveCount(0);

  await page.goto("/transactions");
  const survivor = page.getByRole("row").filter({ hasText: `e2e-csv-${run}` });
  await expect(survivor.getByText("overridden by hand")).toBeVisible();

  // Leave the ledger as found: remove the surviving overridden row.
  await survivor.getByRole("button", { name: "Remove" }).click();
  await survivor.getByRole("button", { name: "Confirm removal" }).click();
  await expect(page.getByRole("row").filter({ hasText: `e2e-csv-${run}` })).toHaveCount(0);
});
