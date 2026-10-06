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
  // A negative amount borrows the locale's own negative pattern, so the sign
  // sits where the locale puts it rather than between currency and digits.
  const negative = value.startsWith("-");
  const pattern = new Intl.NumberFormat(locale, { style: "currency", currency })
    .formatToParts(negative ? -1 : 1)
    .map((part) =>
      part.type === "integer" || part.type === "decimal" || part.type === "fraction"
        ? digits
        : part.value,
    )
    .join("");
  return pattern.replace(/\0+/, formatQuantity(negative ? value.slice(1) : value, locale));
}

/**
 * An EUR figure off the API stated to the cent, so a column of them aligns —
 * the digits never pass through a float, and any beyond the cent are kept
 * rather than rounded away.
 */
export function formatEur(value: string, locale?: string): string {
  const [integer = "0", fraction = ""] = value.split(".");
  return formatMoneyExact(`${integer}.${fraction.padEnd(2, "0")}`, "EUR", locale);
}

/** Quantities of an asset, not money: up to eight fraction digits, no unit. */
export function formatNumber(value: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 8 }).format(value);
}

/** A share of a whole (0–1) as a percentage, to one decimal at most. */
export function formatPercent(share: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(
    share,
  );
}

/**
 * A share stated as a fixed-point string (0.02 for 2 %) in hundredths of a
 * percent, worked out on the digits themselves — never through a float —
 * and rounded half away from zero where the share states more.
 */
function hundredthsOfAPercent(share: string): string {
  const negative = share.startsWith("-");
  const [integer = "0", fraction = ""] = (negative ? share.slice(1) : share).split(".");
  const scaled = BigInt(integer + fraction);
  const excess = fraction.length - 4;
  const hundredths =
    excess <= 0
      ? scaled * 10n ** BigInt(-excess)
      : (scaled + 10n ** BigInt(excess) / 2n) / 10n ** BigInt(excess);
  const digits = hundredths.toString().padStart(3, "0");
  const magnitude = `${digits.slice(0, -2)}.${digits.slice(-2)}`;
  return negative && hundredths !== 0n ? `-${magnitude}` : magnitude;
}

/** A figure set into the locale's own percent pattern, its digits untouched. */
function asPercent(figure: string, locale?: string): string {
  const digits = "\u0000";
  const pattern = new Intl.NumberFormat(locale, { style: "percent" })
    .formatToParts(1)
    .map((part) => (part.type === "integer" ? digits : part.value))
    .join("");
  return pattern.replace(/\0+/, figure);
}

/**
 * A share that arrives as a fixed-point string (0.02 for 2 %), to two
 * decimals — the precision a venue states its own ratios in — without ever
 * passing through a float.
 */
export function formatPercentExact(share: string, locale?: string): string {
  return asPercent(formatQuantity(hundredthsOfAPercent(share), locale), locale);
}

/** formatPercentExact with the direction in the figure — a share that can fall either side of zero. */
export function formatSignedPercentExact(share: string, locale?: string): string {
  return asPercent(formatSignedQuantity(hundredthsOfAPercent(share), locale), locale);
}

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

/** A size on disk, in the largest unit that keeps the figure at one or above. */
export function formatBytes(bytes: number, locale?: string): string {
  let unit = 0;
  let size = bytes;
  while (size >= 1024 && unit < BYTE_UNITS.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: BYTE_UNITS[unit],
    maximumFractionDigits: 1,
  }).format(size);
}

/**
 * A fixed-point decimal string — the shape quantities cross the API in —
 * formatted for reading without ever passing through a float: the integer
 * digits are grouped per locale, the fraction digits kept verbatim, so a
 * satoshi and an eighteen-decimal token unit survive to the pixel.
 */
export function formatQuantity(value: string, locale?: string): string {
  // The sign is carried apart from the digits: an integer part of zero
  // ("-0.5") has none of its own to lend the figure.
  const below = value.startsWith("-") && /[1-9]/.test(value);
  const [integer = "0", fraction] = (value.startsWith("-") ? value.slice(1) : value).split(".");
  const format = new Intl.NumberFormat(locale);
  const sign = below
    ? (format.formatToParts(-1).find((part) => part.type === "minusSign")?.value ?? "-")
    : "";
  const grouped = sign + format.format(BigInt(integer));
  if (!fraction) {
    return grouped;
  }
  const separator = format.formatToParts(1.1).find((part) => part.type === "decimal")?.value ?? ".";
  return grouped + separator + fraction;
}

/**
 * An amount of an asset that is no ISO currency — a coin, a stablecoin — with
 * its symbol beside it, as the money rule asks of every amount. The digits
 * stay verbatim, as formatQuantity keeps them.
 */
export function formatAssetAmount(value: string, symbol: string, locale?: string): string {
  return `${formatQuantity(value, locale)} ${symbol}`;
}

/** formatAssetAmount with the direction in the figure — a result, a funding payment. */
export function formatSignedAssetAmount(value: string, symbol: string, locale?: string): string {
  return `${formatSignedQuantity(value, locale)} ${symbol}`;
}

/**
 * A fixed-point decimal string rounded to `places` fraction digits, half away
 * from zero, on the digits themselves — never through a float.
 */
function roundDecimal(value: string, places: number): string {
  const negative = value.startsWith("-");
  const [integer = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
  let scaled = BigInt((integer || "0") + fraction.slice(0, places).padEnd(places, "0"));
  if ((fraction[places] ?? "0") >= "5") scaled += 1n;
  const digits = scaled.toString().padStart(places + 1, "0");
  const magnitude = places === 0 ? digits : `${digits.slice(0, -places)}.${digits.slice(-places)}`;
  return negative && scaled !== 0n ? `-${magnitude}` : magnitude;
}

/**
 * roundDecimal for reading: a figure below one is given as many places as
 * its first `significant` digits need, so an amount that is not zero never
 * reads as zero. The places it was widened by are given back where rounding
 * carried into them — 0.0096 reads 0.01, not 0.010.
 */
function roundForReading(value: string, places: number, significant = 1): string {
  const [integer = "0", fraction = ""] = value.replace("-", "").split(".");
  const leadingZeros = fraction.search(/[1-9]/);
  const widened =
    /[1-9]/.test(integer) || leadingZeros === -1
      ? places
      : Math.max(places, leadingZeros + significant);
  let rounded = roundDecimal(value, widened);
  for (let extra = widened - places; extra > 0 && rounded.endsWith("0"); extra -= 1) {
    rounded = rounded.slice(0, -1);
  }
  return rounded.endsWith(".") ? rounded.slice(0, -1) : rounded;
}

/** A figure without the zeros that end its fraction. */
function trimFraction(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

const COIN_PLACES = 8;
// What reads as money, by symbol, and the fraction digits it is read to. A
// short list on purpose: a coin's ticker may spell a lesser-known currency
// code, and a symbol is a label, never an identity. Presentation only — a
// symbol missing here shows more digits, never a different amount.
const MONEY_PLACES: ReadonlyMap<string, number> = new Map([
  ...["EUR", "USD", "GBP", "CHF", "CAD", "AUD", "SEK", "NOK", "DKK", "PLN"].map(
    (code) => [code, 2] as const,
  ),
  ["JPY", 0],
  ...["USDC", "USDT", "DAI", "USDE", "USDS", "USDP", "TUSD", "FDUSD", "PYUSD", "EURC"].map(
    (code) => [code, 2] as const,
  ),
]);

/** The fraction digits an amount of `symbol` is read to: money to its minor unit, a coin to eight. */
function placesOf(symbol: string | undefined): number {
  return MONEY_PLACES.get(symbol?.toUpperCase() ?? "") ?? COIN_PLACES;
}

function minorUnits(currency: string): number {
  return (
    new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions()
      .maximumFractionDigits ?? 2
  );
}

/**
 * An amount of `symbol` rounded for reading. A coin drops its trailing zeros;
 * money keeps its cents whole — 0.40, never 0.4 — unless it has none to state.
 */
function roundAmount(value: string, symbol: string | undefined): string {
  const places = placesOf(symbol);
  const rounded = roundForReading(value, places);
  return places === COIN_PLACES ? trimFraction(rounded) : rounded.replace(/\.0+$/, "");
}

/**
 * A quantity rounded for reading — money and stablecoins to the cent, a coin
 * to eight places. For a list or a table; a form, a reconciliation and a tax
 * figure state the digits verbatim instead.
 */
export function formatRoundedQuantity(value: string, symbol?: string, locale?: string): string {
  return formatQuantity(roundAmount(value, symbol), locale);
}

/** formatRoundedQuantity with the direction in the figure, as formatSignedQuantity states it. */
export function formatRoundedSignedQuantity(
  value: string,
  symbol?: string,
  locale?: string,
): string {
  return formatSignedQuantity(roundAmount(value, symbol), locale);
}

/** formatAssetAmount rounded for reading, as formatRoundedQuantity rounds. */
export function formatRoundedAssetAmount(value: string, symbol: string, locale?: string): string {
  return `${formatRoundedQuantity(value, symbol, locale)} ${symbol}`;
}

/** formatSignedAssetAmount rounded for reading, as formatRoundedQuantity rounds. */
export function formatRoundedSignedAssetAmount(
  value: string,
  symbol: string,
  locale?: string,
): string {
  return `${formatRoundedSignedQuantity(value, symbol, locale)} ${symbol}`;
}

/**
 * formatMoneyExact rounded to the currency's minor unit and padded to it, so
 * a column aligns — a venue's sixteen-digit dollar value read to the cent.
 */
export function formatMoneyRounded(value: string, currency: string, locale?: string): string {
  return formatMoneyExact(roundForReading(value, minorUnits(currency)), currency, locale);
}

/**
 * A price rounded for reading: two decimals at one or above, four significant
 * digits below, where two decimals would make a mark and an entry price look
 * alike. Bare, as a venue's price stands.
 */
export function formatPrice(value: string, locale?: string): string {
  return formatQuantity(trimFraction(roundForReading(value, 2, 4)), locale);
}

/**
 * A fixed-point difference with its direction in the figure itself — a plus
 * for a surplus, a true minus for a shortfall, nothing on an exact zero — so
 * the sign is never left to colour alone. The digits stay verbatim, as
 * formatQuantity keeps them.
 */
export function formatSignedQuantity(value: string, locale?: string): string {
  const negative = value.startsWith("-");
  const digits = negative ? value.slice(1) : value;
  const magnitude = formatQuantity(digits, locale);
  if (!/[1-9]/.test(digits)) return magnitude;
  return `${negative ? "−" : "+"}${magnitude}`;
}

/** A calendar date off the API (ISO `YYYY-MM-DD`), rendered per locale. */
export function formatDate(isoDate: string, locale?: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
    new Date(year ?? 0, (month ?? 1) - 1, day ?? 1),
  );
}

export function formatTimestamp(epochMs: number, locale?: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(epochMs);
}
