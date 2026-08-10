import { z } from "zod";
import { postJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const CONNECTIONS_URL = "/api/connections";

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
});

export const adapterStatusSchema = z.object({
  adapter_kind: z.string(),
  last_success_at: z.string().nullable(),
  last_error_at: z.string().nullable(),
  last_error: z.string().nullable(),
});

/**
 * Everything the API ever returns of a Connection: a label, a fingerprint, a
 * last-used timestamp and per-kind results — never secret material, in any
 * form.
 */
export const connectionSchema = z.object({
  id: z.number(),
  platform_id: z.number(),
  venue: z.string(),
  label: z.string(),
  fingerprint: z.string(),
  last_used_at: z.string().nullable(),
  statuses: z.array(adapterStatusSchema),
});

export type Venue = z.infer<typeof venueSchema>;
export type AdapterStatus = z.infer<typeof adapterStatusSchema>;
export type Connection = z.infer<typeof connectionSchema>;

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
