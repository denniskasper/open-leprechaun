import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLedgerExport, ledgerExportFileUrl } from "./ledger-export";

const summary = {
  format: "cointracking",
  filename: "open-leprechaun-ledger-cointracking.csv",
  row_count: 3,
  left_out: [
    {
      transaction_id: 7,
      type: "trade",
      occurred_at: "2031-03-14T12:30:05Z",
      reason: "SAP is a security, and CoinTracking holds only coins and currencies.",
    },
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

describe("fetchLedgerExport", () => {
  it("reads what the file carries and what it leaves out", async () => {
    respondWith(200, summary);

    await expect(fetchLedgerExport()).resolves.toEqual(summary);

    expect(fetch).toHaveBeenCalledWith("/api/ledger-export");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchLedgerExport()).rejects.toThrow("500");
  });

  it("rejects a left-out Transaction that gives no reason", async () => {
    respondWith(200, { ...summary, left_out: [{ ...summary.left_out[0], reason: undefined }] });

    await expect(fetchLedgerExport()).rejects.toThrow();
  });

  it("rejects a format it does not know how to describe", async () => {
    respondWith(200, { ...summary, format: "koinly" });

    await expect(fetchLedgerExport()).rejects.toThrow();
  });
});

describe("ledgerExportFileUrl", () => {
  it("points at the file of the format the summary named", () => {
    expect(ledgerExportFileUrl("cointracking")).toBe("/api/ledger-export/cointracking.csv");
  });
});
