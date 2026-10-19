import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The promise of the frame (docs/agents/design.md, "Tables"), held on every
// screen that draws a table: the page never scrolls sideways, from a 1440px
// window up no table does either, and where a narrow window makes one scroll
// its first column stays pinned. Each screen is arranged so its tables are
// actually drawn — a screen showing its empty state would pass by default.
// What only a venue or the tax engine could state is supplied here, with
// figures and names as long as real ones run.

async function arrangePlatform(request: APIRequestContext): Promise<number> {
  const created = await request.post("/api/platforms", {
    data: { name: `E2E Tables ${randomUUID()}`, kind: "exchange" },
  });
  return ((await created.json()) as { id: number }).id;
}

async function arrangeAccount(request: APIRequestContext): Promise<number> {
  const platformId = await arrangePlatform(request);
  const account = await request.post(`/api/platforms/${platformId}/accounts`, {
    data: { name: "Spot and derivatives" },
  });
  return ((await account.json()) as { id: number }).id;
}

async function numeraire(request: APIRequestContext): Promise<number> {
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    is_numeraire: boolean;
  }[];
  return instruments.find((entry) => entry.is_numeraire)!.id;
}

async function arrangeCash(request: APIRequestContext): Promise<void> {
  const account = await arrangeAccount(request);
  await request.post("/api/transactions", {
    data: {
      type: "opening_balance",
      occurred_at: "2031-01-05T12:00:00Z",
      note: "e2e tables",
      reconstructed: "basis",
      estimated_basis_eur: "1250.00",
      legs: [
        {
          account_id: account,
          instrument_id: await numeraire(request),
          role: "in",
          quantity: "1250.00",
        },
      ],
    },
  });
}

const POT = {
  carryforward_in_eur: "1834.27",
  carryforward_in: [
    { origin_year: 2028, amount_eur: "1034.27", opening: true },
    { origin_year: 2029, amount_eur: "800.00", opening: false },
  ],
  consumed_eur: "612.40",
  consumed: [{ origin_year: 2028, amount_eur: "612.40", opening: true }],
  produced_eur: "0",
  carryforward_out_eur: "1221.87",
  carryforward_out: [
    { origin_year: 2028, amount_eur: "421.87", opening: true },
    { origin_year: 2029, amount_eur: "800.00", opening: false },
  ],
};

function regimeYear(taxable: string) {
  return {
    gross_eur: "48213.55",
    offsets_eur: "-12904.18",
    allowance_limit_eur: "1000.00",
    allowance_eur: "1000.00",
    taxable_eur: taxable,
    tax_eur: null,
  };
}

const OVERVIEW = {
  years: [2031, 2032, 2033].map((year) => ({
    year,
    blockers: [],
    private_sales: regimeYear("34309.37"),
    other_income: regimeYear("2210.00"),
    capital_income: {
      ...regimeYear("18120.45"),
      categories: [
        { category: "aktien", ...POT },
        { category: "sonstige", ...POT },
        { category: "termingeschaefte", ...POT },
      ],
    },
  })),
};

const LIVE = [
  {
    connection_id: 1,
    connection_label: "E2E tables venue account",
    venue: "okx",
    adapter_kind: "futures",
    account_id: null,
    supported: true,
    error: null,
    stated_at: "2031-03-04T10:00:00Z",
    positions: [
      {
        symbol: "E2E-TABLES-USDT-SWAP",
        side: "short",
        quantity: "1250.5",
        quantity_unit: "ETH",
        notional_usd: "2501234.56",
        leverage: "12.5",
        margin_mode: "isolated",
        entry_price: "2000.12",
        mark_price: "2100.45",
        liquidation_price: "2390.88",
        breakeven_price: "1998.07",
        floating_result: "-125412.33",
        floating_result_ratio: "-0.1542",
        margin: "200098.77",
        margin_ratio: "2.5",
        settlement_symbol: "USDT",
        ledger_position_id: null,
      },
    ],
  },
];

const EVENTS = {
  fills: [1, 2, 3].map((id) => ({
    id,
    side: id === 3 ? "sell" : "buy",
    price: "2000.1234",
    size: "416.8333",
    fee: "-41.2087",
    realized: id === 3 ? "12542.10" : null,
    occurred_at: `2031-03-0${id + 1}T10:00:00Z`,
  })),
  funding: [1, 2, 3, 4].map((id) => ({
    id,
    amount: "-18.4471",
    occurred_at: `2031-03-02T0${id * 2}:00:00Z`,
  })),
};

const CONNECTION = (platformId: number) => ({
  id: 9001,
  platform_id: platformId,
  venue: "okx",
  label: "E2E tables reconciled account",
  fingerprint: "e2e…f00d",
  last_used_at: null,
  statuses: [],
  pairings: [],
});

const RECONCILIATION = [
  {
    adapter_kind: "spot",
    ok: true,
    error: null,
    account_id: null,
    as_of: "2031-03-04T10:00:00Z",
    tolerance: "0.00000001",
    lines: [
      {
        instrument_id: 1,
        symbol: "BTC",
        name: "Bitcoin",
        family: "crypto",
        live: "1.23456789",
        tracked: "1.20000000",
        difference: "0.03456789",
        status: "gap",
        resolutions: ["import_history"],
        detail: null,
      },
      {
        instrument_id: 2,
        symbol: "USDT",
        name: "Tether USD",
        family: "crypto",
        live: "15000.5",
        tracked: "15000.5",
        difference: "0",
        status: "matched",
        resolutions: [],
        detail: null,
      },
    ],
  },
];

const INTERPRETATION = {
  columns: ["Date", "Kind", "Asset", "Amount", "Fee", "Comment"],
  rows: [1, 2, 3].map((number) => ({
    number,
    external_id: `row-${number}`,
    occurred_at: `2031-03-0${number}T10:00:00Z`,
    type: "trade",
    symbol: "E2E-LONG-SYMBOL",
    quantity: "12345.67890123",
    fee_quantity: "0.00012345",
    note: null,
    left_out: number === 3 ? "a row the venue marked as cancelled" : null,
    problems: [],
  })),
  row_count: 3,
  defects: ["No column is chosen for the timestamp."],
  type_values_seen: [],
};

type Screen = {
  name: string;
  path: string;
  /** What the screen needs before its tables are drawn. */
  arrange?: (page: Page, request: APIRequestContext) => Promise<unknown>;
  /** What to open once loaded, so every table is in view. */
  open?: (page: Page) => Promise<unknown>;
  /** Few columns: each table stays narrower than the column at 1440px. */
  compact?: true;
  /** Wide enough that a phone has to scroll some table sideways. */
  wide?: true;
};

const SCREENS: Screen[] = [
  {
    name: "Holdings",
    path: "/holdings",
    arrange: (_page, request) => arrangeCash(request),
    wide: true,
  },
  {
    name: "Transactions",
    path: "/transactions",
    arrange: (_page, request) => arrangeCash(request),
    wide: true,
  },
  { name: "Instruments", path: "/instruments", wide: true },
  {
    name: "Import batches",
    path: "/imports",
    arrange: async (_page, request) => {
      const run = Date.now();
      await request.post("/api/imports", {
        data: {
          source: `e2e-tables-${run}`,
          label: `a-long-statement-export-named-by-its-venue-${run}.csv`,
          account_id: await arrangeAccount(request),
          rows: [
            {
              external_id: "row-1",
              type: "transfer_in",
              occurred_at: "2031-03-14T12:00:00Z",
              legs: [{ role: "in", quantity: "25.00", instrument_id: await numeraire(request) }],
            },
          ],
        },
      });
    },
  },
  {
    name: "A mapped file's rows",
    path: "/imports",
    arrange: (page) =>
      page.route("**/api/column-mappings/interpret", (route) =>
        route.fulfill({ json: INTERPRETATION }),
      ),
    open: async (page) => {
      await page.getByRole("button", { name: "Map a file" }).click();
      await page
        .getByRole("region", { name: "Map a file" })
        .getByLabel("Exported file")
        .setInputFiles({
          name: "e2e-tables.csv",
          mimeType: "text/csv",
          buffer: Buffer.from("Date,Kind,Asset,Amount,Fee,Comment\n"),
        });
      await expect(page.getByRole("table")).toHaveCount(2);
    },
  },
  {
    name: "Portfolio points",
    path: "/portfolio",
    arrange: async (_page, request) => {
      await arrangeCash(request);
      await request.post("/api/scheduled-tasks/portfolio_snapshot/run");
    },
    open: (page) => page.getByText(/points as a table/).click(),
  },
  {
    name: "Multi-year overview",
    path: "/tax/overview",
    arrange: (page) =>
      page.route("**/api/multi-year-overview", (route) => route.fulfill({ json: OVERVIEW })),
    compact: true,
  },
  {
    name: "Open futures positions",
    path: "/futures",
    arrange: (page) => page.route("**/api/futures/live", (route) => route.fulfill({ json: LIVE })),
    wide: true,
  },
  {
    name: "Futures history, fills and funding",
    path: "/futures",
    arrange: async (page, request) => {
      await page.route("**/api/futures/live", (route) => route.fulfill({ json: [] }));
      await page.route("**/api/futures/positions/*/events", (route) =>
        route.fulfill({ json: EVENTS }),
      );
      const stamp = Date.now();
      await request.post("/api/futures/positions", {
        data: {
          account_id: await arrangeAccount(request),
          symbol: `E2T${String(stamp).slice(-6)}-USDT-SWAP`,
          side: "long",
          quantity: "1250.5",
          settlement_instrument_id: await numeraire(request),
          opened_at: "2031-03-02T10:00:00Z",
          closed_at: "2031-03-04T10:00:00Z",
          realized: "125412.33",
          fees: "4120.87",
        },
      });
    },
    open: async (page) => {
      await page.getByRole("tab", { name: /Position history/ }).click();
      await page
        .getByRole("button", { name: /^Show the fills and funding of E2T/ })
        .first()
        .click();
      await expect(page.getByRole("group", { name: "Funding payments" })).toBeVisible();
    },
    wide: true,
  },
  {
    name: "Connection reconciliation",
    path: "/settings/connections",
    arrange: async (page, request) => {
      const platformId = await arrangePlatform(request);
      await page.route("**/api/connections", (route) =>
        route.fulfill({ json: [CONNECTION(platformId)] }),
      );
      await page.route("**/api/connections/9001/reconcile", (route) =>
        route.fulfill({ json: RECONCILIATION }),
      );
    },
    open: (page) => page.getByRole("button", { name: "Reconcile", exact: true }).click(),
    compact: true,
  },
];

/** How far the page itself scrolls sideways. */
function pageOverflow(page: Page): Promise<number> {
  return page.locator("html").evaluate((html) => html.scrollWidth - html.clientWidth);
}

/** How far each table's frame scrolls sideways — zero where it shows every column. */
function tableOverflows(page: Page): Promise<number[]> {
  return page
    .locator("#content table")
    .evaluateAll((tables) =>
      tables.map((table) => table.parentElement!.scrollWidth - table.parentElement!.clientWidth),
    );
}

/** How much of the column each table leaves free: more than none where it fits its content. */
function tableSlack(page: Page): Promise<number[]> {
  return page
    .locator("#content table")
    .evaluateAll((tables) =>
      tables.map(
        (table) => table.parentElement!.clientWidth - table.getBoundingClientRect().width,
      ),
    );
}

/**
 * Each frame that scrolls, scrolled to its far end: how far every row's first
 * cell then sits from the frame's left edge. A pinned column sits at zero.
 */
function pinnedOffsets(page: Page): Promise<number[]> {
  return page.locator("#content table").evaluateAll((tables) =>
    tables.flatMap((table) => {
      const frame = table.parentElement!;
      if (frame.scrollWidth <= frame.clientWidth) return [];
      frame.scrollLeft = frame.scrollWidth;
      const left = frame.getBoundingClientRect().left;
      return [...table.querySelectorAll(":scope > * > tr > :first-child:not([colspan])")].map(
        (cell) => Math.round(cell.getBoundingClientRect().left - left),
      );
    }),
  );
}

for (const screen of SCREENS) {
  for (const width of [1440, 390]) {
    test(`${screen.name} holds its tables at ${width}px`, async ({ page, request }) => {
      await page.setViewportSize({ width, height: 900 });
      await screen.arrange?.(page, request);
      await page.goto(screen.path);
      await expect(page.locator("#content").getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await screen.open?.(page);
      await expect(page.locator("#content table").first()).toBeVisible();

      expect(await pageOverflow(page)).toBe(0);
      if (width >= 1440) {
        for (const overflow of await tableOverflows(page)) {
          expect(overflow).toBe(0);
        }
        if (screen.compact) {
          for (const slack of await tableSlack(page)) {
            expect(slack).toBeGreaterThan(0);
          }
        }
      } else {
        if (screen.wide) {
          expect(Math.max(...(await tableOverflows(page)))).toBeGreaterThan(0);
        }
        for (const offset of await pinnedOffsets(page)) {
          expect(offset).toBe(0);
        }
        // Scrolling a frame never moves the page.
        expect(await pageOverflow(page)).toBe(0);
      }
    });
  }
}
