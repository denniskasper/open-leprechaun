import { describe, expect, it } from "vitest";
import type { Instrument } from "@/api/instruments";
import {
  addInstrumentHref,
  addressProblem,
  fieldProblems,
  alreadyKeyed,
  instrumentPayload,
  requestedKind,
  wearing,
} from "./add-instrument";

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

describe("fieldProblems", () => {
  const sound = {
    symbol: "USDC",
    name: "USD Coin",
    chain: "ethereum",
    contractAddress: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    peggedCurrency: "",
  };

  it("finds nothing wrong with a sound entry of any kind", () => {
    expect(fieldProblems("token", sound)).toEqual({});
    expect(fieldProblems("token", { ...sound, peggedCurrency: " usd " })).toEqual({});
    expect(fieldProblems("native", { ...sound, symbol: "BTC" })).toEqual({});
    expect(fieldProblems("cash", { ...sound, symbol: "usd" })).toEqual({});
  });

  it("says nothing about a field still empty — the form requires it itself", () => {
    expect(
      fieldProblems("token", {
        symbol: "",
        name: "",
        chain: "",
        contractAddress: "",
        peggedCurrency: "",
      }),
    ).toEqual({});
  });

  it("refuses a field holding only spaces", () => {
    expect(
      fieldProblems("token", {
        symbol: " ",
        name: "  ",
        chain: " ",
        contractAddress: "  ",
        peggedCurrency: "",
      }),
    ).toEqual({
      symbol: "A symbol cannot be blank.",
      name: "A name cannot be blank.",
      chain: "A chain cannot be blank.",
      contractAddress: "A contract address cannot be blank.",
    });
  });

  it("holds a peg to three letters", () => {
    for (const peggedCurrency of ["US", "U5D", "USDT"]) {
      expect(fieldProblems("token", { ...sound, peggedCurrency })).toEqual({
        peggedCurrency: "A currency code is three letters, like USD.",
      });
    }
  });

  it("holds a currency's code to three letters", () => {
    for (const symbol of ["US", "  "]) {
      expect(fieldProblems("cash", { ...sound, symbol })).toEqual({
        symbol: "A currency code is three letters, like USD.",
      });
    }
  });

  it("holds a token's hex address to its form", () => {
    expect(fieldProblems("token", { ...sound, contractAddress: "0xA0b8" })).toEqual({
      contractAddress: "An address starting with 0x is 40 hex characters after it.",
    });
  });

  it("judges only the fields the kind is made of", () => {
    const leftover = { ...sound, chain: " ", contractAddress: "0xA0b8", peggedCurrency: "US" };

    expect(fieldProblems("native", { ...leftover, chain: "bitcoin" })).toEqual({});
    expect(fieldProblems("cash", { ...leftover, symbol: "USD" })).toEqual({});
  });
});

describe("alreadyKeyed", () => {
  const listed = [
    instrument({ id: 1 }),
    instrument({ id: 2, family: "cash", type: "fiat", symbol: "EUR", name: "Euro", chain: null }),
    instrument({
      id: 3,
      type: "native",
      symbol: "BTC",
      name: "Bitcoin",
      chain: "bitcoin",
      contract_address: null,
    }),
    instrument({ id: 4, family: "security", type: "share", symbol: "ETH", name: "A share" }),
  ];
  const typed = { ...FIELDS, symbol: "BTC" };

  it("finds the native coin already keyed on the symbol", () => {
    expect(alreadyKeyed(listed, "native", typed)?.id).toBe(3);
    expect(alreadyKeyed(listed, "native", { ...typed, symbol: " BTC " })?.id).toBe(3);
  });

  it("finds the currency already keyed on the code, in any casing", () => {
    expect(alreadyKeyed(listed, "cash", { ...typed, symbol: "eur" })?.id).toBe(2);
  });

  it("finds the token already keyed on the chain and contract, in any casing", () => {
    expect(alreadyKeyed(listed, "token", { ...FIELDS, symbol: "ANOTHER" })?.id).toBe(1);
    expect(alreadyKeyed(listed, "token", { ...FIELDS, chain: "solana" })).toBeNull();
  });

  it("keeps the kinds apart: a symbol is an identity only within its own", () => {
    // A token wearing a coin's symbol, a coin wearing a currency's code and a
    // security wearing either are second Instruments, not the same one.
    expect(alreadyKeyed(listed, "native", { ...typed, symbol: "USDC" })).toBeNull();
    expect(alreadyKeyed(listed, "native", { ...typed, symbol: "EUR" })).toBeNull();
    expect(alreadyKeyed(listed, "cash", { ...typed, symbol: "BTC" })).toBeNull();
    expect(alreadyKeyed(listed, "native", { ...typed, symbol: "ETH" })).toBeNull();
  });

  it("finds nothing while nothing is typed", () => {
    expect(alreadyKeyed(listed, "native", { ...typed, symbol: " " })).toBeNull();
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

  it("names the kind where only one can answer to the symbol", () => {
    expect(addInstrumentHref("USD", "cash")).toBe("/instruments?add=USD&kind=cash");
    expect(addInstrumentHref("USDC", null)).toBe("/instruments?add=USDC");
  });
});

describe("requestedKind", () => {
  it("opens on the kind the link names", () => {
    expect(requestedKind("cash")).toBe("cash");
    expect(requestedKind("native")).toBe("native");
  });

  it("opens on a token where the link names none, or none the form knows", () => {
    expect(requestedKind(null)).toBe("token");
    expect(requestedKind("security")).toBe("token");
  });
});
