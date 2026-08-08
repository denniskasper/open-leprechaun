import { describe, expect, it } from "vitest";
import { transactionTypeSchema, type LegRole } from "@/api/transactions";
import {
  isPositiveDecimal,
  legTemplate,
  signOf,
  TYPE_VOCABULARY,
  withLegRemoved,
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
