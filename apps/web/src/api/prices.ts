import { z } from "zod";
import { DECIMAL_PATTERN } from "@/api/transactions";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const CRYPTO_PRICES_URL = "/api/prices/crypto";

/**
 * One Instrument's answer from the provider chain (ticket 18): a fresh quote,
 * the stored last-known price clearly labelled stale, or the honest admission
 * that nothing has ever priced it — never a blank or a zero.
 */
export const pricedInstrumentSchema = z.object({
  instrument_id: z.number(),
  symbol: z.string(),
  name: z.string(),
  status: z.enum(["fresh", "stale", "unpriced"]),
  price_eur: z.string().regex(DECIMAL_PATTERN).nullable(),
  source: z.string().nullable(),
  as_of: z.iso.datetime({ offset: true }).nullable(),
});

/**
 * What one failing provider's failure actually was — a rate limit is its own
 * named condition, never conflated with an outage.
 */
export const providerConditionSchema = z.object({
  provider: z.string(),
  condition: z.enum(["rate_limited", "outage"]),
});

export const priceReportSchema = z.object({
  prices: z.array(pricedInstrumentSchema),
  conditions: z.array(providerConditionSchema),
});

export type PricedInstrument = z.infer<typeof pricedInstrumentSchema>;
export type ProviderCondition = z.infer<typeof providerConditionSchema>;
export type PriceReport = z.infer<typeof priceReportSchema>;

export async function fetchCryptoPrices(): Promise<PriceReport> {
  const response = await fetch(CRYPTO_PRICES_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the crypto price report.`);
  }
  return priceReportSchema.parse(await response.json());
}

export const SECURITY_PRICES_URL = "/api/prices/securities";

/**
 * The securities report (ticket 45) speaks the same vocabulary: each security
 * priced through its price-source Listing, served fresh, stale or unpriced.
 */
export async function fetchSecurityPrices(): Promise<PriceReport> {
  const response = await fetch(SECURITY_PRICES_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the security price report.`);
  }
  return priceReportSchema.parse(await response.json());
}
