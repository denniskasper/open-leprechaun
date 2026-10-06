import { describe, expect, it } from "vitest";
import {
  formatAssetAmount,
  formatEur,
  formatMoney,
  formatMoneyExact,
  formatMoneyRounded,
  formatNumber,
  formatBytes,
  formatPercent,
  formatPercentExact,
  formatPrice,
  formatQuantity,
  formatRoundedAssetAmount,
  formatRoundedQuantity,
  formatRoundedSignedAssetAmount,
  formatRoundedSignedQuantity,
  formatSignedAssetAmount,
  formatSignedPercentExact,
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

describe("formatQuantity below zero", () => {
  it("keeps the sign of a figure whose integer part is zero", () => {
    expect(formatQuantity("-0.5", "en-US")).toBe("-0.5");
    expect(formatQuantity("-98765.4", "en-US")).toBe("-98,765.4");
    expect(formatQuantity("-1234.5", "de-DE")).toBe("-1.234,5");
  });

  it("writes no sign on a zero, however it arrived", () => {
    expect(formatQuantity("-0.00", "en-US")).toBe("0.00");
  });
});

describe("formatAssetAmount", () => {
  it("keeps the asset beside its amount — never a bare number", () => {
    expect(formatAssetAmount("1234.5", "USDC", "en-US")).toBe("1,234.5 USDC");
    expect(formatAssetAmount("-0.25", "USDC", "en-US")).toBe("-0.25 USDC");
  });
});

describe("formatSignedAssetAmount", () => {
  it("states the direction in the figure, with the asset beside it", () => {
    expect(formatSignedAssetAmount("346", "USDT", "en-US")).toBe("+346 USDT");
    expect(formatSignedAssetAmount("-4.20", "USDC", "en-US")).toBe("−4.20 USDC");
    expect(formatSignedAssetAmount("0", "USDC", "en-US")).toBe("0 USDC");
  });
});

describe("formatPercentExact", () => {
  it("states a share to two decimals, as a venue states its ratios", () => {
    expect(formatPercentExact("7.5", "en-US")).toBe("750.00%");
    expect(formatPercentExact("0.02", "de-DE")).toBe("2,00\u00a0%");
    expect(formatPercentExact("12.3456", "de-DE")).toBe("1.234,56\u00a0%");
  });

  it("works on the digits, so no float can bend the figure", () => {
    // 0.145 is not representable in binary; a float would state 14.49 %.
    expect(formatPercentExact("0.14495", "en-US")).toBe("14.50%");
    expect(formatPercentExact("0.000049", "en-US")).toBe("0.00%");
    expect(formatPercentExact("0.00005", "en-US")).toBe("0.01%");
  });
});

describe("formatSignedPercentExact", () => {
  it("puts the direction in the figure", () => {
    expect(formatSignedPercentExact("-0.0425", "en-US")).toBe("−4.25%");
    expect(formatSignedPercentExact("0.02", "en-US")).toBe("+2.00%");
    expect(formatSignedPercentExact("0", "en-US")).toBe("0.00%");
    expect(formatSignedPercentExact("-0.00001", "en-US")).toBe("0.00%");
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

// A list rounds for reading; the digits as stated stay with the verbatim
// formatters, for forms, reconciliations and tax figures.

describe("formatRoundedAssetAmount", () => {
  it("reads money and stablecoins to the cent, half away from zero", () => {
    expect(formatRoundedAssetAmount("56.921676", "USDC", "en-US")).toBe("56.92 USDC");
    expect(formatRoundedAssetAmount("5.695", "USDC", "en-US")).toBe("5.70 USDC");
    expect(formatRoundedAssetAmount("-5.695", "USDC", "en-US")).toBe("-5.70 USDC");
    expect(formatRoundedAssetAmount("1234.999", "EUR", "en-US")).toBe("1,235 EUR");
    expect(formatRoundedAssetAmount("100", "USDC", "en-US")).toBe("100 USDC");
  });

  it("reads a coin to eight places, so two would not flatten it", () => {
    expect(formatRoundedAssetAmount("0.00041", "BTC", "en-US")).toBe("0.00041 BTC");
    expect(formatRoundedAssetAmount("1.234567891234", "ETH", "en-US")).toBe("1.23456789 ETH");
    // A ticker that spells a currency code — silver, Mantle — is still an asset.
    expect(formatRoundedAssetAmount("2.0412", "XAG", "en-US")).toBe("2.0412 XAG");
    expect(formatRoundedAssetAmount("1.239", "MNT", "en-US")).toBe("1.239 MNT");
    expect(formatRoundedAssetAmount("1234.6", "JPY", "en-US")).toBe("1,235 JPY");
  });

  it("never reads an amount that is not zero as zero", () => {
    expect(formatRoundedAssetAmount("0.004", "USDC", "en-US")).toBe("0.004 USDC");
    expect(formatRoundedAssetAmount("0.00049", "USDC", "en-US")).toBe("0.0005 USDC");
    expect(formatRoundedAssetAmount("0.000000000123", "ETH", "en-US")).toBe("0.0000000001 ETH");
    expect(formatRoundedAssetAmount("0.000", "USDC", "en-US")).toBe("0 USDC");
    // A carry into the widened places gives them back.
    expect(formatRoundedAssetAmount("0.0096", "USDC", "en-US")).toBe("0.01 USDC");
    expect(formatRoundedAssetAmount("0.00096", "USDC", "en-US")).toBe("0.001 USDC");
  });

  it("works on the digits, so no float can bend the figure", () => {
    // 1.005 is not representable in binary; a float would state 1 USDC.
    expect(formatRoundedAssetAmount("1.005", "USDC", "en-US")).toBe("1.01 USDC");
    expect(formatRoundedAssetAmount("123456789012345678.999", "USDC", "en-US")).toBe(
      "123,456,789,012,345,679 USDC",
    );
  });
});

describe("formatRoundedSignedAssetAmount", () => {
  it("keeps the direction in the rounded figure", () => {
    expect(formatRoundedSignedAssetAmount("-4.2049", "USDC", "en-US")).toBe("−4.20 USDC");
    expect(formatRoundedSignedAssetAmount("0.126", "USDC", "en-US")).toBe("+0.13 USDC");
    expect(formatRoundedSignedAssetAmount("-0.004", "USDC", "en-US")).toBe("−0.004 USDC");
  });
});

describe("formatRoundedQuantity", () => {
  it("reads to eight places where no asset is named", () => {
    expect(formatRoundedQuantity("500.000000004", undefined, "de-DE")).toBe("500");
    expect(formatRoundedQuantity("1234.5", undefined, "de-DE")).toBe("1.234,5");
    expect(formatRoundedSignedQuantity("-0.1234567891", undefined, "en-US")).toBe("−0.12345679");
  });
});

describe("formatMoneyRounded", () => {
  it("reads a venue's long dollar value to the cent, padded so a column aligns", () => {
    expect(formatMoneyRounded("248.20000000000002", "USD", "en-US")).toBe("$248.20");
    expect(formatMoneyRounded("125.4804", "USD", "en-US")).toBe("$125.48");
    expect(formatMoneyRounded("-125.485", "USD", "en-US")).toBe("-$125.49");
    expect(formatMoneyRounded("0.004", "USD", "en-US")).toBe("$0.004");
    expect(formatMoneyRounded("0.0096", "USD", "en-US")).toBe("$0.01");
  });
});

describe("formatPrice", () => {
  it("reads two decimals at one or above", () => {
    expect(formatPrice("30.554649471486155", "en-US")).toBe("30.55");
    expect(formatPrice("61.51", "en-US")).toBe("61.51");
    expect(formatPrice("63", "en-US")).toBe("63");
  });

  it("reads four significant digits below one, so mark and entry stay apart", () => {
    expect(formatPrice("0.4964", "en-US")).toBe("0.4964");
    expect(formatPrice("0.501304", "en-US")).toBe("0.5013");
    expect(formatPrice("0.254899135927236", "en-US")).toBe("0.2549");
    expect(formatPrice("0.000012345678", "en-US")).toBe("0.00001235");
  });
});
