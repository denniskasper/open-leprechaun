import { describe, expect, it } from "vitest";
import type { Instrument } from "@/api/instruments";
import type { PricedInstrument } from "@/api/prices";
import type { Candidate } from "@/api/securities";
import {
  classificationCell,
  conditionLine,
  identityOf,
  securityPayload,
  sharedSymbols,
  staleExplanation,
  stanceWarning,
  unheldListings,
} from "./instruments";

function instrument(overrides: Partial<Instrument>): Instrument {
  return {
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
    ...overrides,
  };
}

function security(overrides: Partial<Instrument>): Instrument {
  return instrument({
    family: "security",
    type: "etf",
    symbol: "EUNL",
    chain: null,
    contract_address: null,
    isin: "IE00B4L5Y983",
    ...overrides,
  });
}

describe("identityOf", () => {
  it("identifies a token by chain and abbreviated contract", () => {
    expect(identityOf(instrument({}))).toBe("ethereum · 0x1f98…f984");
  });

  it("identifies a native coin by its chain, marked native", () => {
    expect(
      identityOf(
        instrument({ type: "native", symbol: "BTC", chain: "bitcoin", contract_address: null }),
      ),
    ).toBe("bitcoin · native");
  });

  it("identifies a security by its ISIN", () => {
    expect(
      identityOf(
        instrument({
          family: "security",
          type: "etf",
          chain: null,
          contract_address: null,
          isin: "IE00B4L5Y983",
        }),
      ),
    ).toBe("IE00B4L5Y983");
  });

  it("identifies cash by its currency code", () => {
    expect(
      identityOf(
        instrument({
          family: "cash",
          type: "fiat",
          symbol: "EUR",
          chain: null,
          contract_address: null,
        }),
      ),
    ).toBe("EUR");
  });
});

describe("sharedSymbols", () => {
  it("names every symbol that more than one instrument displays", () => {
    const rows = [
      instrument({ id: 1, symbol: "UNI" }),
      instrument({ id: 2, symbol: "UNI", chain: "bsc" }),
      instrument({ id: 3, symbol: "BTC", type: "native", contract_address: null }),
    ];

    expect(sharedSymbols(rows)).toEqual(new Set(["UNI"]));
  });

  it("is empty when every symbol is unique", () => {
    expect(sharedSymbols([instrument({})])).toEqual(new Set());
  });
});

describe("stanceWarning", () => {
  it("wears no warning by default, and none when kept", () => {
    expect(stanceWarning(instrument({}))).toBeNull();
    expect(stanceWarning(instrument({ stances: [{ account_id: 1, stance: "kept" }] }))).toBeNull();
  });

  it("warns while any Account ignores the Instrument", () => {
    expect(
      stanceWarning(
        instrument({
          stances: [
            { account_id: 1, stance: "kept" },
            { account_id: 2, stance: "ignored" },
          ],
        }),
      ),
    ).toBe("ignored");
  });

  it("lets a global dangerous verdict outrank everything", () => {
    expect(
      stanceWarning(
        instrument({ dangerous: true, stances: [{ account_id: 1, stance: "kept" }] }),
      ),
    ).toBe("dangerous");
  });
});

describe("classificationCell", () => {
  it("does not apply outside the security family, nor to a share", () => {
    expect(classificationCell(instrument({}))).toEqual({ kind: "not_applicable" });
    expect(classificationCell(security({ type: "share" }))).toEqual({ kind: "not_applicable" });
  });

  it("asks for review before anything else — the type is not yet settled", () => {
    expect(classificationCell(security({ type: "unknown", needs_review: true }))).toEqual({
      kind: "review",
    });
    // A review outranks a classification question even on a typed fund.
    expect(classificationCell(security({ needs_review: true }))).toEqual({ kind: "review" });
  });

  it("names an unclassified fund — the state that blocks finalisation", () => {
    expect(classificationCell(security({}))).toEqual({ kind: "unclassified" });
    expect(classificationCell(security({ type: "fund" }))).toEqual({ kind: "unclassified" });
  });

  it("answers a classified fund with its category, source and policy", () => {
    expect(
      classificationCell(
        security({
          fund_category: "aktienfonds",
          fund_category_source: "provider",
          distribution_policy: "accumulating",
        }),
      ),
    ).toEqual({
      kind: "classified",
      category: "aktienfonds",
      source: "provider",
      policy: "accumulating",
    });
  });
});

describe("securityPayload", () => {
  const candidate: Candidate = {
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

  it("carries identifiers, listing and the provider prefill with its source", () => {
    expect(securityPayload(candidate)).toEqual({
      isin: "IE00B4L5Y983",
      name: "iShares Core MSCI World UCITS ETF USD Acc.",
      symbol: "EUNL",
      type: "etf",
      wkn: "A0RPWH",
      ticker: "EUNL",
      venue: "gettex",
      quote_currency: "EUR",
      classification: {
        fund_category: "aktienfonds",
        fund_category_source: "provider",
        distribution_policy: "accumulating",
      },
    });
  });

  it("falls back to WKN then ISIN for the display symbol", () => {
    expect(securityPayload({ ...candidate, ticker: null }).symbol).toBe("A0RPWH");
    expect(securityPayload({ ...candidate, ticker: null, wkn: null }).symbol).toBe(
      "IE00B4L5Y983",
    );
  });

  it("sends the listing only when venue and currency arrive together", () => {
    const half = securityPayload({ ...candidate, venue: null });

    expect(half.venue).toBeNull();
    expect(half.quote_currency).toBeNull();
  });

  it("sends no classification when the provider stated none", () => {
    expect(securityPayload({ ...candidate, fund_category: null }).classification).toBeNull();
  });
});

describe("conditionLine", () => {
  it("is null while every provider answers", () => {
    expect(conditionLine([])).toBeNull();
  });

  it("names each provider and keeps a rate limit distinct from an outage", () => {
    expect(
      conditionLine([
        { provider: "coingecko", condition: "rate_limited" },
        { provider: "defillama", condition: "outage" },
      ]),
    ).toBe("coingecko rate-limited · defillama outage");
  });
});

describe("staleExplanation", () => {
  const stale: PricedInstrument = {
    instrument_id: 1,
    symbol: "BTC",
    name: "Bitcoin",
    status: "stale",
    price_eur: "48000.5",
    source: "defillama",
    as_of: "2026-08-07T12:00:00Z",
  };

  it("names the source and the age of the last known price", () => {
    const explanation = staleExplanation(stale, "de-DE");

    expect(explanation).toContain("last known price");
    expect(explanation).toContain("defillama");
    expect(explanation).toContain("2026");
  });
});


describe("unheldListings", () => {
  const held = [
    { id: 1, venue: "Xetra", quote_currency: "EUR", price_source: true },
    { id: 2, venue: "London Stock Exchange", quote_currency: "USD", price_source: false },
  ];

  it("offers only the markets not already held, compared as venue and currency together", () => {
    const resolved = [
      { venue: "Xetra", quote_currency: "EUR" },
      { venue: "London Stock Exchange", quote_currency: "GBP" },
      { venue: "gettex", quote_currency: "EUR" },
    ];

    expect(unheldListings(resolved, held)).toEqual([
      { venue: "London Stock Exchange", quote_currency: "GBP" },
      { venue: "gettex", quote_currency: "EUR" },
    ]);
  });

  it("offers nothing when every resolved market is held", () => {
    expect(unheldListings([{ venue: "Xetra", quote_currency: "EUR" }], held)).toEqual([]);
  });

  it("treats a venue casing difference as held, matching the provider's own rule", () => {
    const holder = [{ id: 1, venue: "XETRA", quote_currency: "EUR", price_source: true }];

    expect(unheldListings([{ venue: "Xetra", quote_currency: "EUR" }], holder)).toEqual([]);
  });
});
