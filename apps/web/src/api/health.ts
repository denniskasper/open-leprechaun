import { z } from "zod";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const HEALTH_URL = "/api/health";

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  database: z.enum(["up", "down"]),
});

export type Health = z.infer<typeof healthSchema>;

export async function fetchHealth(): Promise<Health> {
  const response = await fetch(HEALTH_URL);

  // A degraded service answers 503 with a body that still says what is wrong, so
  // the body is read before the status is judged. Only an unreadable body — a
  // proxy error page, say — means there is no report to show.
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new Error(`The API answered ${response.status} without a health report.`);
  }

  return healthSchema.parse(body);
}
