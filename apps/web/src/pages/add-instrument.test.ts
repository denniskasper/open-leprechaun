import { describe, expect, it } from "vitest";
import type { Instrument } from "@/api/instruments";
import { addInstrumentHref, addressProblem, instrumentPayload, wearing } from "./add-instrument";

function instrument(overrides: Partial<Instrument>): Instrument {
  return {
    id: 1,
    family: "crypto",
    type: "token",
    symbol: "USDC",
    name: "USD Coin",
    chain: "ethereum",
    contract_address: "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
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

const FIELDS = {
  symbol: " USDC ",
  name: " USD Coin ",
  chain: " Ethereum ",
  contractAddress: " 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 ",
  peggedCurrency: "usd",
};

describe("addressProblem", () => {
  it("holds a hex address to its one length", () => {
    expect(addressProblem("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")).toBeNull();
    expect(addressProblem("0xA0b8")).toMatch(/40 hex characters/);
    expect(addressProblem(`0x${"g".repeat(40)}`)).toMatch(/40 hex characters/);
  });

  it("takes any other chain's address as written", () => {
    expect(addressProblem("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")).toBeNull();
  });

  it("says nothing while the field is still empty", () => {
    expect(addressProblem("  ")).toBeNull();
  });
});

describe("instrumentPayload", () => {
  it("states a token by chain and contract, with its peg where one is given", () => {
    expect(instrumentPayload("token", FIELDS)).toEqual({
      kind: "token",
      symbol: "USDC",
      name: "USD Coin",
      chain: "Ethereum",
      contract_address: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
      pegged_currency: "USD",
    });
    expect(instrumentPayload("token", { ...FIELDS, peggedCurrency: " " })).toMatchObject({
      pegged_currency: null,
    });
  });

  it("states a native coin by its chain alone", () => {
    expect(instrumentPayload("native", { ...FIELDS, symbol: "BTC", name: "Bitcoin" })).toEqual({
      kind: "native",
      symbol: "BTC",
      name: "Bitcoin",
      chain: "Ethereum",
    });
  });

  it("states a currency by its code", () => {
    expect(instrumentPayload("cash", { ...FIELDS, symbol: "usd", name: "US Dollar" })).toEqual({
      kind: "cash",
      symbol: "USD",
      name: "US Dollar",
    });
  });
});

describe("wearing", () => {
  const listed = [
    instrument({ id: 1 }),
    instrument({ id: 2, family: "cash", type: "fiat", symbol: "EUR", name: "Euro", chain: null }),
    instrument({ id: 3, family: "security", type: "share", symbol: "USDC", name: "A share" }),
  ];

  it("finds the coins and currencies a venue's bare symbol could mean", () => {
    expect(wearing(listed, " USDC ").map((entry) => entry.id)).toEqual([1]);
  });

  it("finds nothing for a symbol nobody wears, or none typed", () => {
    expect(wearing(listed, "BTC")).toEqual([]);
    expect(wearing(listed, "")).toEqual([]);
  });
});

describe("addInstrumentHref", () => {
  it("opens the form with the symbol a sync could not resolve", () => {
    expect(addInstrumentHref("USDC")).toBe("/instruments?add=USDC");
    expect(addInstrumentHref("A&B")).toBe("/instruments?add=A%26B");
  });
});
