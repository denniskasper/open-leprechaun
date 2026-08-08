import { z } from "zod";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const META_URL = "/api/meta";

export const metaSchema = z.object({
  environment: z.enum(["development", "production"]),
  version: z.string(),
});

export type Meta = z.infer<typeof metaSchema>;

export async function fetchMeta(): Promise<Meta> {
  const response = await fetch(META_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of identifying itself.`);
  }
  return metaSchema.parse(await response.json());
}
