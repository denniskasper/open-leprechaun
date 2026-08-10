import { describe, expect, it } from "vitest";
import type { CoverageWarning } from "@/api/connections";
import type { Position } from "@/api/holdings";
import {
  counts,
  custodyOf,
  describeCoverageWarning,
  displayMoney,
  exclusionLine,
  groupHoldings,
  sumFixed,
  totalsOf,
} from "@/pages/holdings";

function position(overrides: Partial<Position> = {}): Position {
  return {
    instrument_id: 1,
    symbol: "BTC",
    name: "Bitcoin",
    family: "crypto",
    type: "native_coin",
    chain: "bitcoin",
    contract_address: null,
    isin: null,
    is_numeraire: false,
    account_id: 1,
    account_name: "Main",
    access_software: null,
    platform_name: "Kraken",
    platform_kind: "exchange",
    quantity: "1",
    marker: null,
    basis_eur: "10000",
    basis_gap: null,
    average_cost_eur: "10000.00",
    value_eur: "12000.00",
    unrealised_eur: "2000.00",
    price_source: "coingecko",
    price_as_of: "2026-08-01T00:00:00Z",
    rate_date: null,
    ...overrides,
  };
}

describe("custodyOf", () => {
  it("holds a cold-storage device and a software wallet as self-custody", () => {
    expect(custodyOf("cold_storage")).toBe("self_custody");
    expect(custodyOf("software_wallet")).toBe("self_custody");
  });

  it("holds an exchange, broker and bank as third-party custody", () => {
    expect(custodyOf("exchange")).toBe("third_party");
    expect(custodyOf("broker")).toBe("third_party");
    expect(custodyOf("bank")).toBe("third_party");
  });
});

describe("groupHoldings", () => {
  const btc = position({ platform_name: "Ledger Nano", platform_kind: "cold_storage" });
  const eur = position({
    instrument_id: 2,
    symbol: "EUR",
    family: "cash",
    is_numeraire: true,
    platform_name: "Kraken",
    platform_kind: "exchange",
  });

  it("buckets by asset class in the fixed family order", () => {
    const groups = groupHoldings([eur, btc], "asset_class");
    expect(groups.map((group) => group.label)).toEqual(["Crypto", "Cash"]);
  });

  it("buckets by Platform alphabetically", () => {
    const groups = groupHoldings([btc, eur], "platform");
    expect(groups.map((group) => group.label)).toEqual(["Kraken", "Ledger Nano"]);
  });

  it("buckets by custody, self-custody first", () => {
    const groups = groupHoldings([eur, btc], "custody");
    expect(groups.map((group) => group.label)).toEqual(["Self-custody", "Third-party custody"]);
    expect(groups[0]?.positions).toEqual([btc]);
  });
});

describe("sumFixed", () => {
  it("sums decimal strings of mixed scale without a float", () => {
    expect(sumFixed(["10000.05", "0.000000000000000001"])).toBe("10000.050000000000000001");
  });

  it("carries signs", () => {
    expect(sumFixed(["100.00", "-250.50"])).toBe("-150.50");
  });

  it("answers zero for nothing", () => {
    expect(sumFixed([])).toBe("0");
  });
});

describe("totalsOf and exclusionLine", () => {
  const kept = position();
  const awaiting = position({
    instrument_id: 3,
    symbol: "ETH",
    basis_eur: null,
    basis_gap: "awaiting_valuation",
    average_cost_eur: null,
    unrealised_eur: null,
    value_eur: "500.00",
  });
  const unpriced = position({
    instrument_id: 4,
    symbol: "NEW",
    marker: "unpriced",
    value_eur: null,
    unrealised_eur: null,
  });
  const dangerous = position({ instrument_id: 5, symbol: "EVIL", marker: "dangerous" });

  it("counts only unmarked positions", () => {
    expect(counts(kept)).toBe(true);
    expect(counts(unpriced)).toBe(false);
  });

  it("totals value over counted positions and unrealised where the basis is stated", () => {
    const totals = totalsOf([kept, awaiting, unpriced, dangerous]);
    expect(totals.value).toBe("12500.00");
    expect(totals.unrealised).toBe("2000.00");
    expect(totals.counted).toBe(2);
    expect(totals.unrealisedStated).toBe(1);
  });

  it("names what stands outside the totals and why", () => {
    expect(exclusionLine([kept, unpriced, dangerous])).toBe(
      "2 positions stand outside the totals: 1 unpriced, 1 dangerous",
    );
  });

  it("stays silent when everything counts", () => {
    expect(exclusionLine([kept])).toBeNull();
  });
});

describe("displayMoney", () => {
  it("renders EUR exact, digits verbatim", () => {
    expect(displayMoney("12000.05", "EUR", null, "en-US")).toBe("€12,000.05");
  });

  it("multiplies by the served rate for a foreign display currency", () => {
    const rate = { currency: "USD", rate: "1.10", rate_date: "2026-08-07" };
    expect(displayMoney("1000.00", "USD", rate, "en-US")).toBe("$1,100.00");
  });

  it("falls back to EUR while no rate is served", () => {
    expect(displayMoney("1000.00", "USD", null, "en-US")).toBe("€1,000.00");
  });
});

describe("describeCoverageWarning", () => {
  const warning: CoverageWarning = {
    connection_id: 1,
    connection_label: "Main account",
    venue: "okx",
    platform_name: "OKX",
    account_id: 3,
    account_name: "Trading",
    coverage_starts_at: "2026-05-12T09:15:00Z",
    earliest_elsewhere_at: "2024-01-03T12:00:00Z",
  };

  it("names the venue and states both instants as dates", () => {
    expect(describeCoverageWarning(warning, "en-US")).toBe(
      "OKX · Trading: coverage starts May 12, 2026, but activity elsewhere starts Jan 3, 2024 — older history at this venue cannot arrive by sync.",
    );
  });
});
