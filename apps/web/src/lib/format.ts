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

/**
 * An amount of money that arrives as a fixed-point decimal string — the
 * currency placed where the locale puts it, around digits that never pass
 * through a float. Intl is asked to format the number one only to learn the
 * locale's pattern; the digits themselves come from formatQuantity verbatim.
 */
export function formatMoneyExact(value: string, currency: string, locale?: string): string {
  const digits = "\u0000";
  const pattern = new Intl.NumberFormat(locale, { style: "currency", currency })
    .formatToParts(1)
    .map((part) =>
      part.type === "integer" || part.type === "decimal" || part.type === "fraction"
        ? digits
        : part.value,
    )
    .join("");
  return pattern.replace(/\0+/, formatQuantity(value, locale));
}

/** Quantities of an asset, not money: up to eight fraction digits, no unit. */
export function formatNumber(value: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 8 }).format(value);
}

/**
 * A fixed-point decimal string — the shape quantities cross the API in —
 * formatted for reading without ever passing through a float: the integer
 * digits are grouped per locale, the fraction digits kept verbatim, so a
 * satoshi and an eighteen-decimal token unit survive to the pixel.
 */
export function formatQuantity(value: string, locale?: string): string {
  const [integer = "0", fraction] = value.split(".");
  const grouped = new Intl.NumberFormat(locale).format(BigInt(integer));
  if (!fraction) {
    return grouped;
  }
  const separator =
    new Intl.NumberFormat(locale)
      .formatToParts(1.1)
      .find((part) => part.type === "decimal")?.value ?? ".";
  return grouped + separator + fraction;
}

export function formatTimestamp(epochMs: number, locale?: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(epochMs);
}
