import { z } from "zod";
import { postJson, putJson, refusal } from "@/api/http";
import { DECIMAL_PATTERN } from "@/api/transactions";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const CORPORATE_ACTIONS_URL = "/api/corporate-actions";

export const corporateActionKindSchema = z.enum(["split", "spin_off", "merger", "capital_return"]);

export type CorporateActionKind = z.infer<typeof corporateActionKindSchema>;

const decimalString = z.string().regex(DECIMAL_PATTERN);

/** What one open lot holds at one moment; a null basis awaits a valuation. */
const lotStateSchema = z.object({
  instrument_id: z.number(),
  quantity: decimalString,
  basis_eur: decimalString.nullable(),
});

export type LotState = z.infer<typeof lotStateSchema>;

/** One open lot before the event and everything it became. */
const lotEffectSchema = z.object({
  account_id: z.number(),
  acquired_at: z.iso.datetime({ offset: true }),
  basis_source: z.string(),
  before: lotStateSchema,
  after: z.array(lotStateSchema),
  // What a capital return exceeded the lot's basis by.
  excess_eur: decimalString,
});

export type LotEffect = z.infer<typeof lotEffectSchema>;

/**
 * One event with what it did to the lots open at its instant. A preview is
 * the same shape with no id: nothing was recorded.
 */
export const corporateActionSchema = z.object({
  id: z.number().nullable(),
  kind: corporateActionKindSchema,
  instrument_id: z.number(),
  effective_at: z.iso.datetime({ offset: true }),
  units_new: decimalString.nullable(),
  units_old: decimalString.nullable(),
  target_instrument_id: z.number().nullable(),
  basis_share: decimalString.nullable(),
  amount_per_unit_eur: decimalString.nullable(),
  note: z.string().nullable(),
  reviewed_at: z.iso.datetime({ offset: true }).nullable(),
  needs_review: z.boolean(),
  lots: z.array(lotEffectSchema),
});

export type CorporateAction = z.infer<typeof corporateActionSchema>;

/** The event as the Admin states it; each kind carries exactly its own fields. */
export interface NewCorporateAction {
  kind: CorporateActionKind;
  instrument_id: number;
  effective_at: string;
  units_new?: string;
  units_old?: string;
  target_instrument_id?: number;
  basis_share?: string;
  amount_per_unit_eur?: string;
  note?: string;
}

export async function fetchCorporateActions(): Promise<CorporateAction[]> {
  const response = await fetch(CORPORATE_ACTIONS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing corporate actions.`);
  }
  return z.array(corporateActionSchema).parse(await response.json());
}

/** The before and after of every lot the event would touch; writes nothing. */
export async function previewCorporateAction(action: NewCorporateAction): Promise<CorporateAction> {
  const response = await postJson(`${CORPORATE_ACTIONS_URL}/preview`, action);
  if (!response.ok) {
    throw await refusal(response, "The event could not be previewed.");
  }
  return corporateActionSchema.parse(await response.json());
}

/** Apply the event by recording it; answers its id. */
export async function applyCorporateAction(action: NewCorporateAction): Promise<number> {
  const response = await postJson(CORPORATE_ACTIONS_URL, action);
  if (!response.ok) {
    throw await refusal(response, "The event could not be applied.");
  }
  const { id } = z.object({ id: z.number() }).parse(await response.json());
  return id;
}

/** The Admin has looked at a flagged event and stands by what it states. */
export async function markCorporateActionReviewed(actionId: number): Promise<void> {
  const response = await putJson(`${CORPORATE_ACTIONS_URL}/${actionId}/review`, {});
  if (!response.ok) {
    throw await refusal(response, "The event could not be marked as reviewed.");
  }
}

/** Reverse the event: remove it, and the lots rebuild without it. */
export async function removeCorporateAction(actionId: number): Promise<void> {
  const response = await fetch(`${CORPORATE_ACTIONS_URL}/${actionId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The event could not be reversed.");
  }
}
