import { z } from "zod";
import { refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const IMPORT_BATCHES_URL = "/api/import-batches";

/**
 * One import, recorded as a unit and reversible as a unit (ticket 31). The
 * connectors that produce batches arrive with later tickets; this page shows
 * what every one of them leaves behind.
 */
export const importBatchSchema = z.object({
  id: z.number(),
  /** The per-kind provenance string — one half of the deduplication key. */
  source: z.string(),
  /** What the Admin imported, in their words — a filename, usually. */
  label: z.string(),
  account_id: z.number(),
  created_at: z.iso.datetime({ offset: true }),
  /** How many rows the batch registered. */
  rows: z.number(),
  /** How many of those the Admin has since edited or deleted by hand. */
  overridden: z.number(),
});

export type ImportBatch = z.infer<typeof importBatchSchema>;

export async function fetchImportBatches(): Promise<ImportBatch[]> {
  const response = await fetch(IMPORT_BATCHES_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing import batches.`);
  }
  return z.array(importBatchSchema).parse(await response.json());
}

export async function reverseImportBatch(batchId: number): Promise<void> {
  const response = await fetch(`${IMPORT_BATCHES_URL}/${batchId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The Import Batch could not be reversed.");
  }
}
