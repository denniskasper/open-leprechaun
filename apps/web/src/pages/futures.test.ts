import { describe, expect, it } from "vitest";
import type { KindLive, LivePosition, Position } from "@/api/futures";
import {
  closedNewestFirst,
  ledgerOnly,
  marginRatioWords,
  ratioWords,
  signedSum,
  toneOf,
} from "./futures";

function position(overrides: Partial<Position>): Position {
  return {
    id: 1,
    origin: "derived",
    source: "okx:futures",
    account_id: 1,
    symbol: "BTC-USDT-SWAP",
    side: "long",
    quantity: "2",
    settlement_symbol: "USDT",
    opened_at: "2031-03-02T10:00:00Z",
    closed_at: null,
    realized: "0",
    fees: "1",
    funding: "0",
    net: "-1",
    net_eur: null,
    ...overrides,
  };
}

function live(overrides: Partial<LivePosition>): LivePosition {
  return {
    symbol: "BTC-USDT-SWAP",
    side: "long",
    quantity: "2",
    quantity_unit: "BTC",
    notional_usd: null,
    leverage: null,
    margin_mode: null,
    entry_price: null,
    mark_price: null,
    liquidation_price: null,
    breakeven_price: null,
    floating_result: null,
    floating_result_ratio: null,
    margin: null,
    margin_ratio: null,
    settlement_symbol: "USDT",
    opened_at: null,
    as_of: "2031-03-03T10:00:00Z",
    ledger_position_id: null,
    ...overrides,
  };
}

function kind(positions: LivePosition[]): KindLive {
  return {
    connection_id: 1,
    connection_label: "Main account",
    venue: "okx",
    adapter_kind: "futures",
    account_id: 1,
    supported: true,
    error: null,
    positions,
  };
}

describe("closedNewestFirst", () => {
  it("keeps closed positions only, the latest close on top", () => {
    const listed = closedNewestFirst([
      position({ id: 1, closed_at: "2031-03-02T12:00:00Z" }),
      position({ id: 2 }),
      position({ id: 3, closed_at: "2031-04-02T12:00:00Z" }),
    ]);

    expect(listed.map((entry) => entry.id)).toEqual([3, 1]);
  });
});

describe("ledgerOnly", () => {
  it("names the ledger's open positions no venue statement covers", () => {
    const positions = [
      position({ id: 1 }),
      position({ id: 2, symbol: "ETH-USDT-SWAP" }),
      position({ id: 3, closed_at: "2031-03-02T12:00:00Z" }),
    ];

    const uncovered = ledgerOnly(positions, [kind([live({ ledger_position_id: 1 })])]);

    expect(uncovered.map((entry) => entry.id)).toEqual([2]);
  });

  it("is every open position while no venue has answered", () => {
    expect(ledgerOnly([position({ id: 1 })], []).map((entry) => entry.id)).toEqual([1]);
  });
});

describe("ratioWords", () => {
  it("states a share with its direction in the figure", () => {
    expect(ratioWords("-0.0425", "en-US")).toBe("−4.25%");
    expect(ratioWords("0.02", "en-US")).toBe("+2.00%");
    expect(ratioWords("0", "en-US")).toBe("0.00%");
  });
});

describe("marginRatioWords", () => {
  it("states the venue's ratio as the percentage its own screen shows", () => {
    expect(marginRatioWords("7.5", "en-US")).toBe("750.00%");
  });
});

describe("toneOf", () => {
  it("reads a gain, a loss and nothing either way", () => {
    expect(toneOf("12.5")).toBe("signal");
    expect(toneOf("-0.000001")).toBe("alarm");
    expect(toneOf("0.00")).toBe("idle");
    expect(toneOf(null)).toBe("idle");
  });
});

describe("signedSum", () => {
  it("adds fixed-point amounts without a float in between", () => {
    expect(signedSum(["-0.1", "-0.2", "0.05"])).toBe("-0.25");
    expect(signedSum(["0.1", "0.2"])).toBe("0.3");
    expect(signedSum(["1.5", "-1.5"])).toBe("0");
    expect(signedSum([])).toBe("0");
    expect(signedSum(["-0.000000000000000001", "1"])).toBe("0.999999999999999999");
  });
});
