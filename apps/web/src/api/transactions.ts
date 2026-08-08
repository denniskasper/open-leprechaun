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
  "dividend",
  "distribution",
  "interest",
  "fee",
]);

export const legRoleSchema = z.enum(["in", "out", "fee"]);

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
  legs: z.array(legSchema),
});

export type TransactionType = z.infer<typeof transactionTypeSchema>;
export type LegRole = z.infer<typeof legRoleSchema>;
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
