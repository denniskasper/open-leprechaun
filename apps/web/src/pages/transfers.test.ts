import { describe, expect, it } from "vitest";
import type { TransferLeg } from "@/api/transfer-matches";
import { placeOf, trimDecimal, whatWentMissing } from "./transfers";

function leg(overrides: Partial<TransferLeg> = {}): TransferLeg {
  return {
    leg_id: 1,
    transaction_id: 1,
    occurred_at: "2026-02-02T18:30:00Z",
    note: null,
    quantity: "1",
    account_id: 1,
    account_name: "Main",
    platform_name: "Kraken",
    instrument_id: 7,
    instrument_symbol: "BTC",
    instrument_name: "Bitcoin",
    ...overrides,
  };
}

describe("placeOf", () => {
  it("names the side as the Admin knows it", () => {
    expect(placeOf(leg())).toBe("Kraken · Main");
  });
});

describe("trimDecimal", () => {
  it("drops insignificant fraction zeros without touching integers", () => {
    expect(trimDecimal("1.500")).toBe("1.5");
    expect(trimDecimal("1.000")).toBe("1");
    expect(trimDecimal("100")).toBe("100");
    expect(trimDecimal("0.004")).toBe("0.004");
  });
});

describe("whatWentMissing", () => {
  it("is silent when what left arrived whole, however it is spelled", () => {
    expect(whatWentMissing(leg({ quantity: "1.0" }), leg({ quantity: "1" }))).toBeNull();
  });

  it("names the gap a fee consumed, never through a float", () => {
    const sentence = whatWentMissing(
      leg({ quantity: "1" }),
      leg({ quantity: "0.99999999999999999" }),
    );
    expect(sentence).toContain("0.99999999999999999");
    expect(sentence).toContain("what the move consumed");
  });
});
