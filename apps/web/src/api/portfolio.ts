import { z } from "zod";
import { SIGNED_DECIMAL_PATTERN } from "@/api/holdings";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const PORTFOLIO_URL = "/api/portfolio";

const signedDecimal = z.string().regex(SIGNED_DECIMAL_PATTERN);

/**
 * The portfolio at one instant (ticket 54), every figure EUR. `value_eur` and
 * `result_eur` are null where something is held and none of it counts —
 * unstated, never zero. Contributions and withdrawals are cumulative from the
 * ledger's beginning; `unvalued_flows` counts those nothing stored could
 * value, which stand outside both.
 */
export const measurementSchema = z.object({
  snapshot_date: z.iso.date(),
  taken_at: z.iso.datetime({ offset: true }),
  value_eur: signedDecimal.nullable(),
  positions_held: z.number(),
  positions_counted: z.number(),
  contributions_eur: signedDecimal,
  withdrawals_eur: signedDecimal,
  net_contributions_eur: signedDecimal,
  result_eur: signedDecimal.nullable(),
  unvalued_flows: z.number(),
});

/** The stored snapshots, oldest first, and the portfolio as it stands now. */
export const developmentSchema = z.object({
  snapshots: z.array(measurementSchema),
  current: measurementSchema,
});

/**
 * One kind of realisation. `result_eur` sums the `stated` of its `events`;
 * null where none states a gain, or where the engine refused — `refusal` is
 * then its sentence.
 */
export const realisedComponentSchema = z.object({
  kind: z.enum(["private_sales", "securities", "futures"]),
  result_eur: signedDecimal.nullable(),
  stated: z.number(),
  events: z.number(),
  refusal: z.string().nullable(),
});

/** Null overall as soon as one kind is unstated. */
export const realisedSchema = z.object({
  result_eur: signedDecimal.nullable(),
  stated: z.number(),
  events: z.number(),
  components: z.array(realisedComponentSchema),
});

export type Measurement = z.infer<typeof measurementSchema>;
export type Development = z.infer<typeof developmentSchema>;
export type RealisedComponent = z.infer<typeof realisedComponentSchema>;
export type Realised = z.infer<typeof realisedSchema>;

export async function fetchDevelopment(): Promise<Development> {
  const response = await fetch(`${PORTFOLIO_URL}/development`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the portfolio's development.`);
  }
  return developmentSchema.parse(await response.json());
}

export async function fetchRealised(): Promise<Realised> {
  const response = await fetch(`${PORTFOLIO_URL}/realised`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the realised result.`);
  }
  return realisedSchema.parse(await response.json());
}
