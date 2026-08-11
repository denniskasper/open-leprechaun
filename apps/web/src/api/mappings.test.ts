import { afterEach, describe, expect, it, vi } from "vitest";
import {
  emptyDraft,
  fetchColumnMappings,
  interpretMapping,
  previewMappedImport,
  saveColumnMapping,
} from "./mappings";

function respondWith(status: number, body?: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const interpretation = {
  columns: ["Datum", "Betrag"],
  rows: [
    {
      number: 1,
      external_id: "abc-1",
      occurred_at: "2026-07-01T12:30:00Z",
      type: "transfer_in",
      symbol: "BTC",
      quantity: "0.5",
      fee_quantity: null,
      note: null,
      left_out: null,
      problems: [],
    },
  ],
  row_count: 1,
  defects: [],
  type_values_seen: ["Einzahlung"],
};

describe("interpretMapping", () => {
  it("parses the interpretation, quantities staying strings", async () => {
    respondWith(200, interpretation);

    await expect(
      interpretMapping({ content: "whatever", mapping: emptyDraft() }),
    ).resolves.toEqual(interpretation);
  });

  it("refuses a response that is not the contract", async () => {
    respondWith(200, { columns: "not-a-list" });

    await expect(interpretMapping({ content: "x", mapping: emptyDraft() })).rejects.toThrow();
  });
});

const savedMapping = {
  id: 3,
  name: "Some venue",
  mapping: { ...emptyDraft(), occurred_at: "Datum" },
  created_at: "2026-08-11T09:00:00Z",
};

describe("fetchColumnMappings", () => {
  it("parses the saved mappings", async () => {
    respondWith(200, [savedMapping]);

    await expect(fetchColumnMappings()).resolves.toEqual([savedMapping]);
  });
});

describe("saveColumnMapping", () => {
  it("answers the saved mapping back", async () => {
    respondWith(201, savedMapping);

    await expect(
      saveColumnMapping({ name: "Some venue", mapping: savedMapping.mapping }),
    ).resolves.toEqual(savedMapping);
  });

  it("carries the API's own sentence on a refusal", async () => {
    respondWith(422, { detail: "No column is assigned to the timestamp." });

    await expect(saveColumnMapping({ name: "Half", mapping: emptyDraft() })).rejects.toThrow(
      "No column is assigned to the timestamp.",
    );
  });
});

describe("previewMappedImport", () => {
  it("carries the API's own sentence on a refused file", async () => {
    respondWith(422, { detail: "The file has no column 'Betrag'." });

    await expect(
      previewMappedImport({ account_id: 1, content: "x", mapping: emptyDraft() }),
    ).rejects.toThrow("The file has no column 'Betrag'.");
  });
});
