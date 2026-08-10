import { z } from "zod";
import { postJson, putJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const CONNECTIONS_URL = "/api/connections";

/**
 * One adapter kind a venue serves, with its declared capability: how far back
 * the venue actually reaches — null where its history is unbounded.
 */
export const venueAdapterSchema = z.object({
  kind: z.string(),
  lookback_days: z.number().nullable(),
});

/**
 * A venue as the registry describes it: what its credential is made of and
 * the read-only scope to grant when minting the key there.
 */
export const venueSchema = z.object({
  venue: z.string(),
  name: z.string(),
  required_scope: z.string(),
  requires_secret: z.boolean(),
  requires_passphrase: z.boolean(),
  /** The kinds this venue's adapters serve — empty until its adapters ship. */
  adapters: z.array(venueAdapterSchema),
});

export const adapterStatusSchema = z.object({
  adapter_kind: z.string(),
  last_success_at: z.string().nullable(),
  last_error_at: z.string().nullable(),
  last_error: z.string().nullable(),
});

/** Which Account one adapter kind writes into. */
export const accountPairingSchema = z.object({
  adapter_kind: z.string(),
  account_id: z.number(),
});

/**
 * Everything the API ever returns of a Connection: a label, a fingerprint, a
 * last-used timestamp, per-kind results and per-kind Account pairings —
 * never secret material, in any form.
 */
export const connectionSchema = z.object({
  id: z.number(),
  platform_id: z.number(),
  venue: z.string(),
  label: z.string(),
  fingerprint: z.string(),
  last_used_at: z.string().nullable(),
  statuses: z.array(adapterStatusSchema),
  pairings: z.array(accountPairingSchema),
});

/** One adapter kind's test outcome — the venue's sentence or the failure's. */
export const kindTestResultSchema = z.object({
  adapter_kind: z.string(),
  ok: z.boolean(),
  detail: z.string().nullable(),
  error: z.string().nullable(),
});

/** One adapter kind's sync outcome; what landed stays reported beside an error. */
export const kindSyncResultSchema = z.object({
  adapter_kind: z.string(),
  ok: z.boolean(),
  error: z.string().nullable(),
  /** How far back the pull reached — null where nothing was pulled. */
  covered_days: z.number().nullable(),
  futures: z.object({ new_fills: z.number(), new_funding: z.number() }).nullable(),
  imported: z
    .object({
      batch_id: z.number().nullable(),
      created: z.number(),
      duplicates: z.number(),
      skipped: z.number(),
    })
    .nullable(),
});

/**
 * One venue account whose synced coverage begins after the earliest activity
 * recorded elsewhere — a silent history gap, named so the Admin can close it
 * by importing the older history.
 */
export const coverageWarningSchema = z.object({
  connection_id: z.number(),
  connection_label: z.string(),
  venue: z.string(),
  platform_name: z.string(),
  account_id: z.number(),
  account_name: z.string(),
  coverage_starts_at: z.string(),
  earliest_elsewhere_at: z.string(),
});

export type Venue = z.infer<typeof venueSchema>;
export type VenueAdapter = z.infer<typeof venueAdapterSchema>;
export type CoverageWarning = z.infer<typeof coverageWarningSchema>;
export type AdapterStatus = z.infer<typeof adapterStatusSchema>;
export type AccountPairing = z.infer<typeof accountPairingSchema>;
export type Connection = z.infer<typeof connectionSchema>;
export type KindTestResult = z.infer<typeof kindTestResultSchema>;
export type KindSyncResult = z.infer<typeof kindSyncResultSchema>;

export interface NewConnection {
  platform_id: number;
  venue: string;
  label: string;
  key: string;
  secret: string | null;
  passphrase: string | null;
}

export async function fetchVenues(): Promise<Venue[]> {
  const response = await fetch(`${CONNECTIONS_URL}/venues`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing venues.`);
  }
  return z.array(venueSchema).parse(await response.json());
}

export async function fetchConnections(): Promise<Connection[]> {
  const response = await fetch(CONNECTIONS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing connections.`);
  }
  return z.array(connectionSchema).parse(await response.json());
}

export async function fetchCoverageWarnings(): Promise<CoverageWarning[]> {
  const response = await fetch(`${CONNECTIONS_URL}/coverage-warnings`);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing coverage warnings.`);
  }
  return z.array(coverageWarningSchema).parse(await response.json());
}

export async function registerConnection(connection: NewConnection): Promise<void> {
  const response = await postJson(CONNECTIONS_URL, connection);
  if (!response.ok) {
    throw await refusal(response, "The Connection could not be stored.");
  }
}

export async function removeConnection(connectionId: number): Promise<void> {
  const response = await fetch(`${CONNECTIONS_URL}/${connectionId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The Connection could not be removed.");
  }
}

export async function testConnection(connectionId: number): Promise<KindTestResult[]> {
  const response = await postJson(`${CONNECTIONS_URL}/${connectionId}/test`, {});
  if (!response.ok) {
    throw await refusal(response, "The Connection could not be tested.");
  }
  return z.array(kindTestResultSchema).parse(await response.json());
}

export async function syncConnection(connectionId: number): Promise<KindSyncResult[]> {
  const response = await postJson(`${CONNECTIONS_URL}/${connectionId}/sync`, {});
  if (!response.ok) {
    throw await refusal(response, "The Connection could not be synced.");
  }
  return z.array(kindSyncResultSchema).parse(await response.json());
}

export async function pairAccount(
  connectionId: number,
  adapterKind: string,
  accountId: number,
): Promise<void> {
  const response = await putJson(`${CONNECTIONS_URL}/${connectionId}/pairings/${adapterKind}`, {
    account_id: accountId,
  });
  if (!response.ok) {
    throw await refusal(response, "The Account could not be paired.");
  }
}
