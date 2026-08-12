import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchInstruments } from "./instruments";

const uniswap = {
  id: 1,
  family: "crypto",
  type: "token",
  symbol: "UNI",
  name: "Uniswap",
  chain: "ethereum",
  contract_address: "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",
  isin: null,
  is_numeraire: false,
  fund_category: null,
  fund_category_source: null,
  distribution_policy: null,
  needs_review: false,
  listings: [],
  dangerous: false,
  stances: [],
};

const fund = {
  id: 2,
  family: "security",
  type: "etf",
  symbol: "EUNL",
  name: "iShares Core MSCI World UCITS ETF",
  chain: null,
  contract_address: null,
  isin: "IE00B4L5Y983",
  is_numeraire: false,
  fund_category: "aktienfonds",
  fund_category_source: "provider",
  distribution_policy: "accumulating",
  needs_review: false,
  listings: [{ id: 4, venue: "XETRA", quote_currency: "EUR", price_source: true }],
  dangerous: false,
  stances: [{ account_id: 5, stance: "kept" }],
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchInstruments", () => {
  it("reads the instruments from the API's own origin", async () => {
    respondWith(200, []);

    await fetchInstruments();

    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/instruments");
  });

  it("returns instruments with their identity attributes and listings", async () => {
    respondWith(200, [uniswap, fund]);

    await expect(fetchInstruments()).resolves.toEqual([uniswap, fund]);
  });

  it("rejects a family it does not know", async () => {
    respondWith(200, [{ ...uniswap, family: "commodity" }]);

    await expect(fetchInstruments()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchInstruments()).rejects.toThrow("500");
  });
});
