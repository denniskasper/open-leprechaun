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

export const HEALTH_REPORT_URL = "/api/health/report";

const instant = z.string().nullable();

/**
 * The health panel's report: every data provider, Connection and scheduled
 * task on its own, and what the store holds. A provider's `rate_limited` is
 * its own state, never an outage, and `never_asked` until something has
 * asked it; `affected_instruments` are the ones its failure left without a
 * fresh price — empty while it answers.
 */
export const healthReportSchema = z.object({
  checked_at: z.string(),
  providers: z.array(
    z.object({
      name: z.string(),
      feeds: z.enum(["crypto_prices", "security_prices", "reference_rates"]),
      state: z.enum(["ok", "rate_limited", "outage", "never_asked"]),
      last_success_at: instant,
      last_error_at: instant,
      last_error: z.string().nullable(),
      affected_instruments: z.array(
        z.object({ id: z.number(), symbol: z.string(), name: z.string() }),
      ),
    }),
  ),
  connections: z.array(
    z.object({
      id: z.number(),
      label: z.string(),
      venue: z.string(),
      last_sync_at: instant,
      kinds: z.array(
        z.object({
          adapter_kind: z.string(),
          ok: z.boolean(),
          last_success_at: instant,
          last_error_at: instant,
          last_error: z.string().nullable(),
        }),
      ),
    }),
  ),
  tasks: z.array(
    z.object({
      key: z.string(),
      name: z.string(),
      enabled: z.boolean(),
      running: z.boolean(),
      last_started_at: instant,
      last_finished_at: instant,
      outcome: z.enum(["ok", "failed"]).nullable(),
      error: z.string().nullable(),
      next_due_at: instant,
    }),
  ),
  scheduler_enabled: z.boolean(),
  storage: z.object({
    database_bytes: z.number(),
    crypto_daily_closes: z.number(),
    security_daily_closes: z.number(),
    reference_rates: z.number(),
  }),
});

export type HealthReport = z.infer<typeof healthReportSchema>;

export async function fetchHealthReport(): Promise<HealthReport> {
  const response = await fetch(HEALTH_REPORT_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of a health report.`);
  }
  return healthReportSchema.parse(await response.json());
}
