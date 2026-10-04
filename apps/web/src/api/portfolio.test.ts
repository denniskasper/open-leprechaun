import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDevelopment, fetchRealised } from "./portfolio";

const measurement = {
  snapshot_date: "2026-08-01",
  taken_at: "2026-08-01T21:55:00Z",
  value_eur: "1500.00",
  positions_held: 3,
  positions_counted: 2,
  contributions_eur: "1200.00",
  withdrawals_eur: "200.00",
  net_contributions_eur: "1000.00",
  result_eur: "500.00",
  unvalued_flows: 0,
};

const realised = {
  result_eur: "-200.00",
  stated: 1,
  events: 1,
  components: [
    { kind: "private_sales", result_eur: "0.00", stated: 0, events: 0, refusal: null },
    { kind: "securities", result_eur: "-200.00", stated: 1, events: 1, refusal: null },
    { kind: "futures", result_eur: "0.00", stated: 0, events: 0, refusal: null },
  ],
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

describe("fetchDevelopment", () => {
  it("reads the stored snapshots and the live measurement", async () => {
    const development = { snapshots: [measurement], current: measurement };
    respondWith(200, development);

    await expect(fetchDevelopment()).resolves.toEqual(development);

    expect(fetch).toHaveBeenCalledWith("/api/portfolio/development");
  });

  it("accepts a value nothing can state", async () => {
    const unstated = { ...measurement, value_eur: null, result_eur: null, positions_counted: 0 };
    respondWith(200, { snapshots: [], current: unstated });

    await expect(fetchDevelopment()).resolves.toMatchObject({ current: { value_eur: null } });
  });

  it("rejects a figure that arrives as a number rather than a fixed-point string", async () => {
    respondWith(200, { snapshots: [], current: { ...measurement, value_eur: 1500 } });

    await expect(fetchDevelopment()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchDevelopment()).rejects.toThrow("500");
  });
});

describe("fetchRealised", () => {
  it("reads the realised result with its kinds", async () => {
    respondWith(200, realised);

    await expect(fetchRealised()).resolves.toEqual(realised);

    expect(fetch).toHaveBeenCalledWith("/api/portfolio/realised");
  });

  it("accepts a kind its engine refused, with the sentence saying why", async () => {
    const refused = {
      kind: "private_sales",
      result_eur: null,
      stated: 0,
      events: 0,
      refusal: "An acquisition is missing from the ledger.",
    };
    respondWith(200, { ...realised, result_eur: null, components: [refused] });

    await expect(fetchRealised()).resolves.toMatchObject({ result_eur: null });
  });

  it("rejects a kind outside the three the engines state", async () => {
    respondWith(200, {
      ...realised,
      components: [{ ...realised.components[0], kind: "staking" }],
    });

    await expect(fetchRealised()).rejects.toThrow();
  });
});
