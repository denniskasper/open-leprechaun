import { z } from "zod";
import { postJson, putJson, refusal } from "./http";

/**
 * The Teilfreistellung categories of §20 InvStG — the classification a fund's
 * taxation depends on. The rates belong to the statutory store, never here.
 */
export const fundCategorySchema = z.enum([
  "aktienfonds",
  "mischfonds",
  "immobilienfonds",
  "auslands_immobilienfonds",
  "sonstige",
]);

export const distributionPolicySchema = z.enum(["distributing", "accumulating"]);

/** Who stated a fund's classification: the provider's prefill, or the Admin. */
export const categorySourceSchema = z.enum(["provider", "admin"]);

export const candidateSchema = z.object({
  isin: z.string(),
  wkn: z.string().nullable(),
  ticker: z.string().nullable(),
  name: z.string(),
  type: z.string(),
  currency: z.string().nullable(),
  venue: z.string().nullable(),
  fund_category: fundCategorySchema.nullable(),
  distribution_policy: distributionPolicySchema.nullable(),
  // The Instrument this candidate already is — the picker says so instead of
  // inviting a duplicate.
  instrument_id: z.number().nullable(),
});

export type FundCategory = z.infer<typeof fundCategorySchema>;
export type DistributionPolicy = z.infer<typeof distributionPolicySchema>;
export type CategorySource = z.infer<typeof categorySourceSchema>;
export type Candidate = z.infer<typeof candidateSchema>;

/** A classification at creation, where the picker relays the prefill's provenance. */
export interface Classification {
  fund_category: FundCategory;
  fund_category_source: CategorySource;
  distribution_policy: DistributionPolicy | null;
}

/**
 * A classification stated in the Admin's own act — an override or a review.
 * It carries no source: the server stamps `admin`, so a request cannot wear
 * the provider's name.
 */
export interface AdminClassification {
  fund_category: FundCategory;
  distribution_policy: DistributionPolicy | null;
}

export interface NewSecurity {
  isin: string;
  name: string;
  symbol: string;
  type: string;
  wkn?: string | null;
  ticker?: string | null;
  venue?: string | null;
  quote_currency?: string | null;
  classification?: Classification | null;
}

export interface Review {
  type: string;
  symbol: string;
  name: string;
  classification?: AdminClassification | null;
}

export async function searchSecurities(query: string): Promise<Candidate[]> {
  const response = await fetch(`/api/securities/search?query=${encodeURIComponent(query)}`);
  if (!response.ok) {
    throw await refusal(response, `The API answered ${response.status} instead of searching.`);
  }
  return z.array(candidateSchema).parse(await response.json());
}

export async function createSecurity(security: NewSecurity): Promise<number> {
  const response = await postJson("/api/securities", security);
  if (!response.ok) {
    throw await refusal(response, `The API answered ${response.status} instead of creating.`);
  }
  return z.object({ id: z.number() }).parse(await response.json()).id;
}

export async function classifyFund(
  instrumentId: number,
  classification: AdminClassification,
): Promise<void> {
  const response = await putJson(`/api/securities/${instrumentId}/classification`, classification);
  if (!response.ok) {
    throw await refusal(response, `The API answered ${response.status} instead of classifying.`);
  }
}

export async function reviewSecurity(instrumentId: number, review: Review): Promise<void> {
  const response = await putJson(`/api/securities/${instrumentId}/review`, review);
  if (!response.ok) {
    throw await refusal(response, `The API answered ${response.status} instead of settling.`);
  }
}
