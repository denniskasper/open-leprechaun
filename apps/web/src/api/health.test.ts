import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchHealth, fetchHealthReport } from "./health";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHealth", () => {
  it("reads the health report from the API's own origin", async () => {
    respondWith(200, { status: "ok", database: "up" });

    await fetchHealth();

    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/health");
  });

  it("returns the report when the service is healthy", async () => {
    respondWith(200, { status: "ok", database: "up" });

    await expect(fetchHealth()).resolves.toEqual({ status: "ok", database: "up" });
  });

  it("returns the report when the service is degraded, which arrives as a 503", async () => {
    respondWith(503, { status: "degraded", database: "down" });

    await expect(fetchHealth()).resolves.toEqual({ status: "degraded", database: "down" });
  });

  it("rejects a response that is not a health report", async () => {
    respondWith(200, { status: "fine" });

    await expect(fetchHealth()).rejects.toThrow();
  });

  it("rejects a response that carries no report at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>gateway error</html>", { status: 502 })),
    );

    await expect(fetchHealth()).rejects.toThrow("502");
  });
});

const report = {
  checked_at: "2026-10-04T09:00:00Z",
  providers: [
    {
      name: "coingecko",
      feeds: "crypto_prices",
      state: "rate_limited",
      last_success_at: "2026-10-04T08:45:00Z",
      last_error_at: "2026-10-04T09:00:00Z",
      last_error: "coingecko asked for a pause (HTTP 429).",
      affected_instruments: [{ id: 7, symbol: "KAS", name: "Kaspa" }],
    },
  ],
  connections: [
    {
      id: 3,
      label: "Main account",
      venue: "okx",
      last_sync_at: "2026-10-04T06:00:00Z",
      kinds: [
        {
          adapter_kind: "spot",
          ok: true,
          last_success_at: "2026-10-04T06:00:00Z",
          last_error_at: null,
          last_error: null,
        },
      ],
    },
  ],
  tasks: [
    {
      key: "crypto_prices",
      name: "Crypto price update",
      enabled: true,
      running: false,
      last_started_at: "2026-10-04T09:00:00Z",
      last_finished_at: "2026-10-04T09:00:02Z",
      outcome: "ok",
      error: null,
      next_due_at: "2026-10-04T09:15:00Z",
    },
  ],
  scheduler_enabled: true,
  storage: {
    database_bytes: 52428800,
    crypto_daily_closes: 1200,
    security_daily_closes: 300,
    reference_rates: 90,
  },
};

describe("fetchHealthReport", () => {
  it("reads the report from the API's own origin", async () => {
    respondWith(200, report);

    await expect(fetchHealthReport()).resolves.toEqual(report);

    expect(fetch).toHaveBeenCalledWith("/api/health/report");
  });

  it("rejects an error status, naming it", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchHealthReport()).rejects.toThrow("500");
  });

  it("rejects a provider state outside the four the API states", async () => {
    respondWith(200, {
      ...report,
      providers: [{ ...report.providers[0], state: "down" }],
    });

    await expect(fetchHealthReport()).rejects.toThrow();
  });
});
