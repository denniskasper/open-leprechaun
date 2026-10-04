import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchMultiYearOverview } from "./multi-year-overview";

const privateSales = {
  gross_eur: "1500.00",
  offsets_eur: "700.00",
  allowance_limit_eur: "1000",
  allowance_eur: "800.00",
  taxable_eur: "0",
  tax_eur: null,
};

const pot = {
  category: "termingeschaefte",
  carryforward_in_eur: "400",
  carryforward_in: [{ origin_year: 2024, amount_eur: "400", opening: false }],
  consumed_eur: "400",
  consumed: [{ origin_year: 2024, amount_eur: "400", opening: false }],
  produced_eur: "0",
  carryforward_out_eur: "0",
  carryforward_out: [],
};

const year = {
  year: 2025,
  blockers: [],
  private_sales: privateSales,
  other_income: { ...privateSales, gross_eur: "300", offsets_eur: "0" },
  capital_income: {
    gross_eur: "1000",
    offsets_eur: "400",
    allowance_limit_eur: "1000",
    allowance_eur: "600",
    taxable_eur: "0",
    tax_eur: "0.00",
    categories: [pot],
  },
};

const blockedYear = {
  year: 2026,
  blockers: [
    {
      kind: "missing_statutory_configuration",
      detail: "The 2026 statutory configuration is missing required values: flat_rate.",
      resolve_path: "/settings/statutory",
      count: 1,
    },
  ],
  private_sales: null,
  other_income: null,
  capital_income: null,
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMultiYearOverview", () => {
  it("reads every year with its regimes, carryforwards and blockers", async () => {
    respondWith(200, { years: [year, blockedYear] });

    await expect(fetchMultiYearOverview()).resolves.toEqual({ years: [year, blockedYear] });

    expect(fetch).toHaveBeenCalledWith("/api/multi-year-overview");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchMultiYearOverview()).rejects.toThrow("500");
  });

  it("rejects a figure that arrives as a number rather than a fixed-point string", async () => {
    respondWith(200, { years: [{ ...year, private_sales: { ...privateSales, gross_eur: 1500 } }] });

    await expect(fetchMultiYearOverview()).rejects.toThrow();
  });

  it("rejects a pot outside the three the engine keeps", async () => {
    respondWith(200, {
      years: [
        {
          ...year,
          capital_income: { ...year.capital_income, categories: [{ ...pot, category: "krypto" }] },
        },
      ],
    });

    await expect(fetchMultiYearOverview()).rejects.toThrow();
  });
});
