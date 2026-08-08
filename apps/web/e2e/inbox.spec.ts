import { expect, test, type APIRequestContext } from "@playwright/test";

// Classifying an unacknowledged arrival end to end (ticket 14). Instruments
// are minted by the seed or by imports, never by the API, and the numéraire
// EUR is exempt from stance — so this flow rides on the seed's USD and skips
// where a database was never seeded. Platform and Account are arranged over
// the API, tolerating an earlier run having left them behind.

interface Arranged {
  instrumentId: number;
  accountId: number;
}

async function arrange(request: APIRequestContext): Promise<Arranged | null> {
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    symbol: string;
    family: string;
  }[];
  const usd = instruments.find((entry) => entry.symbol === "USD" && entry.family === "cash");
  if (!usd) {
    return null;
  }

  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Inbox", kind: "software_wallet" },
  });
  let platformId: number;
  if (platform.status() === 201) {
    platformId = ((await platform.json()) as { id: number }).id;
  } else {
    const all = (await (await request.get("/api/platforms")).json()) as {
      id: number;
      name: string;
    }[];
    platformId = all.find((entry) => entry.name === "E2E Inbox")!.id;
  }
  await request.post(`/api/platforms/${platformId}/accounts`, { data: { name: "Sprayed" } });
  const withAccounts = (await (await request.get("/api/platforms")).json()) as {
    id: number;
    accounts: { id: number; name: string }[];
  }[];
  const accountId = withAccounts
    .find((entry) => entry.id === platformId)!
    .accounts.find((account) => account.name === "Sprayed")!.id;

  // An earlier run may have left a kept stance behind, which would keep the
  // fresh arrival out of the inbox; returning the pair to unacknowledged is
  // part of arranging, and 404 just means there was nothing to clear.
  await request.delete(`/api/instruments/${usd.id}/stance?account_id=${accountId}`);
  return { instrumentId: usd.id, accountId };
}

test("the Admin keeps an unsolicited arrival, the question defaulting to no", async ({
  page,
  request,
}) => {
  const arranged = await arrange(request);
  test.skip(arranged === null, "Needs the seeded USD Instrument; EUR is exempt from stance.");
  const { instrumentId, accountId } = arranged!;

  // A note only this run wrote, so the ledger locator below is unambiguous
  // even beside leftovers of an interrupted earlier run.
  const note = `e2e arrival ${Date.now()}`;
  const inflow = await request.post("/api/transactions", {
    data: {
      type: "transfer_in",
      occurred_at: new Date().toISOString(),
      note,
      legs: [
        { account_id: accountId, instrument_id: instrumentId, role: "in", quantity: "12.34" },
      ],
    },
  });
  const transactionId = ((await inflow.json()) as { id: number }).id;

  await page.goto("/inbox");
  const item = page.getByRole("listitem").filter({ hasText: "E2E Inbox · Sprayed" });
  await expect(item.getByText("unacknowledged", { exact: true })).toBeVisible();

  await item.getByRole("button", { name: "Keep", exact: true }).click();
  const form = item.getByRole("form", { name: /Keep USD/ });
  // The counter-performance question defaults to no.
  await expect(form.getByLabel(/No — a windfall/)).toBeChecked();
  await form.getByRole("button", { name: "Keep at Sprayed" }).click();

  // The pair leaves the inbox, and the inflow settled as a windfall.
  await expect(item).toHaveCount(0);
  await page.goto("/transactions");
  const row = page.getByRole("row").filter({ hasText: note });
  await expect(row.getByText("Windfall")).toBeVisible();
  await expect(row.getByText("+12.34 USD")).toBeVisible();

  // Leave the database as found: the settled event and the stance both go.
  await request.delete(`/api/transactions/${transactionId}`);
  await request.delete(`/api/instruments/${instrumentId}/stance?account_id=${accountId}`);
});
