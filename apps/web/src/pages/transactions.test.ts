import { describe, expect, it } from "vitest";
import { reconstructedSchema, transactionTypeSchema, type LegRole } from "@/api/transactions";
import {
  capitalIncomeOf,
  EMPTY_WITHHELD,
  isPositiveDecimal,
  legTemplate,
  occurredAtWords,
  RECONSTRUCTED_WORDS,
  signOf,
  TYPE_VOCABULARY,
  withLegRemoved,
  withheldDefect,
  withheldWords,
  withToggled,
  type DraftLeg,
} from "./transactions";

describe("TYPE_VOCABULARY", () => {
  it("speaks every type the API knows, and no other", () => {
    expect(Object.keys(TYPE_VOCABULARY).sort()).toEqual([...transactionTypeSchema.options].sort());
  });
});

describe("legTemplate", () => {
  it("opens a trade with both sides, so the balance is on the form from the start", () => {
    expect(legTemplate("trade")).toEqual(["out", "in"]);
  });

  it("opens outbound events with what left and inbound ones with what arrived", () => {
    expect(legTemplate("transfer_out")).toEqual(["out"]);
    expect(legTemplate("spend")).toEqual(["out"]);
    expect(legTemplate("transfer_in")).toEqual(["in"]);
    expect(legTemplate("staking_reward")).toEqual(["in"]);
    expect(legTemplate("dividend")).toEqual(["in"]);
  });

  it("opens a standalone fee with the one leg it is", () => {
    expect(legTemplate("fee")).toEqual(["fee"]);
  });

  it("opens an Opening Balance with the one position that already existed", () => {
    expect(legTemplate("opening_balance")).toEqual(["in"]);
  });
});

describe("RECONSTRUCTED_WORDS", () => {
  it("speaks both variants the API knows, and no other", () => {
    expect(Object.keys(RECONSTRUCTED_WORDS).sort()).toEqual(
      [...reconstructedSchema.options].sort(),
    );
  });

  it("explains what each choice affects and recommends conservative dating only when the date is unknown", () => {
    // The difference decides a tax outcome, so the copy is load-bearing: the
    // known date carries the exemption; the conservative date is for a date
    // genuinely unknown, and would manufacture tax where the date is known.
    const dateKnown = RECONSTRUCTED_WORDS.basis;
    const bothReconstructed = RECONSTRUCTED_WORDS.basis_and_date;

    expect(dateKnown.explanation).toContain("used as given");
    expect(dateKnown.explanation).toContain("exempt");
    expect(bothReconstructed.explanation).toContain("start of known history");
    expect(bothReconstructed.explanation).toContain("genuinely unknown");
    expect(RECONSTRUCTED_WORDS.basis.marker).not.toEqual(bothReconstructed.marker);
  });
});

describe("occurredAtWords", () => {
  it("names the instant for what it is on each variant", () => {
    expect(occurredAtWords("trade", null)).toBe("Occurred at");
    expect(occurredAtWords("opening_balance", "basis")).toBe("Acquired at");
    expect(occurredAtWords("opening_balance", "basis_and_date")).toBe("Known history begins at");
  });
});

describe("isPositiveDecimal", () => {
  it("accepts fixed-point decimals", () => {
    expect(isPositiveDecimal("0.00000001")).toBe(true);
    expect(isPositiveDecimal("100.00")).toBe(true);
    expect(isPositiveDecimal("42")).toBe(true);
  });

  it("refuses zero, signs, exponents and separators a float would smuggle in", () => {
    expect(isPositiveDecimal("0")).toBe(false);
    expect(isPositiveDecimal("0.000")).toBe(false);
    expect(isPositiveDecimal("-1")).toBe(false);
    expect(isPositiveDecimal("1e8")).toBe(false);
    expect(isPositiveDecimal("1,5")).toBe(false);
    expect(isPositiveDecimal("")).toBe(false);
    expect(isPositiveDecimal(".5")).toBe(false);
  });
});

function draft(role: LegRole, chargedAgainst: number | null = null): DraftLeg {
  return { key: 0, role, accountId: "1", instrumentId: "1", quantity: "1", chargedAgainst };
}

describe("withLegRemoved", () => {
  it("drops the attachment of a fee whose target was removed", () => {
    const legs = [draft("out"), draft("in"), draft("fee", 1)];

    const remaining = withLegRemoved(legs, 1);

    expect(remaining.map((leg) => leg.role)).toEqual(["out", "fee"]);
    expect(remaining[1]?.chargedAgainst).toBeNull();
  });

  it("follows a target down a position when an earlier leg goes", () => {
    const legs = [draft("out"), draft("in"), draft("fee", 1)];

    const remaining = withLegRemoved(legs, 0);

    expect(remaining[1]?.chargedAgainst).toBe(0);
  });

  it("leaves an attachment before the removed position untouched", () => {
    const legs = [draft("out"), draft("fee", 0), draft("in")];

    const remaining = withLegRemoved(legs, 2);

    expect(remaining[1]?.chargedAgainst).toBe(0);
  });
});

describe("signOf", () => {
  it("gains an inflow and spends everything else", () => {
    expect(signOf("in")).toBe("+");
    expect(signOf("out")).toBe("−");
    expect(signOf("fee")).toBe("−");
  });
});

describe("withToggled", () => {
  it("adds an absent id and removes a present one, without touching the original", () => {
    const none: ReadonlySet<number> = new Set();

    const one = withToggled(none, 7);
    expect([...one]).toEqual([7]);

    const back = withToggled(one, 7);
    expect(back.size).toBe(0);
    expect([...one]).toEqual([7]);
    expect(none.size).toBe(0);
  });
});

describe("capitalIncomeOf", () => {
  it("declares nothing on a type that is not income from capital", () => {
    expect(capitalIncomeOf("trade", { ...EMPTY_WITHHELD, kapitalertragsteuer: "5" })).toBeNull();
  });

  it("declares nothing where nothing was entered, so a plain receipt stays plain", () => {
    expect(capitalIncomeOf("dividend", EMPTY_WITHHELD)).toBeNull();
  });

  it("states blank amounts as zero and keeps the entered strings exact", () => {
    expect(
      capitalIncomeOf("dividend", {
        ...EMPTY_WITHHELD,
        payerId: "7",
        foreignWithholding: "15.30",
        sourceCountry: "us",
      }),
    ).toEqual({
      paying_instrument_id: 7,
      foreign_withholding: "15.30",
      source_country: "US",
      kapitalertragsteuer: "0",
      solidarity_surcharge: "0",
      church_tax: "0",
    });
  });
});

describe("withheldDefect", () => {
  it("accepts an empty declaration and a complete one", () => {
    expect(withheldDefect("dividend", EMPTY_WITHHELD)).toBeNull();
    expect(
      withheldDefect("dividend", {
        ...EMPTY_WITHHELD,
        foreignWithholding: "15",
        sourceCountry: "US",
      }),
    ).toBeNull();
  });

  it("keeps a foreign withholding tax and its source country together", () => {
    expect(withheldDefect("dividend", { ...EMPTY_WITHHELD, foreignWithholding: "15" })).toMatch(
      /source country/,
    );
    expect(withheldDefect("dividend", { ...EMPTY_WITHHELD, sourceCountry: "US" })).toMatch(
      /source country/,
    );
  });

  it("asks a distribution for the fund that paid it", () => {
    expect(withheldDefect("distribution", EMPTY_WITHHELD)).toMatch(/fund/);
    expect(withheldDefect("distribution", { ...EMPTY_WITHHELD, payerId: "7" })).toBeNull();
  });

  it("refuses an amount that is not a fixed-point decimal", () => {
    expect(withheldDefect("interest", { ...EMPTY_WITHHELD, churchTax: "1,5" })).toMatch(/decimal/);
  });

  it("judges nothing on a type that declares nothing", () => {
    expect(withheldDefect("trade", { ...EMPTY_WITHHELD, churchTax: "1,5" })).toBeNull();
  });
});

describe("withheldWords", () => {
  const nothing = {
    paying_instrument_id: null,
    foreign_withholding: "0",
    source_country: null,
    kapitalertragsteuer: "0",
    solidarity_surcharge: "0",
    church_tax: "0",
  };

  it("names each component taken, every amount beside its currency", () => {
    const words = withheldWords(
      { ...nothing, foreign_withholding: "15", source_country: "US", kapitalertragsteuer: "10" },
      "USD",
    );

    expect(words).toContain("Quellensteuer US 15 USD");
    expect(words).toContain("KESt 10 USD");
    expect(words).not.toContain("Soli");
  });

  it("says so where a declaration took nothing", () => {
    expect(withheldWords(nothing, "EUR")).toBe("nothing withheld");
  });
});
