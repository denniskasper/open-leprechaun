import { describe, expect, it } from "vitest";
import type {
  FuturesPosition,
  LivePosition,
  UnattributableFunding,
  VenueStatement,
} from "@/api/futures";
import {
  closedNewestFirst,
  groupUnattributableFunding,
  ledgerOnly,
  nothingToShow,
} from "./futures";
import { toneOf } from "./futures-tables";

function position(overrides: Partial<FuturesPosition>): FuturesPosition {
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
    ledger_position_id: null,
    ...overrides,
  };
}

function statement(positions: LivePosition[]): VenueStatement {
  return {
    connection_id: 1,
    connection_label: "Main account",
    venue: "okx",
    adapter_kind: "futures",
    account_id: 1,
    supported: true,
    error: null,
    stated_at: "2031-03-03T10:00:00Z",
    positions,
  };
}

function payment(overrides: Partial<UnattributableFunding>): UnattributableFunding {
  return {
    id: 1,
    source: "okx:futures",
    account_id: 1,
    symbol: "BTC-USDT-SWAP",
    amount: "-0.10",
    settlement_symbol: "USDT",
    occurred_at: "2031-03-02T10:00:00Z",
    ...overrides,
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

    const uncovered = ledgerOnly(positions, [statement([live({ ledger_position_id: 1 })])]);

    expect(uncovered.map((entry) => entry.id)).toEqual([2]);
  });

  it("is every open position where no venue states any", () => {
    expect(ledgerOnly([position({ id: 1 })], []).map((entry) => entry.id)).toEqual([1]);
  });
});

describe("groupUnattributableFunding", () => {
  it("gathers payments by Account and symbol, with their exact total and the span they cover", () => {
    const groups = groupUnattributableFunding([
      payment({ id: 1, amount: "-0.10", occurred_at: "2031-03-04T08:00:00Z" }),
      payment({ id: 2, amount: "-0.20", occurred_at: "2031-03-02T08:00:00Z" }),
      payment({ id: 3, amount: "0.05", occurred_at: "2031-03-03T08:00:00Z" }),
    ]);

    expect(groups).toEqual([
      {
        account_id: 1,
        symbol: "BTC-USDT-SWAP",
        settlement_symbol: "USDT",
        count: 3,
        total: "-0.25",
        first_at: "2031-03-02T08:00:00Z",
        last_at: "2031-03-04T08:00:00Z",
      },
    ]);
  });

  it("keeps another Account, symbol or settlement asset apart", () => {
    const groups = groupUnattributableFunding([
      payment({ id: 1 }),
      payment({ id: 2, account_id: 2 }),
      payment({ id: 3, symbol: "ETH-USDT-SWAP" }),
      payment({ id: 4, settlement_symbol: "USDC" }),
    ]);

    expect(groups.map((group) => group.count)).toEqual([1, 1, 1, 1]);
  });

  it("is empty where every payment found its position", () => {
    expect(groupUnattributableFunding([])).toEqual([]);
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

describe("nothingToShow", () => {
  const empty = { positions: [], unattributable_funding: [], derivation_issues: [] };

  it("is the empty screen: no position, no venue, nothing unresolved", () => {
    expect(nothingToShow(empty, [])).toBe(true);
  });

  it("never hides what is unresolved behind the empty state", () => {
    expect(nothingToShow({ ...empty, unattributable_funding: [payment({})] }, [])).toBe(false);
    expect(
      nothingToShow(
        {
          ...empty,
          derivation_issues: [
            {
              id: 1,
              source: "okx:futures",
              account_id: 1,
              symbol: "BTC-USDT-SWAP",
              position_side: null,
              reason: "The stream states no contract variant.",
            },
          ],
        },
        [],
      ),
    ).toBe(false);
  });

  it("concludes nothing while an answer is still out", () => {
    expect(nothingToShow(undefined, [])).toBe(false);
    expect(nothingToShow(empty, undefined)).toBe(false);
  });

  it("is not empty where a venue is there to ask, or a position stands", () => {
    expect(nothingToShow(empty, [statement([])])).toBe(false);
    expect(nothingToShow({ ...empty, positions: [position({})] }, [])).toBe(false);
  });
});
