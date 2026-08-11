import { afterEach, describe, expect, it, vi } from "vitest";
import { classifyFund, createSecurity, reviewSecurity, searchSecurities } from "./securities";

const candidate = {
  isin: "IE00B4L5Y983",
  wkn: "A0RPWH",
  ticker: "EUNL",
  name: "iShares Core MSCI World UCITS ETF USD Acc.",
  type: "etf",
  currency: "EUR",
  venue: "gettex",
  fund_category: "aktienfonds",
  distribution_policy: "accumulating",
  instrument_id: null,
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

describe("searchSecurities", () => {
  it("asks with the query URL-encoded and parses the candidates", async () => {
    respondWith(200, [candidate]);

    await expect(searchSecurities("msci world")).resolves.toEqual([candidate]);

    expect(fetch).toHaveBeenCalledWith("/api/securities/search?query=msci%20world");
  });

  it("surfaces the API's own words for a provider condition", async () => {
    respondWith(503, { detail: "onvista asked for a pause (HTTP 429)." });

    await expect(searchSecurities("x x")).rejects.toThrow("pause");
  });

  it("rejects a category it does not know", async () => {
    respondWith(200, [{ ...candidate, fund_category: "hedgefonds" }]);

    await expect(searchSecurities("x x")).rejects.toThrow();
  });
});

describe("createSecurity", () => {
  it("posts the security and answers the new id", async () => {
    respondWith(201, { id: 7 });

    await expect(
      createSecurity({ isin: "IE00B4L5Y983", name: "n", symbol: "EUNL", type: "etf" }),
    ).resolves.toBe(7);
  });

  it("surfaces a duplicate ISIN as the API states it", async () => {
    respondWith(409, { detail: "An Instrument already carries the ISIN IE00B4L5Y983." });

    await expect(
      createSecurity({ isin: "IE00B4L5Y983", name: "n", symbol: "EUNL", type: "etf" }),
    ).rejects.toThrow("already carries");
  });
});

describe("classifyFund and reviewSecurity", () => {
  it("put their bodies and settle on a bare 204", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );

    await expect(
      classifyFund(7, { fund_category: "aktienfonds", distribution_policy: null }),
    ).resolves.toBeUndefined();
    await expect(
      reviewSecurity(7, { type: "etf", symbol: "EUNL", name: "iShares" }),
    ).resolves.toBeUndefined();
  });

  it("surface the API's refusal words", async () => {
    respondWith(422, { detail: "A Teilfreistellung classification belongs to a fund." });

    await expect(
      classifyFund(7, { fund_category: "aktienfonds", distribution_policy: null }),
    ).rejects.toThrow("belongs to a fund");
  });
});
