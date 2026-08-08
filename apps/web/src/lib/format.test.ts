import { describe, expect, it } from "vitest";
import { formatMoney, formatNumber, formatQuantity, formatTimestamp } from "./format";

// The ticket's rule: numbers are formatted per locale and money always carries
// its currency adjacent — a bare number must be impossible to produce.

describe("formatMoney", () => {
  it("formats EUR for a German locale with the symbol after the amount", () => {
    // de-DE uses a non-breaking space before the symbol.
    expect(formatMoney(1234.56, "EUR", "de-DE")).toBe("1.234,56 €");
  });

  it("formats EUR for a US locale with the symbol before the amount", () => {
    expect(formatMoney(1234.56, "EUR", "en-US")).toBe("€1,234.56");
  });

  it("keeps the sign attached to a negative amount", () => {
    expect(formatMoney(-42, "EUR", "de-DE")).toBe("-42,00 €");
  });

  it("shows currencies without a common symbol by their code", () => {
    // No symbol exists for CHF in de-DE; the code itself must appear.
    expect(formatMoney(10, "CHF", "de-DE")).toContain("CHF");
  });

  it("never drops sub-cent precision silently", () => {
    // Crypto EUR values can carry more than two decimals; the caller opts in.
    expect(formatMoney(0.000123, "EUR", "en-US", { maxFractionDigits: 6 })).toBe("€0.000123");
  });

  it("rounds half away from zero as German tax arithmetic expects", () => {
    expect(formatMoney(0.005, "EUR", "en-US")).toBe("€0.01");
    expect(formatMoney(-0.005, "EUR", "en-US")).toBe("-€0.01");
  });
});

describe("formatNumber", () => {
  it("formats quantities per locale", () => {
    expect(formatNumber(1234567.891, "de-DE")).toBe("1.234.567,891");
    expect(formatNumber(1234567.891, "en-US")).toBe("1,234,567.891");
  });

  it("keeps up to eight fraction digits for asset quantities", () => {
    expect(formatNumber(0.00012345, "en-US")).toBe("0.00012345");
  });
});

describe("formatQuantity", () => {
  it("groups the integer digits per locale and keeps the fraction verbatim", () => {
    expect(formatQuantity("1234567.891", "de-DE")).toBe("1.234.567,891");
    expect(formatQuantity("1234567.891", "en-US")).toBe("1,234,567.891");
  });

  it("keeps every fraction digit — a fixed-point string never meets a float", () => {
    expect(formatQuantity("0.000000000000000001", "en-US")).toBe("0.000000000000000001");
  });

  it("keeps the recorded scale, trailing zeros included", () => {
    expect(formatQuantity("100.00", "en-US")).toBe("100.00");
  });

  it("survives integer digits beyond float precision", () => {
    expect(formatQuantity("123456789012345678901", "en-US")).toBe("123,456,789,012,345,678,901");
  });
});

describe("formatTimestamp", () => {
  it("renders a wall-clock time for the given locale", () => {
    const noon = Date.UTC(2026, 0, 5, 12, 34, 56);
    expect(formatTimestamp(noon, "de-DE", "UTC")).toBe("05.01.2026, 12:34:56");
  });
});
