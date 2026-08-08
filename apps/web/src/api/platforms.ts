import { z } from "zod";
import { postJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const PLATFORMS_URL = "/api/platforms";

/** The five kinds of place that hold value; "exchange" is one of them, never a synonym for all. */
export const platformKindSchema = z.enum([
  "exchange",
  "cold_storage",
  "software_wallet",
  "broker",
  "bank",
]);

export const accountSchema = z.object({
  id: z.number(),
  name: z.string(),
  chain: z.string().nullable(),
  external_reference: z.string().nullable(),
  access_software: z.string().nullable(),
});

export const platformSchema = z.object({
  id: z.number(),
  name: z.string(),
  kind: platformKindSchema,
  accounts: z.array(accountSchema),
});

export type PlatformKind = z.infer<typeof platformKindSchema>;
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
