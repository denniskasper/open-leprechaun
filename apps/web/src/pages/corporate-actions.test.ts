import { describe, expect, it } from "vitest";
import type { CorporateAction } from "@/api/corporate-actions";
import { type ActionDraft, statedAction, termsOf } from "./corporate-actions";

function draft(overrides: Partial<ActionDraft> = {}): ActionDraft {
  return {
    kind: "split",
    instrumentId: "7",
    effectiveOn: "2031-05-02",
    unitsNew: "2",
    unitsOld: "1",
    targetInstrumentId: "",
    basisShare: "",
    amountPerUnit: "",
    note: "",
    ...overrides,
  };
}

function action(overrides: Partial<CorporateAction> = {}): CorporateAction {
  return {
    id: 1,
    kind: "split",
    instrument_id: 7,
    effective_at: "2031-05-02T00:00:00Z",
    units_new: "2",
    units_old: "1",
    target_instrument_id: null,
    basis_share: null,
    amount_per_unit_eur: null,
    note: null,
    reviewed_at: null,
    needs_review: false,
    lots: [],
    ...overrides,
  };
}

const symbolOf = (id: number) => (id === 8 ? "SHL" : "SAP");

describe("statedAction", () => {
  it("states a split with its ratio and nothing else", () => {
    expect(statedAction(draft({ basisShare: "0.5", amountPerUnit: "3" }))).toEqual({
      kind: "split",
      instrument_id: 7,
      effective_at: new Date("2031-05-02T00:00:00").toISOString(),
      units_new: "2",
      units_old: "1",
    });
  });

  it("waits while the ratio is missing, malformed or zero", () => {
    expect(statedAction(draft({ unitsNew: "" }))).toBeNull();
    expect(statedAction(draft({ unitsOld: "1,5" }))).toBeNull();
    expect(statedAction(draft({ unitsNew: "0.0" }))).toBeNull();
  });

  it("waits for an Instrument and a day", () => {
    expect(statedAction(draft({ instrumentId: "" }))).toBeNull();
    expect(statedAction(draft({ effectiveOn: "" }))).toBeNull();
  });

  it("states a capital return by its amount alone", () => {
    const stated = statedAction(draft({ kind: "capital_return", amountPerUnit: "0.75" }));

    expect(stated?.amount_per_unit_eur).toBe("0.75");
    expect(stated).not.toHaveProperty("units_new");
  });

  it("needs a target other than the Instrument itself for a merger", () => {
    expect(statedAction(draft({ kind: "merger" }))).toBeNull();
    expect(statedAction(draft({ kind: "merger", targetInstrumentId: "7" }))).toBeNull();
    expect(statedAction(draft({ kind: "merger", targetInstrumentId: "8" }))).toMatchObject({
      target_instrument_id: 8,
    });
  });

  it("needs a share of basis strictly below one for a spin-off", () => {
    const spinOff = { kind: "spin_off" as const, targetInstrumentId: "8" };

    expect(statedAction(draft({ ...spinOff, basisShare: "1" }))).toBeNull();
    expect(statedAction(draft({ ...spinOff, basisShare: "0.0" }))).toBeNull();
    expect(statedAction(draft({ ...spinOff, basisShare: "0.2" }))).toMatchObject({
      basis_share: "0.2",
    });
  });

  it("carries a note only when one was written", () => {
    expect(statedAction(draft({ note: "  " }))).not.toHaveProperty("note");
    expect(statedAction(draft({ note: " per broker letter " }))?.note).toBe("per broker letter");
  });
});

describe("termsOf", () => {
  it("names a split by its ratio, and a shrinking one as a reverse split", () => {
    expect(termsOf(action(), symbolOf)).toBe("2 for 1 split");
    expect(termsOf(action({ units_new: "1", units_old: "10" }), symbolOf)).toBe(
      "1 for 10 reverse split",
    );
  });

  it("names the target of a merger and a spin-off", () => {
    expect(
      termsOf(action({ kind: "merger", units_new: "1", units_old: "2", target_instrument_id: 8 }), symbolOf),
    ).toBe("1 for 2 into SHL");
    expect(
      termsOf(
        action({
          kind: "spin_off",
          units_new: "1",
          units_old: "4",
          target_instrument_id: 8,
          basis_share: "0.20",
        }),
        symbolOf,
      ),
    ).toBe("1 SHL for every 4 held · share of basis 0.2");
  });

  it("keeps the currency beside a capital return's amount", () => {
    const terms = termsOf(
      action({ kind: "capital_return", units_new: null, units_old: null, amount_per_unit_eur: "5" }),
      symbolOf,
    );

    expect(terms).toContain("€");
    expect(terms).toContain("per unit off the basis");
  });
});
