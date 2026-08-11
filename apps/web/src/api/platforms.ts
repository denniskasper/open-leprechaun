import { z } from "zod";
import { postJson, putJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const PLATFORMS_URL = "/api/platforms";
export const ACCOUNTS_URL = "/api/accounts";

/** The five kinds of place that hold value; "exchange" is one of them, never a synonym for all. */
export const platformKindSchema = z.enum([
  "exchange",
  "cold_storage",
  "software_wallet",
  "broker",
  "bank",
]);

/**
 * How a broker treats income at source (ticket 43): withheld already, or
 * arriving gross with everything still to declare.
 */
export const withholdingSchema = z.enum(["at_source", "none"]);

export const accountSchema = z.object({
  id: z.number(),
  name: z.string(),
  chain: z.string().nullable(),
  external_reference: z.string().nullable(),
  access_software: z.string().nullable(),
  /** This Account's exception to its Platform's withholding; null means the Platform's word stands. */
  withholding_override: withholdingSchema.nullable(),
  base_currency: z.string().nullable(),
});

export const platformSchema = z.object({
  id: z.number(),
  name: z.string(),
  kind: platformKindSchema,
  /** Only ever set on a broker; a Depot may hold nothing until it is. */
  withholding: withholdingSchema.nullable(),
  /** Fixed-point decimal string off the API; absent means no exemption order. */
  exemption_order_eur: z.string().nullable(),
  accounts: z.array(accountSchema),
});

export type PlatformKind = z.infer<typeof platformKindSchema>;
export type Withholding = z.infer<typeof withholdingSchema>;
export type Account = z.infer<typeof accountSchema>;
export type Platform = z.infer<typeof platformSchema>;

export interface NewPlatform {
  name: string;
  kind: PlatformKind;
}

export interface NewAccount {
  name: string;
  chain: string | null;
  external_reference: string | null;
  access_software: string | null;
  base_currency: string | null;
}

export interface NewWithholding {
  behaviour: Withholding;
  /** Fixed-point decimal string — money never crosses JSON as a number. */
  exemption_order_eur: string | null;
}

export async function fetchPlatforms(): Promise<Platform[]> {
  const response = await fetch(PLATFORMS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing platforms.`);
  }
  return z.array(platformSchema).parse(await response.json());
}

export async function registerPlatform(platform: NewPlatform): Promise<void> {
  const response = await postJson(PLATFORMS_URL, platform);
  if (!response.ok) {
    throw await refusal(response, "The Platform could not be registered.");
  }
}

export async function addAccount(platformId: number, account: NewAccount): Promise<void> {
  const response = await postJson(`${PLATFORMS_URL}/${platformId}/accounts`, account);
  if (!response.ok) {
    throw await refusal(response, "The Account could not be added.");
  }
}

export async function setWithholding(
  platformId: number,
  withholding: NewWithholding,
): Promise<void> {
  const response = await putJson(`${PLATFORMS_URL}/${platformId}/withholding`, withholding);
  if (!response.ok) {
    throw await refusal(response, "The withholding behaviour could not be recorded.");
  }
}

export async function setWithholdingOverride(
  accountId: number,
  behaviour: Withholding | null,
): Promise<void> {
  const response = await putJson(`${ACCOUNTS_URL}/${accountId}/withholding-override`, { behaviour });
  if (!response.ok) {
    throw await refusal(response, "The withholding override could not be recorded.");
  }
}
