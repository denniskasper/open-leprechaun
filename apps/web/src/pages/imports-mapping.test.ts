import { describe, expect, it } from "vitest";
import { emptyDraft, type MappingDraft } from "@/api/mappings";
import { transactionTypeSchema } from "@/api/transactions";
import {
  FIXED,
  MAPPED_TYPES,
  UNMAPPED,
  chooseSource,
  rowCountWords,
  sourceChoice,
  translationRows,
  withTranslation,
} from "./imports-mapping";

describe("MAPPED_TYPES", () => {
  it("is the transaction vocabulary minus the shapes one file row cannot state", () => {
    // A trade's two sides never fit one mapped row, and an opening balance
    // is the Admin's declaration, never an import's. Pinned against the
    // API's own vocabulary so the two lists cannot drift apart silently.
    const singleRole = transactionTypeSchema.options.filter(
      (type) => type !== "trade" && type !== "opening_balance",
    );
    expect([...MAPPED_TYPES]).toEqual(singleRole);
  });
});

function draft(overrides: Partial<MappingDraft> = {}): MappingDraft {
  return { ...emptyDraft(), ...overrides };
}

describe("chooseSource", () => {
  it("assigns a column and clears the fixed value — exactly one of the two", () => {
    const chosen = chooseSource(draft({ fixed_symbol: "BTC" }), "symbol", "Coin");

    expect(chosen.symbol).toBe("Coin");
    expect(chosen.fixed_symbol).toBeNull();
  });

  it("switches to a fixed value and clears the column", () => {
    const chosen = chooseSource(draft({ type: "Typ" }), "type", FIXED);

    expect(chosen.type).toBeNull();
    expect(chosen.fixed_type).toBe("");
  });

  it("clears both on the empty choice", () => {
    const chosen = chooseSource(draft({ symbol: "Coin" }), "symbol", "");

    expect(chosen.symbol).toBeNull();
    expect(chosen.fixed_symbol).toBeNull();
  });
});

describe("sourceChoice", () => {
  it("mirrors whichever source the draft declares", () => {
    expect(sourceChoice(draft({ symbol: "Coin" }), "symbol")).toBe("Coin");
    expect(sourceChoice(draft({ fixed_symbol: "BTC" }), "symbol")).toBe(FIXED);
    expect(sourceChoice(draft(), "symbol")).toBe("");
    // A fixed type still being chosen ("") is already the fixed source.
    expect(sourceChoice(draft({ fixed_type: "" }), "type")).toBe(FIXED);
  });
});

describe("withTranslation", () => {
  it("maps a type value, remaps it, and forgets it again", () => {
    const mapped = withTranslation(draft(), "Einzahlung", "transfer_in");
    expect(mapped.type_values).toEqual({ Einzahlung: "transfer_in" });

    const leftOut = withTranslation(mapped, "Einzahlung", "");
    expect(leftOut.type_values).toEqual({ Einzahlung: "" });

    const forgotten = withTranslation(leftOut, "Einzahlung", UNMAPPED);
    expect(forgotten.type_values).toEqual({});
  });
});

describe("translationRows", () => {
  it("unions what the file carries with what the mapping declares", () => {
    // A saved mapping reused against a new file keeps its rows even for
    // values this file happens not to show.
    expect(translationRows(["Kauf", "Verkauf"], { Verkauf: "spend", Storno: "" })).toEqual([
      "Kauf",
      "Storno",
      "Verkauf",
    ]);
  });
});

describe("rowCountWords", () => {
  it("counts the file's rows, singular and plural", () => {
    expect(rowCountWords(1, "en")).toBe("1 row in the file");
    expect(rowCountWords(120, "en")).toBe("120 rows in the file");
  });
});
