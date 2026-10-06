import { z } from "zod";
import { request } from "@/api/http";

export const FUTURES_URL = "/api/futures";

const sideSchema = z.enum(["long", "short"]);

/** A position the ledger holds — derived from fills, or entered by hand (ADR-0009). */
export const positionSchema = z.object({
  id: z.number(),
  origin: z.enum(["manual", "derived"]),
  source: z.string().nullable(),
  account_id: z.number(),
  symbol: z.string(),
  side: sideSchema,
  quantity: z.string(),
  settlement_symbol: z.string(),
  opened_at: z.string(),
  closed_at: z.string().nullable(),
  realized: z.string(),
  fees: z.string(),
  funding: z.string(),
  net: z.string(),
  /** The net in EUR by the stored rate of the close day; null while open or unvalued. */
  net_eur: z.string().nullable(),
});

const unattributableFundingSchema = z.object({
  id: z.number(),
  source: z.string(),
  account_id: z.number(),
  symbol: z.string(),
  amount: z.string(),
  /** What `amount` is an amount of. */
  settlement_symbol: z.string(),
  occurred_at: z.string(),
});

const derivationIssueSchema = z.object({
  id: z.number(),
  source: z.string(),
  account_id: z.number(),
  symbol: z.string(),
  position_side: sideSchema.nullable(),
  reason: z.string(),
});

export const futuresSchema = z.object({
  positions: z.array(positionSchema),
  unattributable_funding: z.array(unattributableFundingSchema),
  derivation_issues: z.array(derivationIssueSchema),
});

/** One open position as the venue states it right now — every figure its own, null where unstated. */
export const livePositionSchema = z.object({
  symbol: z.string(),
  side: sideSchema,
  quantity: z.string(),
  quantity_unit: z.string().nullable(),
  notional_usd: z.string().nullable(),
  leverage: z.string().nullable(),
  margin_mode: z.string().nullable(),
  entry_price: z.string().nullable(),
  mark_price: z.string().nullable(),
  liquidation_price: z.string().nullable(),
  breakeven_price: z.string().nullable(),
  floating_result: z.string().nullable(),
  floating_result_ratio: z.string().nullable(),
  margin: z.string().nullable(),
  margin_ratio: z.string().nullable(),
  settlement_symbol: z.string(),
  /** The ledger's open position for the same Account, symbol and side — null where it has none. */
  ledger_position_id: z.number().nullable(),
});

/** One Connection's futures kind: what its venue states, or why nothing is stated. */
export const venueStatementSchema = z.object({
  connection_id: z.number(),
  connection_label: z.string(),
  venue: z.string(),
  adapter_kind: z.string(),
  account_id: z.number().nullable(),
  supported: z.boolean(),
  error: z.string().nullable(),
  /** When the venue answered — the time its statement stands for; null where it stated nothing. */
  stated_at: z.string().nullable(),
  positions: z.array(livePositionSchema),
});

export const positionEventsSchema = z.object({
  fills: z.array(
    z.object({
      id: z.number(),
      side: z.enum(["buy", "sell"]),
      price: z.string(),
      size: z.string(),
      fee: z.string(),
      realized: z.string().nullable(),
      occurred_at: z.string(),
    }),
  ),
  funding: z.array(z.object({ id: z.number(), amount: z.string(), occurred_at: z.string() })),
});

export type FuturesPosition = z.infer<typeof positionSchema>;
export type UnattributableFunding = z.infer<typeof unattributableFundingSchema>;
export type Futures = z.infer<typeof futuresSchema>;
export type LivePosition = z.infer<typeof livePositionSchema>;
export type VenueStatement = z.infer<typeof venueStatementSchema>;
export type PositionEvents = z.infer<typeof positionEventsSchema>;

export async function fetchFutures(): Promise<Futures> {
  const response = await request(FUTURES_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the futures positions.`);
  }
  return futuresSchema.parse(await response.json());
}

/** Asks every venue for its open positions — a live call, so nothing here is cached by the API. */
export async function fetchLivePositions(): Promise<VenueStatement[]> {
  const response = await request(`${FUTURES_URL}/live`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the live positions.`);
  }
  return z.array(venueStatementSchema).parse(await response.json());
}

export async function fetchPositionEvents(positionId: number): Promise<PositionEvents> {
  const response = await request(`${FUTURES_URL}/positions/${positionId}/events`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the position's events.`);
  }
  return positionEventsSchema.parse(await response.json());
}
