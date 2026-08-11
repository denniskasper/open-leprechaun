import { z } from "zod";
import { postJson, refusal } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const IMPORT_BATCHES_URL = "/api/import-batches";
export const CSV_CONNECTORS_URL = "/api/csv-connectors";
export const CSV_IMPORTS_URL = "/api/csv-imports";

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

/**
 * One exported file the ledger can read (ticket 32): which export to produce,
 * and the timezone its timestamps are read in — a local-time export is a
 * declared fact, never a surprise.
 */
export const csvConnectorSchema = z.object({
  connector: z.string(),
  name: z.string(),
  expects: z.string(),
  timezone: z.string(),
});

export type CsvConnector = z.infer<typeof csvConnectorSchema>;

/** What committing the file would do — computed without writing anything. */
export const importPreviewSchema = z.object({
  to_create: z.array(
    z.object({
      external_id: z.string(),
      type: z.string(),
      occurred_at: z.iso.datetime({ offset: true }),
    }),
  ),
  duplicates: z.number(),
  duplicate_external_ids: z.array(z.string()),
  skipped: z.array(z.object({ external_id: z.string(), reason: z.string() })),
  new_instruments: z.array(z.object({ kind: z.string(), symbol: z.string(), name: z.string() })),
  warnings: z.array(z.string()),
});

export type ImportPreview = z.infer<typeof importPreviewSchema>;

/** What the commit did. batch_id is null when nothing was new — a pure re-import records no batch. */
export const committedImportSchema = z.object({
  batch_id: z.number().nullable(),
  created: z.number(),
  duplicates: z.number(),
  skipped: z.number(),
  instruments_created: z.number(),
});

export type CommittedImport = z.infer<typeof committedImportSchema>;

export interface ImportFile {
  connector: string;
  account_id: number;
  /** The exported file itself, as the text it is. */
  content: string;
}

export async function fetchCsvConnectors(): Promise<CsvConnector[]> {
  const response = await fetch(CSV_CONNECTORS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing the connectors.`);
  }
  return z.array(csvConnectorSchema).parse(await response.json());
}

export async function previewCsvImport(file: ImportFile): Promise<ImportPreview> {
  const response = await postJson(`${CSV_IMPORTS_URL}/preview`, file);
  if (!response.ok) {
    throw await refusal(response, "The file could not be previewed.");
  }
  return importPreviewSchema.parse(await response.json());
}

export async function commitCsvImport(
  file: ImportFile & { label: string },
): Promise<CommittedImport> {
  const response = await postJson(CSV_IMPORTS_URL, file);
  if (!response.ok) {
    throw await refusal(response, "The import could not be committed.");
  }
  return committedImportSchema.parse(await response.json());
}
