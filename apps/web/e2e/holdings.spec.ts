import { expect, test, type APIRequestContext } from "@playwright/test";

// The Holdings view end to end (ticket 20). The position exercised is EUR
// cash from an Opening Balance: EUR is the one Instrument every database is
// born with, while the Platform and Account are arranged over the API. The
// Account name is unique per run, so every locator below is unambiguous even
// beside leftovers of an interrupted earlier run. The DisplayCurrency
// selector is asserted present but not switched — a foreign rate fetches
// from the live reference-rate source, which an offline run must not depend
// on.

async function arrange(request: APIRequestContext, accountName: string): Promise<void> {
  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Holdings", kind: "bank" },
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
    platformId = all.find((entry) => entry.name === "E2E Holdings" && entry.kind === "bank")!.id;
  }
  const account = await request.post(`/api/platforms/${platformId}/accounts`, {
    data: { name: accountName },
  });
  const accountId = ((await account.json()) as { id: number }).id;

  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    symbol: string;
    is_numeraire: boolean;
  }[];
  const eur = instruments.find((entry) => entry.is_numeraire)!.id;

  await request.post("/api/transactions", {
    data: {
      type: "opening_balance",
      occurred_at: "2026-01-05T12:00:00Z",
      note: `e2e holdings ${accountName}`,
      reconstructed: "basis",
      estimated_basis_eur: "500.00",
      legs: [{ account_id: accountId, instrument_id: eur, role: "in", quantity: "500.00" }],
    },
  });
}

test("the Admin sees a cash position, regrouped by Platform and by custody", async ({
  page,
  request,
}) => {
  const accountName = `Cash ${Date.now()}`;
  await arrange(request, accountName);

  await page.goto("/holdings");

  // Cash appears as its own line: the numéraire, valued by identity, located.
  const row = page.getByRole("row").filter({ hasText: accountName });
  await expect(row).toBeVisible();
  await expect(row.getByText("numéraire")).toBeVisible();
  await expect(row.getByText("€500.00")).toBeVisible();

  // Grouping is presentation: by Platform the group header names the venue…
  await page.getByLabel("Group by").selectOption("platform");
  await expect(page.getByRole("rowheader", { name: "E2E Holdings" })).toBeVisible();

  // …and by custody a bank Account files under third-party custody.
  await page.getByLabel("Group by").selectOption("custody");
  await expect(page.getByRole("rowheader", { name: "Third-party custody" })).toBeVisible();
  await expect(row).toBeVisible();

  // The DisplayCurrency selector is built here and defaults to EUR.
  await expect(page.getByLabel("Display currency")).toHaveValue("EUR");
});
