/**
 * Locale-aware formatting, defined once so no screen invents its own.
 *
 * The rule from the design foundation: an amount of money is always rendered
 * with its currency adjacent — there is no way to get a bare number out of
 * this module for money. German tax figures stay in EUR; which locale renders
 * them is presentation and defaults to the browser's.
 */

interface MoneyOptions {
  /** Raise above the currency's default when sub-cent precision matters. */
  maxFractionDigits?: number;
}

export function formatMoney(
  amount: number,
  currency: string,
  locale?: string,
  options: MoneyOptions = {},
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    // "halfExpand" is half away from zero — the rounding German tax arithmetic
    // expects, and Intl's default; named here so nobody has to check.
    roundingMode: "halfExpand",
    ...(options.maxFractionDigits !== undefined && {
      maximumFractionDigits: options.maxFractionDigits,
    }),
  }).format(amount);
}

/** Quantities of an asset, not money: up to eight fraction digits, no unit. */
export function formatNumber(value: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 8 }).format(value);
}

export function formatTimestamp(epochMs: number, locale?: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(epochMs);
}
