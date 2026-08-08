import { z } from "zod";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const INSTRUMENTS_URL = "/api/instruments";

export const listingSchema = z.object({
  venue: z.string(),
  quote_currency: z.string(),
});

export const instrumentSchema = z.object({
  id: z.number(),
  family: z.enum(["crypto", "security", "cash"]),
  type: z.string(),
  symbol: z.string(),
  name: z.string(),
  chain: z.string().nullable(),
  contract_address: z.string().nullable(),
  isin: z.string().nullable(),
  listings: z.array(listingSchema),
});

export type Listing = z.infer<typeof listingSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;

export async function fetchInstruments(): Promise<Instrument[]> {
  const response = await fetch(INSTRUMENTS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing instruments.`);
  }
  return z.array(instrumentSchema).parse(await response.json());
}
