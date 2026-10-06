import { expect, test } from "@playwright/test";

// The Futures screen end to end. Position history is the ledger's own: a
// closed position entered over the API stands there with its net, and opens
// to say what it rests on. Open positions are whatever a venue states when
// asked — no venue is reachable from a test run, so its answer is supplied
// here, and what is under test is how the screen repeats it.
test("a closed position stands in the history with its net, and opens to its events", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const platform = await request.post("/api/platforms", {
    data: { name: `E2E Futures ${stamp}`, kind: "exchange" },
  });
  const account = await request.post(`/api/platforms/${(await platform.json()).id}/accounts`, {
    data: { name: "Contracts" },
  });
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    is_numeraire: boolean;
  }[];
  const symbol = `E2E${String(stamp).slice(-6)}-PERP`;
  const created = await request.post("/api/futures/positions", {
    data: {
      account_id: (await account.json()).id,
      symbol,
      side: "long",
      quantity: "2",
      settlement_instrument_id: instruments.find((entry) => entry.is_numeraire)!.id,
      opened_at: "2031-03-02T10:00:00Z",
      closed_at: "2031-03-04T10:00:00Z",
      realized: "120",
      fees: "3",
    },
  });
  expect(created.status()).toBe(201);

  await page.goto("/futures");
  await page.getByRole("tab", { name: /Position history/ }).click();
  const row = page.getByRole("row", { name: new RegExp(symbol) });
  // Result less fees: the net a close puts into its year.
  await expect(row.getByText("+117")).toBeVisible();
  await expect(row.getByText(/entered by hand/)).toBeVisible();

  await row.getByRole("button", { name: `Show the fills and funding of ${symbol}` }).click();
  await expect(page.getByText(/rests on no fills/)).toBeVisible();
});

test("an open position the ledger has no history for is marked", async ({ page }) => {
  await page.route("**/api/futures/live", (route) =>
    route.fulfill({
      json: [
        {
          connection_id: 1,
          connection_label: "E2E venue account",
          venue: "okx",
          adapter_kind: "futures",
          account_id: null,
          supported: true,
          error: null,
          stated_at: new Date().toISOString(),
          positions: [
            {
              symbol: "E2E-LIVE-PERP",
              side: "short",
              quantity: "5",
              quantity_unit: "ETH",
              notional_usd: "10000",
              leverage: "3",
              margin_mode: "isolated",
              entry_price: "2000",
              mark_price: "2100",
              liquidation_price: null,
              breakeven_price: "1998",
              floating_result: "-500",
              floating_result_ratio: "-0.15",
              margin: "40",
              margin_ratio: "2.5",
              settlement_symbol: "USDT",
              ledger_position_id: null,
            },
          ],
        },
      ],
    }),
  );

  await page.goto("/futures");
  const row = page.getByRole("row", { name: /E2E-LIVE-PERP/ });
  await expect(row.getByText(/Not in the ledger/)).toBeVisible();
  // The direction is in the figure itself, never left to colour.
  await expect(row.getByText("−500 USDT")).toBeVisible();
  await expect(row.getByText("−15.00%")).toBeVisible();
  // A figure the venue left unstated is not turned into a zero.
  await expect(row.getByText("250.00%")).toBeVisible();
  // Every amount carries what it is an amount of, the margin its mode.
  const margin = row.getByRole("cell").last();
  await expect(margin).toContainText("40 USDT");
  await expect(margin).toContainText("isolated");
  // The statement says when the venue was asked.
  await expect(page.getByRole("region", { name: "E2E venue account" })).toContainText(
    /stated at/,
  );
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();
});

test("a venue that refuses is an error of its own, with a way to ask again", async ({ page }) => {
  let asked = 0;
  await page.route("**/api/futures/live", (route) => {
    asked += 1;
    return route.fulfill({
      json: [
        {
          connection_id: 1,
          connection_label: "E2E refusing venue",
          venue: "okx",
          adapter_kind: "futures",
          account_id: null,
          supported: true,
          error: "The key was revoked.",
          stated_at: null,
          positions: [],
        },
      ],
    });
  });

  await page.goto("/futures");
  const venue = page.getByRole("region", { name: "E2E refusing venue" });
  await expect(venue.getByRole("alert")).toContainText("The key was revoked.");

  await venue.getByRole("button", { name: /again|Retry/i }).click();
  await expect.poll(() => asked).toBeGreaterThan(1);
  // The ledger's own history never depended on the venue.
  await expect(page.getByRole("tab", { name: /Position history/ })).toBeEnabled();
});

test("what is unresolved shows even with no position and no venue, and is absent otherwise", async ({
  page,
}) => {
  await page.route("**/api/futures/live", (route) => route.fulfill({ json: [] }));
  const unattributable = [1, 2].map((id) => ({
    id,
    source: "okx:futures",
    account_id: 1,
    symbol: "E2E-STRAY-PERP",
    amount: "-0.5",
    settlement_instrument_id: 1,
    settlement_symbol: "USDC",
    occurred_at: `2031-03-0${id}T08:00:00Z`,
    position_side: null,
  }));
  let funding = unattributable;
  await page.route("**/api/futures", (route) =>
    route.fulfill({
      json: { positions: [], unattributable_funding: funding, derivation_issues: [] },
    }),
  );

  await page.goto("/futures");
  const unresolved = page.getByRole("region", { name: "Unresolved" });
  // Two payments on one symbol are one line: how many, and their total.
  await expect(unresolved).toContainText("E2E-STRAY-PERP");
  await expect(unresolved).toContainText("2 funding payments");
  await expect(unresolved).toContainText("−1 USDC");
  await expect(page.getByText("No futures yet")).toBeHidden();

  funding = [];
  await page.reload();
  await expect(page.getByText("No futures yet")).toBeVisible();
  await expect(unresolved).toBeHidden();
});

test("on a narrow screen the table scrolls sideways under a pinned symbol", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    is_numeraire: boolean;
  }[];
  const stamp = Date.now();
  const platform = await request.post("/api/platforms", {
    data: { name: `E2E Narrow ${stamp}`, kind: "exchange" },
  });
  const account = await request.post(`/api/platforms/${(await platform.json()).id}/accounts`, {
    data: { name: "Contracts" },
  });
  await request.post("/api/futures/positions", {
    data: {
      account_id: (await account.json()).id,
      symbol: `E2N${String(stamp).slice(-6)}-PERP`,
      side: "short",
      quantity: "1",
      settlement_instrument_id: instruments.find((entry) => entry.is_numeraire)!.id,
      opened_at: "2031-03-02T10:00:00Z",
      closed_at: "2031-03-04T10:00:00Z",
      realized: "-20",
      fees: "1",
    },
  });

  await page.goto("/futures");
  await page.getByRole("tab", { name: /Position history/ }).click();
  const table = page.getByRole("table").first();
  await expect(table).toBeVisible();
  const scroller = table.locator("xpath=..");
  const overflows = await scroller.evaluate((el) => el.scrollWidth > el.clientWidth);
  expect(overflows).toBe(true);
  // The page itself does not scroll sideways — only the table does.
  const pageOverflows = await page
    .locator("html")
    .evaluate((el) => el.scrollWidth > el.clientWidth);
  expect(pageOverflows).toBe(false);
});
