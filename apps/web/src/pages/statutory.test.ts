import { describe, expect, it } from "vitest";
import {
  churchTaxSchema,
  filingStatusSchema,
  statutoryKeySchema,
  statutorySchema,
  type StatutoryKeyDefinition,
  type StatutoryYear,
} from "@/api/statutory";
import {
  CHURCH_WORDS,
  displayValue,
  FILING_WORDS,
  KEY_WORDS,
  percentWords,
  rowsForYear,
} from "./statutory";

describe("KEY_WORDS", () => {
  it("speaks every key the API knows, and no other", () => {
    expect(Object.keys(KEY_WORDS).sort()).toEqual([...statutoryKeySchema.options].sort());
  });
});

describe("the election vocabularies", () => {
  it("speak every choice the API knows, and no other", () => {
    expect(Object.keys(FILING_WORDS).sort()).toEqual([...filingStatusSchema.options].sort());
    expect(Object.keys(CHURCH_WORDS).sort()).toEqual([...churchTaxSchema.options].sort());
  });
});

describe("percentWords", () => {
  it("moves the decimal point two places without ever touching a float", () => {
    expect(percentWords("0.25")).toBe("25");
    expect(percentWords("0.055")).toBe("5.5");
    expect(percentWords("0.0229")).toBe("2.29");
    expect(percentWords("0.08")).toBe("8");
    expect(percentWords("1")).toBe("100");
    expect(percentWords("0.0320")).toBe("3.2");
  });

  it("keeps digits a float would mangle", () => {
    expect(percentWords("0.123456789012345678901")).toBe("12.3456789012345678901");
  });
});

describe("displayValue", () => {
  it("renders a rate as a percentage and an amount with its currency adjacent", () => {
    expect(displayValue("rate", "0.055", "en-US")).toBe("5.5 %");
    expect(displayValue("eur", "1000", "en-US")).toBe("€1,000");
    expect(displayValue("eur", "256", "de-DE")).toContain("€");
  });
});

const KEYS: StatutoryKeyDefinition[] = [
  { key: "flat_rate", unit: "rate", required: true },
  { key: "saver_allowance_single", unit: "eur", required: true },
  { key: "loss_cap_termingeschaefte", unit: "eur", required: false },
  { key: "opening_carryforward_aktien", unit: "eur", required: false },
];

describe("rowsForYear", () => {
  it("shows every key: set with its value, required gaps as missing, optional gaps as absent", () => {
    const year: StatutoryYear = {
      year: 2031,
      values: [{ key: "flat_rate", value: "0.25", source: "§ 32d Abs. 1 Satz 1 EStG" }],
      missing: ["saver_allowance_single"],
    };

    const rows = rowsForYear(KEYS, year);

    expect(rows.map((row) => [row.definition.key, row.state])).toEqual([
      ["flat_rate", "set"],
      ["saver_allowance_single", "missing"],
      ["loss_cap_termingeschaefte", "absent"],
      ["opening_carryforward_aktien", "absent"],
    ]);
    expect(rows[0]?.value?.source).toBe("§ 32d Abs. 1 Satz 1 EStG");
  });
});

describe("absence wording", () => {
  it("says what an absent optional value means — uncapped for a cap, zero for an opening carryforward", () => {
    expect(KEY_WORDS.loss_cap_termingeschaefte.absent).toContain("uncapped");
    expect(KEY_WORDS.opening_carryforward_aktien.absent).toContain("none");
  });
});

describe("statutorySchema", () => {
  it("refuses a value that crossed JSON as a number", () => {
    const answer = {
      filing_status: "single",
      church_tax: "none",
      keys: [{ key: "flat_rate", unit: "rate", required: true }],
      years: [
        {
          year: 2026,
          values: [{ key: "flat_rate", value: 0.25, source: "§ 32d EStG" }],
          missing: [],
        },
      ],
    };

    expect(statutorySchema.safeParse(answer).success).toBe(false);
    const asString = structuredClone(answer) as unknown as { years: { values: { value: unknown }[] }[] };
    asString.years[0]!.values[0]!.value = "0.25";
    expect(statutorySchema.safeParse(asString).success).toBe(true);
  });
});
