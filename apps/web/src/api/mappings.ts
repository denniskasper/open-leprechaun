import { z } from "zod";
import { postJson, refusal } from "@/api/http";
import { committedImportSchema, importPreviewSchema } from "@/api/imports";
import type { CommittedImport, ImportPreview } from "@/api/imports";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const COLUMN_MAPPINGS_URL = "/api/column-mappings";
export const MAPPED_IMPORTS_URL = "/api/mapped-imports";

/**
 * One file shape as the Admin declares it (ticket 33): which column carries
 * which ledger field, the exact datetime format and timezone, the delimiter
 * and decimal convention. Every field is optional so a half-built mapping can
 * be interpreted live; the API names what a complete one still lacks.
 */
export const mappingDraftSchema = z.object({
  occurred_at: z.string().nullable(),
  datetime_format: z.string().nullable(),
  timezone: z.string().nullable(),
  quantity: z.string().nullable(),
  symbol: z.string().nullable(),
  fixed_symbol: z.string().nullable(),
  type: z.string().nullable(),
  fixed_type: z.string().nullable(),
  type_values: z.record(z.string(), z.string()),
  external_id: z.string().nullable(),
  fee_quantity: z.string().nullable(),
  note: z.string().nullable(),
  delimiter: z.string(),
  decimal_comma: z.boolean(),
});

export type MappingDraft = z.infer<typeof mappingDraftSchema>;

/** A mapping with nothing declared yet — the screen's starting point. */
export function emptyDraft(): MappingDraft {
  return {
    occurred_at: null,
    datetime_format: null,
    timezone: null,
    quantity: null,
    symbol: null,
    fixed_symbol: null,
    type: null,
    fixed_type: null,
    type_values: {},
    external_id: null,
    fee_quantity: null,
    note: null,
    delimiter: ",",
    decimal_comma: false,
  };
}

/**
 * One row as the import would read it: the timestamp already in UTC,
 * quantities as fixed-point strings, each unreadable cell named in
 * `problems`, and `left_out` carrying the reason where the import would
 * deliberately drop the row.
 */
export const interpretedRowSchema = z.object({
  number: z.number(),
  external_id: z.string().nullable(),
  occurred_at: z.iso.datetime({ offset: true }).nullable(),
  type: z.string().nullable(),
  symbol: z.string().nullable(),
  quantity: z.string().nullable(),
  fee_quantity: z.string().nullable(),
  note: z.string().nullable(),
  left_out: z.string().nullable(),
  problems: z.array(z.string()),
});

export type InterpretedRow = z.infer<typeof interpretedRowSchema>;

/**
 * The live preview's whole answer: the file's columns for the pickers, the
 * first rows as interpreted, the defects a complete mapping still lacks, and
 * every distinct value the type column carries for the translation rows.
 */
export const interpretationSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(interpretedRowSchema),
  row_count: z.number(),
  defects: z.array(z.string()),
  type_values_seen: z.array(z.string()),
});

export type Interpretation = z.infer<typeof interpretationSchema>;

export const savedMappingSchema = z.object({
  id: z.number(),
  name: z.string(),
  mapping: mappingDraftSchema,
  created_at: z.iso.datetime({ offset: true }),
});

export type SavedMapping = z.infer<typeof savedMappingSchema>;

export async function interpretMapping(request: {
  content: string;
  mapping: MappingDraft;
}): Promise<Interpretation> {
  const response = await postJson(`${COLUMN_MAPPINGS_URL}/interpret`, request);
  if (!response.ok) {
    throw await refusal(response, "The file could not be interpreted.");
  }
  return interpretationSchema.parse(await response.json());
}

export async function fetchColumnMappings(): Promise<SavedMapping[]> {
  const response = await fetch(COLUMN_MAPPINGS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing the saved mappings.`);
  }
  return z.array(savedMappingSchema).parse(await response.json());
}

export async function saveColumnMapping(request: {
  name: string;
  mapping: MappingDraft;
}): Promise<SavedMapping> {
  const response = await postJson(COLUMN_MAPPINGS_URL, request);
  if (!response.ok) {
    throw await refusal(response, "The mapping could not be saved.");
  }
  return savedMappingSchema.parse(await response.json());
}

export async function deleteColumnMapping(mappingId: number): Promise<void> {
  const response = await fetch(`${COLUMN_MAPPINGS_URL}/${mappingId}`, { method: "DELETE" });
  if (!response.ok) {
    throw await refusal(response, "The saved mapping could not be deleted.");
  }
}

export interface MappedFile {
  account_id: number;
  /** The exported file itself, as the text it is. */
  content: string;
  mapping: MappingDraft;
}

export async function previewMappedImport(file: MappedFile): Promise<ImportPreview> {
  const response = await postJson(`${MAPPED_IMPORTS_URL}/preview`, file);
  if (!response.ok) {
    throw await refusal(response, "The file could not be previewed.");
  }
  return importPreviewSchema.parse(await response.json());
}

export async function commitMappedImport(
  file: MappedFile & { label: string },
): Promise<CommittedImport> {
  const response = await postJson(MAPPED_IMPORTS_URL, file);
  if (!response.ok) {
    throw await refusal(response, "The import could not be committed.");
  }
  return committedImportSchema.parse(await response.json());
}
