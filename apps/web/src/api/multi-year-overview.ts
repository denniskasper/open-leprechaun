import { z } from "zod";
import { request } from "@/api/http";
import { SIGNED_DECIMAL_PATTERN } from "@/api/holdings";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const MULTI_YEAR_OVERVIEW_URL = "/api/multi-year-overview";

const decimal = z.string().regex(SIGNED_DECIMAL_PATTERN);

/**
 * One regime's row for one Tax Year, every figure EUR. `allowance_limit_eur`
 * is the year's configured exemption and `allowance_eur` what it actually
 * freed; `tax_eur` is null where the rate is the Admin's personal one — the
 * taxable amount is the answer there.
 */
export const regimeYearSchema = z.object({
  gross_eur: decimal,
  offsets_eur: decimal,
  allowance_limit_eur: decimal,
  allowance_eur: decimal,
  taxable_eur: decimal,
  tax_eur: decimal.nullable(),
});

/**
 * One slice of a loss carryforward: the year that established it, and whether
 * it was entered from an assessment predating the ledger.
 */
export const carryforwardLayerSchema = z.object({
  origin_year: z.number(),
  amount_eur: decimal,
  opening: z.boolean(),
});

/** One Verlustverrechnungstopf's carryforward through a year. */
export const potCarryforwardSchema = z.object({
  category: z.enum(["aktien", "sonstige", "termingeschaefte"]),
  carryforward_in_eur: decimal,
  carryforward_in: z.array(carryforwardLayerSchema),
  consumed_eur: decimal,
  consumed: z.array(carryforwardLayerSchema),
  produced_eur: decimal,
  carryforward_out_eur: decimal,
  carryforward_out: z.array(carryforwardLayerSchema),
});

export const capitalIncomeYearSchema = regimeYearSchema.extend({
  categories: z.array(potCarryforwardSchema),
});

/** One unfinished prerequisite: the reason, and the screen that resolves it. */
export const blockerSchema = z.object({
  kind: z.string(),
  detail: z.string(),
  resolve_path: z.string(),
  count: z.number(),
});

/**
 * One Tax Year across the regimes (ticket 57). A regime is null where its
 * engine could not state the year — never a zero — and `blockers` says what
 * stands in the way.
 */
export const overviewYearSchema = z.object({
  year: z.number(),
  blockers: z.array(blockerSchema),
  private_sales: regimeYearSchema.nullable(),
  other_income: regimeYearSchema.nullable(),
  capital_income: capitalIncomeYearSchema.nullable(),
});

export const multiYearOverviewSchema = z.object({ years: z.array(overviewYearSchema) });

export type RegimeYear = z.infer<typeof regimeYearSchema>;
export type CarryforwardLayer = z.infer<typeof carryforwardLayerSchema>;
export type PotCarryforward = z.infer<typeof potCarryforwardSchema>;
export type Blocker = z.infer<typeof blockerSchema>;
export type OverviewYear = z.infer<typeof overviewYearSchema>;
export type MultiYearOverview = z.infer<typeof multiYearOverviewSchema>;

export async function fetchMultiYearOverview(): Promise<MultiYearOverview> {
  const response = await request(MULTI_YEAR_OVERVIEW_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the multi-year overview.`);
  }
  return multiYearOverviewSchema.parse(await response.json());
}
