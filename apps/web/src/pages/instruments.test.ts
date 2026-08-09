import { describe, expect, it } from "vitest";
import type { Instrument } from "@/api/instruments";
import type { PricedInstrument } from "@/api/prices";
import { conditionLine, identityOf, sharedSymbols, staleExplanation, stanceWarning } from "./instruments";

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
    listings: [],
    dangerous: false,
    stances: [],
    ...overrides,
  };
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
