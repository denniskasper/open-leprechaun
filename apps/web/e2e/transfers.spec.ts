import { expect, test, type APIRequestContext } from "@playwright/test";

// Self-transfer matching (ticket 16) through the real browser: the app
// proposes the candidate pair, the Admin confirms it, the link shows as a
// confirmed self-transfer, and unlinking returns both sides to visibly
// unmatched. The transfers are arranged over the API on the seeded BTC —
// EUR, the one Instrument every database is born with, is the numéraire and
// never awaits a match — so the spec skips on an unseeded database.

interface Arranged {
  hotAccountId: number;
  coldAccountId: number;
  btcId: number;
}

async function arrange(request: APIRequestContext): Promise<Arranged | null> {
  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    symbol: string;
    family: string;
  }[];
  const btc = instruments.find((entry) => entry.symbol === "BTC" && entry.family === "crypto");
  if (!btc) {
    return null;
  }
  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Transfers", kind: "exchange" },
  });
  let platformId: number;
  if (platform.status() === 201) {
    platformId = ((await platform.json()) as { id: number }).id;
  } else {
    const all = (await (await request.get("/api/platforms")).json()) as {
      id: number;
      name: string;
    }[];
    platformId = all.find((entry) => entry.name === "E2E Transfers")!.id;
  }
  for (const name of ["Hot", "Cold"]) {
    // Tolerate a 409 from an earlier run having left the account behind.
    await request.post(`/api/platforms/${platformId}/accounts`, { data: { name } });
  }
  const platforms = (await (await request.get("/api/platforms")).json()) as {
    id: number;
    accounts: { id: number; name: string }[];
  }[];
  const accounts = platforms.find((entry) => entry.id === platformId)!.accounts;
  return {
    hotAccountId: accounts.find((entry) => entry.name === "Hot")!.id,
    coldAccountId: accounts.find((entry) => entry.name === "Cold")!.id,
    btcId: btc.id,
  };
}

test("the Admin confirms a proposed self-transfer and can unlink it again", async ({
  page,
  request,
}) => {
  const arranged = await arrange(request);
  test.skip(arranged === null, "The seed has not run, so no BTC Instrument exists.");
  const { hotAccountId, coldAccountId, btcId } = arranged!;

  // A note only this run wrote, so every locator below is unambiguous even
  // beside the seeded proposal and leftovers of an interrupted earlier run.
  const stamp = Date.now();
  const marker = `e2e self-transfer ${stamp}`;
  const transactionIds: number[] = [];
  for (const side of [
    {
      type: "transfer_out",
      occurred_at: new Date(stamp).toISOString(),
      account_id: hotAccountId,
      role: "out",
    },
    {
      type: "transfer_in",
      occurred_at: new Date(stamp + 15 * 60_000).toISOString(),
      account_id: coldAccountId,
      role: "in",
    },
  ]) {
    const created = await request.post("/api/transactions", {
      data: {
        type: side.type,
        occurred_at: side.occurred_at,
        note: marker,
        legs: [
          { account_id: side.account_id, instrument_id: btcId, role: side.role, quantity: "0.03657" },
        ],
      },
    });
    expect(created.status()).toBe(201);
    transactionIds.push(((await created.json()) as { id: number }).id);
  }

  try {
    await page.goto("/transfers");

    // The pair is proposed — by Instrument, quantity and window — and both
    // sides still wear the unmatched marker.
    const proposed = page
      .locator('section[aria-label="Proposed matches"]')
      .getByRole("listitem")
      .filter({ hasText: marker });
    await expect(proposed).toBeVisible();
    const unmatched = page
      .locator('section[aria-label="Unmatched transfers"]')
      .getByRole("listitem")
      .filter({ hasText: "0.03657 BTC" });
    await expect(unmatched).toHaveCount(2);

    // Nothing links itself: the link is the Admin's press.
    await proposed.getByRole("button", { name: "Confirm match" }).click();
    const linked = page
      .locator('section[aria-label="Confirmed self-transfers"]')
      .getByRole("listitem")
      .filter({ hasText: marker });
    await expect(linked).toBeVisible();
    await expect(linked.getByText("linked")).toBeVisible();
    await expect(proposed).toHaveCount(0);

    // Unlinking asks once — first press arms, second acts — and both sides
    // return to visibly unmatched, proposable again.
    await linked.getByRole("button", { name: "Unlink" }).click();
    await linked.getByRole("button", { name: "Confirm unlink" }).click();
    await expect(linked).toHaveCount(0);
    await expect(proposed).toBeVisible();
  } finally {
    for (const transactionId of transactionIds) {
      await request.delete(`/api/transactions/${transactionId}`);
    }
  }
});
