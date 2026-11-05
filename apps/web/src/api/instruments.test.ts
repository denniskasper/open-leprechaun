import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addDeployment,
  fetchInstruments,
  removeInstrument,
  settleAsDeploymentOf,
} from "./instruments";

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
  deployments: [
    {
      chain: "ethereum",
      contract_address: "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",
    },
  ],
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
  deployments: [],
  dangerous: false,
  stances: [{ account_id: 5, stance: "kept" }],
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    // A 204 carries no body — the Response constructor itself refuses one.
    vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status })),
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

describe("removeInstrument", () => {
  it("deletes by id", async () => {
    respondWith(204, undefined);

    await removeInstrument(7);

    expect(fetch).toHaveBeenCalledWith("/api/instruments/7", { method: "DELETE" });
  });

  it("surfaces the API's own reason for a refusal", async () => {
    respondWith(409, {
      detail: "This Instrument stays for good: it is recorded in transactions.",
    });

    await expect(removeInstrument(7)).rejects.toThrow(
      "This Instrument stays for good: it is recorded in transactions.",
    );
  });
});

describe("addDeployment", () => {
  it("posts another chain's contract for the token", async () => {
    respondWith(201, null);

    await addDeployment(7, {
      chain: "solana",
      contract_address: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    });

    expect(fetch).toHaveBeenCalledWith("/api/instruments/7/deployments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chain: "solana",
        contract_address: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      }),
    });
  });

  it("surfaces the API's own reason for a refusal", async () => {
    respondWith(409, {
      detail: "USD Coin (USDC) already holds this contract.",
    });

    await expect(
      addDeployment(7, { chain: "solana", contract_address: "x" }),
    ).rejects.toThrow("USD Coin (USDC) already holds this contract.");
  });
});

describe("settleAsDeploymentOf", () => {
  it("names the token this one is a Deployment of", async () => {
    respondWith(200, null);

    await settleAsDeploymentOf(9, 7);

    expect(fetch).toHaveBeenCalledWith("/api/instruments/9/deployment-of", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instrument_id: 7 }),
    });
  });

  it("surfaces the API's own reason for a refusal", async () => {
    respondWith(409, {
      detail: "only while nothing about it has been decided",
    });

    await expect(settleAsDeploymentOf(9, 7)).rejects.toThrow(
      "only while nothing about it has been decided",
    );
  });
});
