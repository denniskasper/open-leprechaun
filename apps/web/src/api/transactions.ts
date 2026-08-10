import { z } from "zod";
import { postJson, putJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const TRANSACTIONS_URL = "/api/transactions";

/** The vocabulary of what happened, for crypto and securities both. */
export const transactionTypeSchema = z.enum([
  "trade",
  "transfer_in",
  "transfer_out",
  "spend",
  "staking_reward",
  "lending_interest",
  "mining_reward",
  "airdrop",
  "windfall",
  "opening_balance",
  "dividend",
  "distribution",
  "interest",
  "fee",
]);

export const legRoleSchema = z.enum(["in", "out", "fee"]);

/**
 * What an Opening Balance declares as reconstructed — the basis alone, with
 * the acquisition date known and used as given, or the date and basis both.
 */
export const reconstructedSchema = z.enum(["basis", "basis_and_date"]);

/**
 * Quantities are fixed-point decimals throughout, including in JSON: the API
 * speaks plain decimal strings, and a number here would mean something had
 * been through a float. The one shape a quantity is judged by, wherever it
 * is judged — this schema, the form's own check, the input's pattern.
 */
export const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

const decimalString = z.string().regex(DECIMAL_PATTERN);

export const legSchema = z.object({
  id: z.number(),
  account_id: z.number(),
  instrument_id: z.number(),
  role: legRoleSchema,
  quantity: decimalString,
  charged_against_leg_id: z.number().nullable(),
});

export const transactionSchema = z.object({
  id: z.number(),
  type: transactionTypeSchema,
  occurred_at: z.iso.datetime({ offset: true }),
  note: z.string().nullable(),
  // An Opening Balance's declarations; null on every other type. The
  // estimated basis is a monetary amount and crosses as a decimal string.
  reconstructed: reconstructedSchema.nullable(),
  estimated_basis_eur: decimalString.nullable(),
  // Import provenance (ticket 31): the batch and source that created this
  // row, null on a hand-recorded event. An imported row the Admin edited by
  // hand is manually overridden — a re-import never silently reverts it.
  import_batch_id: z.number().nullable(),
  import_source: z.string().nullable(),
  manually_overridden: z.boolean(),
  legs: z.array(legSchema),
});

export type TransactionType = z.infer<typeof transactionTypeSchema>;
export type LegRole = z.infer<typeof legRoleSchema>;
export type Reconstructed = z.infer<typeof reconstructedSchema>;
export type Leg = z.infer<typeof legSchema>;
export type Transaction = z.infer<typeof transactionSchema>;

export interface NewLeg {
  account_id: number;
  instrument_id: number;
  role: LegRole;
  quantity: string;
  /** The position of the sibling leg this fee was charged against, if any. */
  charged_against: number | null;
}

export interface NewTransaction {
  type: TransactionType;
  occurred_at: string;
  note: string | null;
  reconstructed: Reconstructed | null;
  estimated_basis_eur: string | null;
  legs: NewLeg[];
}

export async function fetchTransactions(): Promise<Transaction[]> {
  const response = await fetch(TRANSACTIONS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing transactions.`);
  }
  return z.array(transactionSchema).parse(await response.json());
}

export async function recordTransaction(transaction: NewTransaction): Promise<void> {
  const response = await postJson(TRANSACTIONS_URL, transaction);
  if (!response.ok) {
    throw await refusal(response, "The Transaction could not be recorded.");
  }
}

export async function reviseTransaction(
  transactionId: number,
  transaction: NewTransaction,
): Promise<void> {
  const response = await putJson(`${TRANSACTIONS_URL}/${transactionId}`, transaction);
  if (!response.ok) {
    throw await refusal(response, "The Transaction could not be revised.");
  }
}

export async function removeTransaction(transactionId: number): Promise<void> {
  const response = await fetch(`${TRANSACTIONS_URL}/${transactionId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The Transaction could not be removed.");
  }
}

/**
 * Move every leg of the chosen events into another Account, in one act — the
 * repair for a file imported against the wrong holding (ticket 31).
 */
export async function bulkReassign(transactionIds: number[], accountId: number): Promise<void> {
  const response = await postJson(`${TRANSACTIONS_URL}/bulk-reassignment`, {
    transaction_ids: transactionIds,
    account_id: accountId,
  });
  if (!response.ok) {
    throw await refusal(response, "The Transactions could not be reassigned.");
  }
}

/**
 * Re-type the chosen events in one act. One that would not balance for the
 * new type refuses the whole act with a sentence naming it.
 */
export async function bulkRetype(transactionIds: number[], type: TransactionType): Promise<void> {
  const response = await postJson(`${TRANSACTIONS_URL}/bulk-retyping`, {
    transaction_ids: transactionIds,
    type,
  });
  if (!response.ok) {
    throw await refusal(response, "The Transactions could not be re-typed.");
  }
}
