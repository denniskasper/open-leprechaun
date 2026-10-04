import { expect, test, type APIRequestContext } from "@playwright/test";

// The Portfolio screen end to end (ticket 54). The database is whatever the
// developer's is, so nothing here asserts a figure: a cash Opening Balance
// guarantees one counted position, a run of the snapshot task guarantees one
// stored snapshot, and the screen is asserted to state its results, its
// development and — on every allocation chart — how many positions it
// charts against how many are held.

async function arrange(request: APIRequestContext, accountName: string): Promise<void> {
  const platform = await request.post("/api/platforms", {
    data: { name: "E2E Portfolio", kind: "bank" },
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
    platformId = all.find((entry) => entry.name === "E2E Portfolio" && entry.kind === "bank")!.id;
  }
  const account = await request.post(`/api/platforms/${platformId}/accounts`, {
    data: { name: accountName },
  });
  const accountId = ((await account.json()) as { id: number }).id;

  const instruments = (await (await request.get("/api/instruments")).json()) as {
    id: number;
    is_numeraire: boolean;
  }[];
  const eur = instruments.find((entry) => entry.is_numeraire)!.id;

  await request.post("/api/transactions", {
    data: {
      type: "opening_balance",
      occurred_at: "2026-01-05T12:00:00Z",
      note: `e2e portfolio ${accountName}`,
      reconstructed: "basis",
      estimated_basis_eur: "500.00",
      legs: [{ account_id: accountId, instrument_id: eur, role: "in", quantity: "500.00" }],
    },
  });
}

test("the Admin sees results, development and allocation of the portfolio", async ({
  page,
  request,
}) => {
  await arrange(request, `Cash ${Date.now()}`);
  const ran = await request.post("/api/scheduled-tasks/portfolio_snapshot/run");
  expect(((await ran.json()) as { outcome: string }).outcome).toBe("ok");

  await page.goto("/portfolio");

  // Realised and unrealised stand apart, beside what was put in.
  const results = page.getByRole("region", { name: "Portfolio results" });
  for (const figure of ["Value now", "Net contributions", "Result", "Unrealised", "Realised"]) {
    await expect(results.getByText(figure, { exact: true })).toBeVisible();
  }

  // The stored snapshot ends the empty state; a range is selectable.
  await expect(page.getByText("No snapshot is stored yet")).toHaveCount(0);
  const range = page.getByRole("group", { name: "Range" });
  await range.getByRole("button", { name: "1M" }).click();
  await expect(range.getByRole("button", { name: "1M" })).toHaveAttribute("aria-pressed", "true");

  // Every allocation chart states its own completeness.
  for (const chart of ["By asset class", "By Instrument", "By Platform"]) {
    await expect(page.getByRole("region", { name: chart })).toContainText(
      /charts \d+ of \d+ positions? held/i,
    );
  }
});
