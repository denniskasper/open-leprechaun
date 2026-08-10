import { describe, expect, it } from "vitest";
import type { ImportBatch } from "@/api/imports";
import { rowsWords } from "./imports";

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
