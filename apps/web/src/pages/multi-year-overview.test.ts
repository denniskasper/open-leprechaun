import { describe, expect, it } from "vitest";
import type { CarryforwardLayer, OverviewYear, PotCarryforward } from "@/api/multi-year-overview";
import {
  blockedYears,
  carryforwardRows,
  describeOrigin,
  gaugeShares,
  resolveLabel,
} from "@/pages/multi-year-overview";

function pot(overrides: Partial<PotCarryforward> = {}): PotCarryforward {
  return {
    category: "sonstige",
    carryforward_in_eur: "0",
    carryforward_in: [],
    consumed_eur: "0",
    consumed: [],
    produced_eur: "0",
    carryforward_out_eur: "0",
    carryforward_out: [],
    ...overrides,
  };
}

function year(overrides: Partial<OverviewYear> = {}): OverviewYear {
  const row = {
    gross_eur: "0",
    offsets_eur: "0",
    allowance_limit_eur: "1000",
    allowance_eur: "0",
    taxable_eur: "0",
    tax_eur: null,
  };
  return {
    year: 2025,
    blockers: [],
    private_sales: row,
    other_income: row,
    capital_income: {
      ...row,
      tax_eur: "0",
      categories: [
        pot({ category: "aktien" }),
        pot({ category: "sonstige" }),
        pot({ category: "termingeschaefte" }),
      ],
    },
    ...overrides,
  };
}

function layer(overrides: Partial<CarryforwardLayer> = {}): CarryforwardLayer {
  return { origin_year: 2024, amount_eur: "400", opening: false, ...overrides };
}

const BLOCKER = {
  kind: "unmatched_transfers",
  detail: "1 transfer leg up to the end of 2026 awaits a confirmed match.",
  resolve_path: "/transfers",
  count: 1,
};

describe("blockedYears", () => {
  it("names only the years something stands in the way of", () => {
    const years = [year({ year: 2025 }), year({ year: 2026, blockers: [BLOCKER] })];

    expect(blockedYears(years).map((blocked) => blocked.year)).toEqual([2026]);
  });
});

describe("carryforwardRows", () => {
  it("lists a pot only in the years its carryforward moved or stood", () => {
    const produced = pot({
      category: "termingeschaefte",
      produced_eur: "400",
      carryforward_out_eur: "400",
      carryforward_out: [layer({ origin_year: 2025 })],
    });
    const years = [
      year({
        year: 2025,
        capital_income: { ...year().capital_income!, categories: [pot(), produced] },
      }),
    ];

    expect(carryforwardRows(years)).toEqual([{ year: 2025, pot: produced }]);
  });

  it("skips a year whose capital income is not stated", () => {
    expect(carryforwardRows([year({ capital_income: null })])).toEqual([]);
  });

  it("treats a zero written to the cent as nothing", () => {
    const idle = pot({ carryforward_in_eur: "0.00", produced_eur: "0.00" });
    const years = [year({ capital_income: { ...year().capital_income!, categories: [idle] } })];

    expect(carryforwardRows(years)).toEqual([]);
  });
});

describe("describeOrigin", () => {
  it("names the year a carryforward came from", () => {
    expect(describeOrigin(layer({ origin_year: 2024 }))).toBe("from 2024");
  });

  it("says so when the balance was entered from an assessment predating the ledger", () => {
    expect(describeOrigin(layer({ origin_year: 2023, opening: true }))).toBe(
      "opening 2023",
    );
  });
});

describe("resolveLabel", () => {
  it("names the screen a blocker's path leads to", () => {
    expect(resolveLabel("/transfers")).toBe("Transfers");
    expect(resolveLabel("/settings/statutory")).toBe("Statutory");
  });

  it("answers nothing for a path no screen is registered at", () => {
    expect(resolveLabel("/futures")).toBeNull();
  });
});

describe("gaugeShares", () => {
  it("scales each stated figure against the largest", () => {
    expect(gaugeShares(["500", "2000", "0"])).toEqual([25, 100, 0]);
  });

  it("leaves an unstated figure without a gauge", () => {
    expect(gaugeShares([null, "1000"])).toEqual([null, 100]);
  });

  it("draws nothing when every year is zero", () => {
    expect(gaugeShares(["0", "0.00"])).toEqual([0, 0]);
  });
});
