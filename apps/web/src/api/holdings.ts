import { z } from "zod";
import { request } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const HOLDINGS_URL = "/api/holdings";

/** Unrealised results — and a broken ledger's quantity — may be negative. */
export const SIGNED_DECIMAL_PATTERN = /^-?\d+(\.\d+)?$/;

const signedDecimal = z.string().regex(SIGNED_DECIMAL_PATTERN);

/**
 * One (Account, Instrument) holding (ticket 20). Every figure is EUR — the
 * DisplayCurrency conversion happens client-side, for presentation only.
 * `marker` names why a position is excluded from totals; `basis_gap` names
 * why the basis cannot be stated while the position itself still counts.
 */
export const positionSchema = z.object({
  instrument_id: z.number(),
  symbol: z.string(),
  name: z.string(),
  family: z.enum(["crypto", "security", "cash"]),
  type: z.string(),
  chain: z.string().nullable(),
  contract_address: z.string().nullable(),
  isin: z.string().nullable(),
  is_numeraire: z.boolean(),
  account_id: z.number(),
  account_name: z.string(),
  access_software: z.string().nullable(),
  platform_name: z.string(),
  platform_kind: z.enum(["exchange", "cold_storage", "software_wallet", "broker", "bank"]),
  quantity: signedDecimal,
  marker: z.enum(["dangerous", "ignored", "unacknowledged", "unpriced"]).nullable(),
  basis_eur: signedDecimal.nullable(),
  basis_gap: z.enum(["awaiting_valuation", "unvouched"]).nullable(),
  average_cost_eur: signedDecimal.nullable(),
  value_eur: signedDecimal.nullable(),
  unrealised_eur: signedDecimal.nullable(),
  price_source: z.string().nullable(),
  price_as_of: z.iso.datetime({ offset: true }).nullable(),
  rate_date: z.iso.date().nullable(),
});

/**
 * One order a broker holds open (a Pending Order) — an instruction, not an
 * event, so never part of a Position's figures. Named as the broker named
 * it: Holdings matches it to a Position by Account and ISIN. A quantity
 * order states what is still to fill, its prices per unit in `currency`; an
 * order by value states `value` in `currency` instead.
 */
export const pendingOrderSchema = z.object({
  external_id: z.string(),
  created_at: z.iso.datetime({ offset: true }),
  isin: z.string(),
  symbol: z.string(),
  name: z.string(),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["market", "limit", "stop", "stop_limit"]),
  currency: z.string(),
  quantity: signedDecimal.nullable(),
  value: signedDecimal.nullable(),
  limit_price: signedDecimal.nullable(),
  stop_price: signedDecimal.nullable(),
});

/**
 * What one Depot's broker last said it holds open, as of `as_of` — recorded
 * at a sync or a reconciliation. Beside an `error`, why it could not be read.
 */
export const pendingOrdersSchema = z.object({
  account_id: z.number(),
  as_of: z.iso.datetime({ offset: true }),
  error: z.string().nullable(),
  reserved_cash: signedDecimal.nullable(),
  reserved_currency: z.string().nullable(),
  orders: z.array(pendingOrderSchema),
});

export const holdingsSchema = z.object({
  positions: z.array(positionSchema),
  pending_orders: z.array(pendingOrdersSchema),
});

/**
 * The latest published reference rate for a DisplayCurrency — units per one
 * euro, with the date it represents. Presentation only, never a tax figure.
 */
export const displayRateSchema = z.object({
  currency: z.string(),
  rate: signedDecimal,
  rate_date: z.iso.date(),
});

export type Position = z.infer<typeof positionSchema>;
export type Holdings = z.infer<typeof holdingsSchema>;
export type PendingOrder = z.infer<typeof pendingOrderSchema>;
export type PendingOrders = z.infer<typeof pendingOrdersSchema>;
export type DisplayRate = z.infer<typeof displayRateSchema>;

export async function fetchHoldings(): Promise<Holdings> {
  const response = await request(HOLDINGS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the holdings.`);
  }
  return holdingsSchema.parse(await response.json());
}

export async function fetchPendingOrders(): Promise<PendingOrders[]> {
  const response = await request("/api/pending-orders");
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the pending orders.`);
  }
  return z.array(pendingOrdersSchema).parse(await response.json());
}

export async function fetchDisplayRate(currency: string): Promise<DisplayRate> {
  const response = await request(`${HOLDINGS_URL}/display-rate/${currency}`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the ${currency} rate.`);
  }
  return displayRateSchema.parse(await response.json());
}
