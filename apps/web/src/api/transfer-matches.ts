import { z } from "zod";
import { postJson, refusal } from "@/api/http";
import { DECIMAL_PATTERN } from "@/api/transactions";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const TRANSFER_MATCHES_URL = "/api/transfer-matches";

/** One side of a possible self-transfer, described as the Admin knows it. */
export const transferLegSchema = z.object({
  leg_id: z.number(),
  transaction_id: z.number(),
  occurred_at: z.iso.datetime({ offset: true }),
  note: z.string().nullable(),
  quantity: z.string().regex(DECIMAL_PATTERN),
  account_id: z.number(),
  account_name: z.string(),
  platform_name: z.string(),
  instrument_id: z.number(),
  instrument_symbol: z.string(),
  instrument_name: z.string(),
});

export type TransferLeg = z.infer<typeof transferLegSchema>;

const candidateSchema = z.object({
  outgoing: transferLegSchema,
  incoming: transferLegSchema,
});

export type Candidate = z.infer<typeof candidateSchema>;

const decisionSchema = z.object({
  id: z.number(),
  verdict: z.enum(["confirmed", "rejected"]),
  decided_at: z.iso.datetime({ offset: true }),
  outgoing: transferLegSchema,
  incoming: transferLegSchema,
});

export type Decision = z.infer<typeof decisionSchema>;

/**
 * The whole matching state in one answer: what waits unmatched, what the app
 * proposes, and what the Admin has decided. Reading it stores nothing —
 * nothing links itself.
 */
export const matchingOverviewSchema = z.object({
  unmatched_outgoing: z.array(transferLegSchema),
  unmatched_incoming: z.array(transferLegSchema),
  candidates: z.array(candidateSchema),
  decisions: z.array(decisionSchema),
});

export type MatchingOverview = z.infer<typeof matchingOverviewSchema>;

export async function fetchMatching(): Promise<MatchingOverview> {
  const response = await fetch(TRANSFER_MATCHES_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the matching state.`);
  }
  return matchingOverviewSchema.parse(await response.json());
}

/** The deliberate act over one proposed pair; answers the decision's id. */
export async function decideMatch(decision: {
  out_leg_id: number;
  in_leg_id: number;
  verdict: "confirmed" | "rejected";
}): Promise<number> {
  const response = await postJson(TRANSFER_MATCHES_URL, decision);
  if (!response.ok) {
    throw await refusal(response, "The pair could not be decided.");
  }
  const { id } = z.object({ id: z.number() }).parse(await response.json());
  return id;
}

/** Undo a decision: unlink a match, or make a rejected pair proposable again. */
export async function undoDecision(decisionId: number): Promise<void> {
  const response = await fetch(`${TRANSFER_MATCHES_URL}/${decisionId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The decision could not be undone.");
  }
}
