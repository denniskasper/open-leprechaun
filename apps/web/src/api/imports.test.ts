import { afterEach, describe, expect, it, vi } from "vitest";
import {
  commitCsvImport,
  fetchCsvConnectors,
  fetchImportBatches,
  previewCsvImport,
  reverseImportBatch,
} from "./imports";

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

const connector = {
  connector: "bitbox",
  name: "BitBox",
  expects: "The transactions CSV the BitBoxApp exports for one account.",
  timezone: "Europe/Berlin",
};

const preview = {
  to_create: [{ external_id: "tx-1", type: "transfer_in", occurred_at: "2026-03-14T12:00:00Z" }],
  duplicates: 1,
  duplicate_external_ids: ["tx-0"],
  skipped: [{ external_id: "tx-2", reason: "A transfer in records what arrived." }],
  new_instruments: [],
  warnings: ["1 unconfirmed transaction left out — not facts yet."],
};

const file = { connector: "bitbox", account_id: 3, content: "Time,Type\n" };

describe("fetchCsvConnectors", () => {
  it("parses the connectors the registry serves", async () => {
    respondWith(200, [connector]);

    await expect(fetchCsvConnectors()).resolves.toEqual([connector]);
  });

  it("refuses a response that is not the contract", async () => {
    respondWith(200, [{ connector: "bitbox" }]);

    await expect(fetchCsvConnectors()).rejects.toThrow();
  });
});

describe("previewCsvImport", () => {
  it("parses the preview, warnings included", async () => {
    respondWith(200, preview);

    await expect(previewCsvImport(file)).resolves.toEqual(preview);
  });

  it("reports the API's own sentence when the file is refused", async () => {
    respondWith(422, { detail: "This is not a BitBoxApp export." });

    await expect(previewCsvImport(file)).rejects.toThrow("This is not a BitBoxApp export.");
  });
});

describe("commitCsvImport", () => {
  it("parses what the commit did", async () => {
    const committed = {
      batch_id: 9,
      created: 1,
      duplicates: 1,
      skipped: 1,
      instruments_created: 0,
    };
    respondWith(201, committed);

    await expect(commitCsvImport({ ...file, label: "export.csv" })).resolves.toEqual(committed);
  });

  it("reports the API's own sentence when another source is authoritative", async () => {
    respondWith(409, { detail: "'bitbox:3' is authoritative for this Account." });

    await expect(commitCsvImport({ ...file, label: "export.csv" })).rejects.toThrow(
      "'bitbox:3' is authoritative for this Account.",
    );
  });
});
