import { z } from "zod";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const LEDGER_EXPORT_URL = "/api/ledger-export";

/** The independent tools the ledger can be written for — one, so far. */
export const exportFormatSchema = z.enum(["cointracking"]);

/** A Transaction the file does not carry, with the API's sentence saying why. */
export const leftOutSchema = z.object({
  transaction_id: z.number(),
  type: z.string(),
  occurred_at: z.iso.datetime({ offset: true }),
  reason: z.string(),
});

/**
 * What the export file holds and what it could not: the rows it carries, and
 * every Transaction left out of it — nothing is dropped without being named.
 */
export const ledgerExportSchema = z.object({
  format: exportFormatSchema,
  filename: z.string(),
  row_count: z.number(),
  left_out: z.array(leftOutSchema),
});

export type ExportFormat = z.infer<typeof exportFormatSchema>;
export type LeftOut = z.infer<typeof leftOutSchema>;
export type LedgerExport = z.infer<typeof ledgerExportSchema>;

export async function fetchLedgerExport(): Promise<LedgerExport> {
  const response = await fetch(LEDGER_EXPORT_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the ledger export.`);
  }
  return ledgerExportSchema.parse(await response.json());
}

/** Where the file itself is downloaded from — a plain link, never a fetch. */
export function ledgerExportFileUrl(format: ExportFormat): string {
  return `${LEDGER_EXPORT_URL}/${format}.csv`;
}
