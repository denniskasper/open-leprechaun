import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCryptoPrices, fetchSecurityPrices } from "./prices";

const report = {
  prices: [
    {
      instrument_id: 1,
      symbol: "BTC",
      name: "Bitcoin",
      status: "stale",
      price_eur: "48000.5",
      source: "defillama",
      as_of: "2026-08-07T12:00:00Z",
    },
    {
      instrument_id: 2,
      symbol: "KAS",
      name: "Kaspa",
      status: "unpriced",
      price_eur: null,
      source: null,
      as_of: null,
    },
  ],
  conditions: [{ provider: "coingecko", condition: "rate_limited" }],
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

describe("fetchCryptoPrices", () => {
  it("reads the report from the API's own origin", async () => {
    respondWith(200, { prices: [], conditions: [] });

    await fetchCryptoPrices();

    expect(fetch).toHaveBeenCalledWith("/api/prices/crypto");
  });

  it("returns prices with staleness and the providers' named conditions", async () => {
    respondWith(200, report);

    await expect(fetchCryptoPrices()).resolves.toEqual(report);
  });

  it("rejects a price that is not a fixed-point decimal string", async () => {
    respondWith(200, {
      ...report,
      prices: [{ ...report.prices[0], price_eur: 48000.5 }],
    });

    await expect(fetchCryptoPrices()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchCryptoPrices()).rejects.toThrow("500");
  });
});

describe("fetchSecurityPrices", () => {
  it("reads the securities report in the same vocabulary", async () => {
    respondWith(200, report);

    await expect(fetchSecurityPrices()).resolves.toEqual(report);

    expect(fetch).toHaveBeenCalledWith("/api/prices/securities");
  });
});
