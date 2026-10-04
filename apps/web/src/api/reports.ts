import { z } from "zod";
import { postJson, refusal, request } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const REPORTS_URL = "/api/reports";

/**
 * One report as a listing shows it: a frozen artifact for one Tax Year,
 * `draft` until finalised, and `stale` once the inputs it was generated from
 * have changed underneath it.
 */
export const reportSummarySchema = z.object({
  id: z.number(),
  year: z.number(),
  status: z.enum(["draft", "final"]),
  generated_at: z.string(),
  stale: z.boolean(),
});

export type ReportSummary = z.infer<typeof reportSummarySchema>;

/** Every report, newest first. */
export async function fetchReports(): Promise<ReportSummary[]> {
  const response = await request(REPORTS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the reports.`);
  }
  return z.array(reportSummarySchema).parse(await response.json());
}

/**
 * Generates a new draft report for the Tax Year and answers its id. A year
 * the ledger cannot honestly state is refused in the API's own sentence,
 * which names what stands in the way.
 */
export async function generateReport(year: number): Promise<number> {
  const response = await postJson(REPORTS_URL, { year });
  if (!response.ok) {
    throw await refusal(response, `The ${year} report could not be generated.`);
  }
  return z.object({ id: z.number() }).parse(await response.json()).id;
}

/** Where a report's appendix — every figure with its working — downloads from. */
export function appendixUrl(reportId: number, format: "pdf" | "csv"): string {
  return `${REPORTS_URL}/${reportId}/appendix.${format}`;
}
