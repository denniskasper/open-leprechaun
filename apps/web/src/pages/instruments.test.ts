import { describe, expect, it } from "vitest";
import type { Instrument } from "@/api/instruments";
import { identityOf, sharedSymbols } from "./instruments";

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
    listings: [],
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
