import { z } from "zod";
import { putJson, refusal } from "@/api/http";
import { DECIMAL_PATTERN } from "@/api/transactions";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const INBOX_URL = "/api/inbox";

/**
 * One unacknowledged arrival: an Instrument at an Account that the Admin has
 * never classified, with the unsolicited inflows a keep decision would settle.
 */
export const inboxItemSchema = z.object({
  instrument_id: z.number(),
  family: z.enum(["crypto", "security", "cash"]),
  type: z.string(),
  symbol: z.string(),
  name: z.string(),
  chain: z.string().nullable(),
  contract_address: z.string().nullable(),
  isin: z.string().nullable(),
  account_id: z.number(),
  account_name: z.string(),
  platform_name: z.string(),
  unclassified_inflow_count: z.number(),
  unclassified_quantity: z.string().regex(DECIMAL_PATTERN),
  last_inflow_at: z.iso.datetime({ offset: true }),
});

export type InboxItem = z.infer<typeof inboxItemSchema>;

/**
 * The deliberate act with three outcomes (ADR-0012): kept and ignored are
 * decisions about one Account, dangerous applies everywhere. Only keeping
 * answers the counter-performance question, and unanswered it is no.
 */
export interface Classification {
  stance: "kept" | "ignored" | "dangerous";
  account_id?: number;
  received_for_counter_performance?: boolean;
}

export async function fetchInbox(): Promise<InboxItem[]> {
  const response = await fetch(INBOX_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing the inbox.`);
  }
  return z.array(inboxItemSchema).parse(await response.json());
}

/** Classify one Instrument; answers the transaction ids the decision settled. */
export async function classifyInstrument(
  instrumentId: number,
  classification: Classification,
): Promise<number[]> {
  const response = await putJson(`/api/instruments/${instrumentId}/stance`, classification);
  if (!response.ok) {
    throw await refusal(response, "The Instrument could not be classified.");
  }
  const { settled_transaction_ids } = z
    .object({ settled_transaction_ids: z.array(z.number()) })
    .parse(await response.json());
  return settled_transaction_ids;
}
