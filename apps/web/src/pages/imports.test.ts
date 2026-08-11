import { describe, expect, it } from "vitest";
import type { CommittedImport, CsvConnector, ImportBatch } from "@/api/imports";
import { committedWords, rowsWords, timezoneWords } from "./imports";

function batch(rows: number, overridden: number): ImportBatch {
  return {
    id: 1,
    source: "kraken-csv",
    label: "trades.csv",
    account_id: 3,
    created_at: "2026-03-14T12:00:00Z",
    rows,
    overridden,
  };
}

describe("rowsWords", () => {
  it("counts the rows, singular and plural", () => {
    expect(rowsWords(batch(1, 0))).toBe("1 row");
    expect(rowsWords(batch(41, 0))).toBe("41 rows");
  });

  it("names how many the Admin has taken over, only when any", () => {
    expect(rowsWords(batch(41, 2))).toBe("41 rows · 2 overridden");
  });
});

function connector(timezone: string): CsvConnector {
  return {
    connector: "bitbox",
    name: "BitBox",
    expects: "The transactions CSV the BitBoxApp exports.",
    timezone,
  };
}

describe("timezoneWords", () => {
  it("states UTC plainly when the venue writes UTC itself", () => {
    expect(timezoneWords(connector("UTC"))).toBe("Timestamps are read as UTC.");
  });

  it("declares a local-time export before anything is previewed", () => {
    expect(timezoneWords(connector("Europe/Berlin"))).toBe(
      "Bare timestamps are read as Europe/Berlin time and converted to UTC.",
    );
  });
});

function committed(overrides: Partial<CommittedImport>): CommittedImport {
  return {
    batch_id: 5,
    created: 3,
    duplicates: 0,
    skipped: 0,
    instruments_created: 0,
    ...overrides,
  };
}

describe("committedWords", () => {
  it("counts what landed, mentioning only what happened", () => {
    expect(committedWords(committed({}), "en")).toBe("3 rows created");
    expect(
      committedWords(committed({ duplicates: 2, skipped: 1, instruments_created: 1 }), "en"),
    ).toBe("3 rows created · 2 already known · 1 left out · 1 Instrument created");
  });

  it("says a pure re-import changed nothing", () => {
    expect(committedWords(committed({ batch_id: null, created: 0, duplicates: 4 }), "en")).toBe(
      "Nothing new — the ledger already knows everything in this file.",
    );
  });
});
