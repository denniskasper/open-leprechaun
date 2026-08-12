import { z } from "zod";
import { putJson, refusal } from "@/api/http";
import { DECIMAL_PATTERN } from "@/api/transactions";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const STATUTORY_URL = "/api/statutory";

/** The statutory vocabulary; the API's service holds units and requiredness. */
export const statutoryKeySchema = z.enum([
  "private_sale_exemption_limit",
  "other_income_exemption_limit",
  "saver_allowance_single",
  "saver_allowance_joint",
  "flat_rate",
  "solidarity_surcharge_rate",
  "church_tax_rate_bavaria_bw",
  "church_tax_rate_other_laender",
  "advance_lump_sum_base_rate",
  "loss_cap_aktien",
  "loss_cap_sonstige",
  "loss_cap_termingeschaefte",
  "opening_carryforward_aktien",
  "opening_carryforward_sonstige",
  "opening_carryforward_termingeschaefte",
  "partial_exemption_aktienfonds",
  "partial_exemption_mischfonds",
  "partial_exemption_immobilienfonds",
  "partial_exemption_auslands_immobilienfonds",
  "partial_exemption_sonstige",
]);

/** The elections that select which per-year values apply. */
export const filingStatusSchema = z.enum(["single", "joint"]);
export const churchTaxSchema = z.enum(["none", "bavaria_bw", "other_laender"]);

/**
 * Statutory values are fixed-point decimals throughout, including in JSON:
 * the API speaks plain decimal strings, and a number here would mean
 * something had been through a float.
 */
const decimalString = z.string().regex(DECIMAL_PATTERN);

export const statutoryKeyDefinitionSchema = z.object({
  key: statutoryKeySchema,
  unit: z.enum(["eur", "rate"]),
  required: z.boolean(),
});

export const statutoryValueSchema = z.object({
  key: statutoryKeySchema,
  value: decimalString,
  source: z.string(),
});

export const statutoryYearSchema = z.object({
  year: z.number().int(),
  values: z.array(statutoryValueSchema),
  // The required keys this year still has no value for.
  missing: z.array(statutoryKeySchema),
});

export const statutorySchema = z.object({
  filing_status: filingStatusSchema,
  church_tax: churchTaxSchema,
  keys: z.array(statutoryKeyDefinitionSchema),
  years: z.array(statutoryYearSchema),
});

export type StatutoryKey = z.infer<typeof statutoryKeySchema>;
export type FilingStatus = z.infer<typeof filingStatusSchema>;
export type ChurchTax = z.infer<typeof churchTaxSchema>;
export type StatutoryKeyDefinition = z.infer<typeof statutoryKeyDefinitionSchema>;
export type StatutoryValue = z.infer<typeof statutoryValueSchema>;
export type StatutoryYear = z.infer<typeof statutoryYearSchema>;
export type Statutory = z.infer<typeof statutorySchema>;

export interface NewStatutoryValue {
  value: string;
  source: string;
}

export interface Election {
  filing_status: FilingStatus;
  church_tax: ChurchTax;
}

export async function fetchStatutory(): Promise<Statutory> {
  const response = await fetch(STATUTORY_URL);
  if (!response.ok) {
    throw new Error(
      `The API answered ${response.status} instead of the statutory configuration.`,
    );
  }
  return statutorySchema.parse(await response.json());
}

export async function enterValue(
  year: number,
  key: StatutoryKey,
  value: NewStatutoryValue,
): Promise<void> {
  const response = await putJson(`${STATUTORY_URL}/values/${year}/${key}`, value);
  if (!response.ok) {
    throw await refusal(response, "The value could not be stored.");
  }
}

export async function unsetValue(year: number, key: StatutoryKey): Promise<void> {
  const response = await fetch(`${STATUTORY_URL}/values/${year}/${key}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The value could not be unset.");
  }
}

export async function chooseElection(election: Election): Promise<void> {
  const response = await putJson(`${STATUTORY_URL}/election`, election);
  if (!response.ok) {
    throw await refusal(response, "The election could not be changed.");
  }
}
