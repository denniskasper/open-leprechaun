import { z } from "zod";
import { postJson, refusal, request } from "@/api/http";
import { categorySourceSchema, distributionPolicySchema, fundCategorySchema } from "./securities";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const INSTRUMENTS_URL = "/api/instruments";

export const listingSchema = z.object({
  id: z.number(),
  venue: z.string(),
  quote_currency: z.string(),
  // Whether this Listing's market prices the Instrument (ticket 45).
  price_source: z.boolean(),
});

/** A per-Account decision — kept or ignored; dangerous is global (ADR-0012). */
export const accountStanceSchema = z.object({
  account_id: z.number(),
  stance: z.enum(["kept", "ignored"]),
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
  is_numeraire: z.boolean(),
  // A fund's Teilfreistellung classification with the source of the value
  // shown, and the review flag an import-created security wears (ticket 44).
  fund_category: fundCategorySchema.nullable(),
  fund_category_source: categorySourceSchema.nullable(),
  distribution_policy: distributionPolicySchema.nullable(),
  needs_review: z.boolean(),
  listings: z.array(listingSchema),
  dangerous: z.boolean(),
  stances: z.array(accountStanceSchema),
});

export type Listing = z.infer<typeof listingSchema>;
export type AccountStance = z.infer<typeof accountStanceSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;

export async function fetchInstruments(): Promise<Instrument[]> {
  const response = await request(INSTRUMENTS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing instruments.`);
  }
  return z.array(instrumentSchema).parse(await response.json());
}

/**
 * A coin, token or currency stated by the identity the ledger keys it on
 * (ADR-0010) — what a venue's sync can resolve by symbol but never create.
 */
export type NewInstrument =
  | {
      kind: "token";
      symbol: string;
      name: string;
      chain: string;
      contract_address: string;
      /** A stablecoin's peg, which routes its EUR value to the reference rate. */
      pegged_currency: string | null;
    }
  | { kind: "native"; symbol: string; name: string; chain: string }
  | { kind: "cash"; symbol: string; name: string };

export async function addInstrument(instrument: NewInstrument): Promise<number> {
  const response = await postJson(INSTRUMENTS_URL, instrument);
  if (!response.ok) {
    throw await refusal(response, "The Instrument could not be added.");
  }
  return z.object({ id: z.number() }).parse(await response.json()).id;
}
