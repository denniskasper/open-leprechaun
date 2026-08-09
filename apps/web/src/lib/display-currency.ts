/**
 * The DisplayCurrency (ticket 20): which currency values are *rendered* in.
 * Presentation only — every tax figure is computed and served in EUR, and
 * this choice never touches one. The preference lives in localStorage like
 * the theme; absence means EUR.
 */

const STORAGE_KEY = "display-currency";

/**
 * EUR plus currencies the euro reference rate universe covers — the same
 * source the API's display rate answers from, so every offered choice can
 * actually be served.
 */
export const DISPLAY_CURRENCIES = [
  "EUR",
  "USD",
  "GBP",
  "CHF",
  "JPY",
  "SEK",
  "NOK",
  "DKK",
  "PLN",
  "CZK",
  "AUD",
  "CAD",
] as const;

export type DisplayCurrency = (typeof DISPLAY_CURRENCIES)[number];

export function getDisplayCurrency(): DisplayCurrency {
  const stored = localStorage.getItem(STORAGE_KEY);
  const known = DISPLAY_CURRENCIES.find((currency) => currency === stored);
  return known ?? "EUR";
}

export function setDisplayCurrency(currency: DisplayCurrency): void {
  if (currency === "EUR") {
    localStorage.removeItem(STORAGE_KEY);
  } else {
    localStorage.setItem(STORAGE_KEY, currency);
  }
}
