import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchImportBatches, reverseImportBatch } from "./imports";

const batch = {
  id: 7,
  source: "kraken-csv",
  label: "trades-2026.csv",
  account_id: 3,
  created_at: "2026-03-14T12:00:00Z",
  rows: 41,
  overridden: 2,
};

function respondWith(status: number, body?: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchImportBatches", () => {
  it("parses the batches, counts included", async () => {
    respondWith(200, [batch]);

    await expect(fetchImportBatches()).resolves.toEqual([batch]);
  });

  it("refuses a response that is not the contract", async () => {
    respondWith(200, [{ id: 7 }]);

    await expect(fetchImportBatches()).rejects.toThrow();
  });

  it("names the status when the API fails", async () => {
    respondWith(500);

    await expect(fetchImportBatches()).rejects.toThrow("500");
  });
});

describe("reverseImportBatch", () => {
  it("resolves on 204 and reports the API's own sentence on refusal", async () => {
    respondWith(204);
    await expect(reverseImportBatch(7)).resolves.toBeUndefined();

    respondWith(404, { detail: "No such Import Batch." });
    await expect(reverseImportBatch(7)).rejects.toThrow("No such Import Batch.");
  });
});
