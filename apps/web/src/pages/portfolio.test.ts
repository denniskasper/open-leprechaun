import { describe, expect, it } from "vitest";
import type { Position } from "@/api/holdings";
import type { Measurement, Realised } from "@/api/portfolio";
import {
  allocate,
  changeOver,
  coverageLine,
  inRange,
  realisedLine,
  seriesOf,
  subtractFixed,
} from "@/pages/portfolio";

function measurement(date: string, overrides: Partial<Measurement> = {}): Measurement {
  return {
    snapshot_date: date,
    taken_at: `${date}T21:55:00Z`,
    value_eur: "1000.00",
    positions_held: 2,
    positions_counted: 2,
    contributions_eur: "1000.00",
    withdrawals_eur: "0.00",
    net_contributions_eur: "1000.00",
    result_eur: "0.00",
    unvalued_flows: 0,
    ...overrides,
  };
}

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

describe("subtractFixed", () => {
  it("subtracts fixed-point strings without passing through a float", () => {
    expect(subtractFixed("0.30", "0.10")).toBe("0.20");
    expect(subtractFixed("100.00", "250.50")).toBe("-150.50");
    expect(subtractFixed("5.00", "-2.50")).toBe("7.50");
  });
});

describe("seriesOf", () => {
  it("ends the stored snapshots with the live measurement", () => {
    const series = seriesOf({
      snapshots: [measurement("2026-08-01"), measurement("2026-08-02")],
      current: measurement("2026-08-03", { value_eur: "1100.00" }),
    });

    expect(series.map((point) => point.snapshot_date)).toEqual([
      "2026-08-01",
      "2026-08-02",
      "2026-08-03",
    ]);
  });

  it("lets the live measurement stand in for today's stored snapshot", () => {
    const series = seriesOf({
      snapshots: [measurement("2026-08-01"), measurement("2026-08-02")],
      current: measurement("2026-08-02", { value_eur: "1100.00" }),
    });

    expect(series).toHaveLength(2);
    expect(series[1]?.value_eur).toBe("1100.00");
  });
});

describe("inRange", () => {
  const series = [
    measurement("2025-08-02"),
    measurement("2025-12-31"),
    measurement("2026-01-01"),
    measurement("2026-07-03"),
    measurement("2026-08-03"),
  ];
  const dates = (range: Parameters<typeof inRange>[1]) =>
    inRange(series, range, "2026-08-03").map((point) => point.snapshot_date);

  it("keeps the last month", () => {
    expect(dates("1M")).toEqual(["2026-07-03", "2026-08-03"]);
  });

  it("keeps the year to date from the first of January", () => {
    expect(dates("YTD")).toEqual(["2026-01-01", "2026-07-03", "2026-08-03"]);
  });

  it("keeps a year back, not the day before it", () => {
    expect(dates("1Y")).toEqual(["2025-12-31", "2026-01-01", "2026-07-03", "2026-08-03"]);
  });

  it("keeps everything", () => {
    expect(dates("ALL")).toHaveLength(5);
  });

  it("counts a month back from a month's last day to the shorter month's last day", () => {
    const march = [measurement("2026-02-27"), measurement("2026-02-28"), measurement("2026-03-31")];

    expect(inRange(march, "1M", "2026-03-31").map((point) => point.snapshot_date)).toEqual([
      "2026-02-28",
      "2026-03-31",
    ]);
  });
});

describe("changeOver", () => {
  it("splits the change in value into what was put in and what the holdings did", () => {
    const change = changeOver([
      measurement("2026-08-01", { value_eur: "1000.00", net_contributions_eur: "1000.00" }),
      measurement("2026-08-02", { value_eur: "1800.00", net_contributions_eur: "1500.00" }),
    ]);

    // A 500 deposit and a 300 gain — the deposit is no part of the result.
    expect(change).toEqual({
      from: "2026-08-01",
      to: "2026-08-02",
      value: "800.00",
      netContributions: "500.00",
      result: "300.00",
      partial: false,
    });
  });

  it("shows a withdrawal as money taken out, not as a loss", () => {
    const change = changeOver([
      measurement("2026-08-01", { value_eur: "1000.00", net_contributions_eur: "1000.00" }),
      measurement("2026-08-02", { value_eur: "600.00", net_contributions_eur: "600.00" }),
    ]);

    expect(change).toMatchObject({ value: "-400.00", netContributions: "-400.00", result: "0.00" });
  });

  it("measures between the first and last points that state a value", () => {
    const change = changeOver([
      measurement("2026-08-01", { value_eur: null }),
      measurement("2026-08-02", { value_eur: "1000.00" }),
      measurement("2026-08-03", { value_eur: "1100.00" }),
      measurement("2026-08-04", { value_eur: null }),
    ]);

    expect(change).toMatchObject({ from: "2026-08-02", to: "2026-08-03", value: "100.00" });
  });

  it("says when either end leaves something out, so the result may not be all result", () => {
    const start = measurement("2026-08-01");
    const unvalued = changeOver([start, measurement("2026-08-02", { unvalued_flows: 1 })]);
    const uncounted = changeOver([
      measurement("2026-08-01", { positions_held: 3 }),
      measurement("2026-08-02"),
    ]);

    expect(unvalued?.partial).toBe(true);
    expect(uncounted?.partial).toBe(true);
  });

  it("states no change over fewer than two valued points", () => {
    expect(changeOver([measurement("2026-08-01")])).toBeNull();
    expect(changeOver([])).toBeNull();
  });
});

describe("allocate", () => {
  const btc = position({ value_eur: "6000.00" });
  const eth = position({ instrument_id: 2, symbol: "ETH", value_eur: "3000.00" });
  const cash = position({
    instrument_id: 3,
    symbol: "EUR",
    family: "cash",
    platform_name: "Sparkasse",
    platform_kind: "bank",
    value_eur: "1000.00",
  });

  it("charts by asset class, largest first, with each slice's share", () => {
    const allocation = allocate([cash, btc, eth], "asset_class");

    expect(allocation.slices.map((slice) => [slice.label, slice.value, slice.share])).toEqual([
      ["Crypto", "9000.00", 0.9],
      ["Cash", "1000.00", 0.1],
    ]);
  });

  it("charts by Platform", () => {
    const allocation = allocate([cash, btc, eth], "platform");

    expect(allocation.slices.map((slice) => [slice.label, slice.positions])).toEqual([
      ["Kraken", 2],
      ["Sparkasse", 1],
    ]);
  });

  it("keeps two Platforms of one name and different kinds apart", () => {
    const wallet = position({ platform_kind: "software_wallet", value_eur: "100.00" });

    expect(allocate([btc, wallet], "platform").slices).toHaveLength(2);
  });

  it("charts one Instrument held at two Accounts as one slice", () => {
    const elsewhere = position({ account_id: 2, platform_name: "Ledger", value_eur: "4000.00" });

    const allocation = allocate([btc, elsewhere, eth], "instrument");

    expect(allocation.slices.map((slice) => [slice.label, slice.value, slice.positions])).toEqual([
      ["BTC", "10000.00", 2],
      ["ETH", "3000.00", 1],
    ]);
  });

  it("keeps two Instruments sharing a ticker apart", () => {
    const impostor = position({ instrument_id: 9, name: "Bitcoin Fake", value_eur: "500.00" });

    expect(allocate([btc, impostor], "instrument").slices).toHaveLength(2);
  });

  it("states how many positions it charts against how many are held", () => {
    const unpriced = position({ instrument_id: 4, marker: "unpriced", value_eur: null });
    const ignored = position({ instrument_id: 5, marker: "ignored" });

    const allocation = allocate([btc, eth, unpriced, ignored], "instrument");

    expect([allocation.charted, allocation.held]).toEqual([2, 4]);
  });

  it("groups the slices below the threshold rather than dropping them", () => {
    const dust = [5, 6, 7].map((id) =>
      position({ instrument_id: id, symbol: `DUST${id}`, value_eur: "50.00" }),
    );

    const allocation = allocate([btc, eth, ...dust], "instrument");

    expect(allocation.slices.map((slice) => slice.label)).toEqual(["BTC", "ETH", "3 smaller"]);
    const grouped = allocation.slices[2];
    expect(grouped).toMatchObject({ value: "150.00", positions: 3, grouped: ["DUST5", "DUST6", "DUST7"] });
    // Nothing fell out: the charted count still covers the grouped positions.
    expect(allocation.charted).toBe(5);
  });

  it("leaves a lone small slice under its own name", () => {
    const dust = position({ instrument_id: 5, symbol: "DUST", value_eur: "50.00" });

    const allocation = allocate([btc, eth, dust], "instrument");

    expect(allocation.slices.map((slice) => slice.label)).toEqual(["BTC", "ETH", "DUST"]);
  });

  it("cannot chart a share of a position worth nothing or less", () => {
    const overdrawn = position({ instrument_id: 6, symbol: "USD", value_eur: "-20.00" });

    const allocation = allocate([btc, overdrawn], "instrument");

    expect([allocation.charted, allocation.held]).toEqual([1, 2]);
  });
});

describe("coverageLine", () => {
  it("says how many positions a chart covers", () => {
    expect(coverageLine(3, 5)).toBe("charts 3 of 5 positions held");
    expect(coverageLine(1, 1)).toBe("charts 1 of 1 position held");
  });
});

describe("realisedLine", () => {
  const realised = (overrides: Partial<Realised>): Realised => ({
    result_eur: "500.00",
    stated: 2,
    events: 2,
    components: [],
    ...overrides,
  });

  it("says nothing more when every event states its gain", () => {
    expect(realisedLine(realised({}))).toBeNull();
  });

  it("says how many events the figure covers when some await a valuation", () => {
    expect(realisedLine(realised({ stated: 1 }))).toBe("over 1 of 2 sales and closes");
  });
});
