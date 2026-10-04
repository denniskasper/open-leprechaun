import { describe, expect, it } from "vitest";
import {
  formatEur,
  formatMoney,
  formatMoneyExact,
  formatNumber,
  formatBytes,
  formatPercent,
  formatQuantity,
  formatSignedQuantity,
  formatTimestamp,
} from "./format";

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

describe("formatMoneyExact", () => {
  it("puts a negative amount's sign where the locale does", () => {
    expect(formatMoneyExact("-2744.00", "EUR", "en-US")).toBe("-€2,744.00");
    expect(formatMoneyExact("-2744.00", "EUR", "de-DE")).toBe("-2.744,00\u00a0€");
  });

  it("puts the currency where the locale puts it, around the exact digits", () => {
    // de-DE uses a non-breaking space before the symbol.
    expect(formatMoneyExact("1234.56", "EUR", "de-DE")).toBe("1.234,56 €");
    expect(formatMoneyExact("1234.56", "EUR", "en-US")).toBe("€1,234.56");
  });

  it("keeps every digit — a fixed-point string never meets a float", () => {
    expect(formatMoneyExact("0.000000000000000001", "EUR", "en-US")).toBe(
      "€0.000000000000000001",
    );
    expect(formatMoneyExact("123456789012345678901", "EUR", "en-US")).toBe(
      "€123,456,789,012,345,678,901",
    );
  });

  it("keeps the recorded scale, trailing zeros included", () => {
    expect(formatMoneyExact("700.00", "EUR", "en-US")).toBe("€700.00");
    expect(formatMoneyExact("0", "EUR", "en-US")).toBe("€0");
  });
});

describe("formatEur", () => {
  it("states a whole amount to the cent, so a column of figures aligns", () => {
    expect(formatEur("2000", "de-DE")).toBe("2.000,00\u00a0€");
    expect(formatEur("131.9", "de-DE")).toBe("131,90\u00a0€");
  });

  it("keeps digits beyond the cent verbatim rather than rounding them away", () => {
    expect(formatEur("0.125", "de-DE")).toBe("0,125\u00a0€");
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

describe("formatPercent", () => {
  it("states a share per locale, to one decimal at most", () => {
    expect(formatPercent(0.4567, "en-US")).toBe("45.7%");
    expect(formatPercent(0.9, "en-US")).toBe("90%");
    expect(formatPercent(0.02, "de-DE")).toBe("2\u00a0%");
  });
});

describe("formatBytes", () => {
  it("states a size in the largest unit that keeps it above one", () => {
    expect(formatBytes(512, "en-US")).toBe("512 byte");
    expect(formatBytes(52428800, "en-US")).toBe("50 MB");
    expect(formatBytes(1610612736, "en-US")).toBe("1.5 GB");
    expect(formatBytes(1536, "de-DE")).toBe("1,5 kB");
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

describe("formatSignedQuantity", () => {
  it("signs a surplus at the venue, so the direction is never read off a colour", () => {
    expect(formatSignedQuantity("0.9", "en-US")).toBe("+0.9");
  });

  it("keeps the minus of a shortfall and the digits verbatim", () => {
    expect(formatSignedQuantity("-1234.50", "en-US")).toBe("−1,234.50");
  });

  it("leaves an exact agreement unsigned", () => {
    expect(formatSignedQuantity("0.0", "en-US")).toBe("0.0");
  });
});

describe("formatTimestamp", () => {
  it("renders a wall-clock time for the given locale", () => {
    const noon = Date.UTC(2026, 0, 5, 12, 34, 56);
    expect(formatTimestamp(noon, "de-DE", "UTC")).toBe("05.01.2026, 12:34:56");
  });
});
