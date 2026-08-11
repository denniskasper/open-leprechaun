import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ChangeEvent } from "react";
import {
  commitMappedImport,
  emptyDraft,
  fetchColumnMappings,
  interpretMapping,
  previewMappedImport,
  saveColumnMapping,
  type Interpretation,
  type InterpretedRow,
  type MappingDraft,
} from "@/api/mappings";
import type { Platform } from "@/api/platforms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatNumber, formatQuantity, formatTimestamp } from "@/lib/format";
import { committedWords, FileInput, PreviewReport } from "@/pages/imports";
import { TYPE_VOCABULARY } from "@/pages/transactions";

/**
 * The transaction types a mapped row may become: the single-role vocabulary —
 * one file row states one movement, so a trade's two sides and the Admin-owned
 * opening balance are deliberately absent. Mirrors the API's own list.
 */
export const MAPPED_TYPES = [
  "transfer_in",
  "transfer_out",
  "spend",
  "staking_reward",
  "lending_interest",
  "mining_reward",
  "airdrop",
  "windfall",
  "dividend",
  "distribution",
  "interest",
  "fee",
] as const;

/** The picker choice that means "one fixed value for the whole file". */
export const FIXED = "__fixed__";

/** The translation choice that means "not mapped yet" — a stated problem. */
export const UNMAPPED = "__unmapped__";

/**
 * The symbol and the type each come from a column or are fixed for the whole
 * file — exactly one of the two, so choosing one side clears the other.
 */
export function chooseSource(
  draft: MappingDraft,
  field: "symbol" | "type",
  choice: string,
): MappingDraft {
  const fixedField = field === "symbol" ? "fixed_symbol" : "fixed_type";
  if (choice === "") return { ...draft, [field]: null, [fixedField]: null };
  if (choice === FIXED) return { ...draft, [field]: null, [fixedField]: "" };
  return { ...draft, [field]: choice, [fixedField]: null };
}

/** The picker value mirroring `chooseSource` — which source is declared now. */
export function sourceChoice(draft: MappingDraft, field: "symbol" | "type"): string {
  if (field === "symbol") return draft.fixed_symbol !== null ? FIXED : (draft.symbol ?? "");
  return draft.fixed_type !== null ? FIXED : (draft.type ?? "");
}

/**
 * One translation row changed: a type value maps to a transaction type, to
 * "leave out" (the empty target — dropped aloud, never in silence), or back
 * to unmapped.
 */
export function withTranslation(draft: MappingDraft, raw: string, target: string): MappingDraft {
  const type_values = { ...draft.type_values };
  if (target === UNMAPPED) {
    delete type_values[raw];
  } else {
    type_values[raw] = target;
  }
  return { ...draft, type_values };
}

/**
 * Every type value needing a translation row: what this file carries, plus
 * what the mapping already declares — a saved mapping reused against a new
 * file keeps its rows even for values this file happens not to show.
 */
export function translationRows(seen: string[], declared: Record<string, string>): string[] {
  return [...new Set([...seen, ...Object.keys(declared)])].sort();
}

/** How many rows the file holds, said once above the interpreted preview. */
export function rowCountWords(count: number, locale?: string): string {
  return `${formatNumber(count, locale)} ${count === 1 ? "row" : "rows"} in the file`;
}

const DELIMITERS = [
  { value: ",", label: "Comma (,)" },
  { value: ";", label: "Semicolon (;)" },
  { value: "\t", label: "Tab" },
];

// UTC leads the list explicitly, so the browser's catalogue must not repeat it.
const TIMEZONES = Intl.supportedValuesOf("timeZone").filter((zone) => zone !== "UTC");

export function MappingPanel({
  platforms,
  onDone,
}: {
  platforms: Platform[];
  onDone: () => void;
}) {
  const fieldId = useId();
  const queryClient = useQueryClient();
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<{ name: string; content: string } | null>(null);
  const [draft, setDraft] = useState<MappingDraft>(emptyDraft());
  const [saveName, setSaveName] = useState("");

  const saved = useQuery({ queryKey: ["column-mappings"], queryFn: fetchColumnMappings });
  const save = useMutation({
    mutationFn: saveColumnMapping,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["column-mappings"] });
    },
  });
  const preview = useMutation({ mutationFn: previewMappedImport });
  const commit = useMutation({
    mutationFn: commitMappedImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });

  // The live interpretation, re-asked a beat after the last change — the
  // Admin watches the first rows re-read as they assign columns.
  const [settledDraft, setSettledDraft] = useState(draft);
  useEffect(() => {
    const timer = setTimeout(() => setSettledDraft(draft), 250);
    return () => clearTimeout(timer);
  }, [draft]);
  const interpreted = useQuery({
    queryKey: ["interpret", file?.name, settledDraft],
    queryFn: () => interpretMapping({ content: file?.content ?? "", mapping: settledDraft }),
    enabled: file !== null,
    placeholderData: keepPreviousData,
  });

  const complete = interpreted.data !== undefined && interpreted.data.defects.length === 0;
  const ready = complete && accountId !== "" && file !== null;

  /** Any changed input outdates what was previewed or committed. */
  function outdate(): void {
    preview.reset();
    commit.reset();
    save.reset();
  }

  function change(next: MappingDraft): void {
    outdate();
    setDraft(next);
  }

  async function choose(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    outdate();
    const chosen = event.target.files?.[0];
    setFile(chosen ? { name: chosen.name, content: await chosen.text() } : null);
  }

  function load(id: string): void {
    const entry = saved.data?.find((mapping) => String(mapping.id) === id);
    if (entry) {
      change(entry.mapping);
      setSaveName(entry.name);
    }
  }

  const columns = interpreted.data?.columns ?? [];

  return (
    <section
      aria-label="Map a file"
      className="rise space-y-6 border-y border-border py-6"
      style={{ animationDelay: "80ms" }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id={`${fieldId}-account`} label="Into Account">
          <NativeSelect
            id={`${fieldId}-account`}
            className="w-full"
            value={accountId}
            onChange={(event) => {
              outdate();
              setAccountId(event.target.value);
            }}
          >
            <option value="">Choose…</option>
            {platforms
              .filter((platform) => platform.accounts.length > 0)
              .map((platform) => (
                <optgroup key={platform.id} label={platform.name}>
                  {platform.accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
                </optgroup>
              ))}
          </NativeSelect>
        </Field>
        <Field id={`${fieldId}-file`} label="Exported file">
          <FileInput id={`${fieldId}-file`} onChange={(event) => void choose(event)} />
        </Field>
        <Field id={`${fieldId}-saved`} label="Saved mapping">
          <NativeSelect
            id={`${fieldId}-saved`}
            className="w-full"
            value=""
            onChange={(event) => load(event.target.value)}
          >
            <option value="">Start from scratch…</option>
            {(saved.data ?? []).map((mapping) => (
              <option key={mapping.id} value={mapping.id}>
                {mapping.name}
              </option>
            ))}
          </NativeSelect>
          {saved.error && (
            <p role="alert" className="text-xs text-alarm">
              The saved mappings could not be loaded.{" "}
              <button type="button" className="underline" onClick={() => void saved.refetch()}>
                Retry
              </button>
            </p>
          )}
        </Field>
      </div>

      {file !== null && interpreted.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field id={`${fieldId}-delimiter`} label="Cells are separated by">
              <NativeSelect
                id={`${fieldId}-delimiter`}
                className="w-full"
                value={draft.delimiter}
                onChange={(event) => change({ ...draft, delimiter: event.target.value })}
              >
                {DELIMITERS.map((delimiter) => (
                  <option key={delimiter.label} value={delimiter.value}>
                    {delimiter.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field id={`${fieldId}-decimal`} label="Amounts write the decimal as">
              <NativeSelect
                id={`${fieldId}-decimal`}
                className="w-full"
                value={draft.decimal_comma ? "comma" : "point"}
                onChange={(event) =>
                  change({ ...draft, decimal_comma: event.target.value === "comma" })
                }
              >
                <option value="point">Point — 1,234.56</option>
                <option value="comma">Comma — 1.234,56</option>
              </NativeSelect>
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <ColumnField
              id={`${fieldId}-occurred`}
              label="Timestamp"
              columns={columns}
              value={draft.occurred_at ?? ""}
              onChange={(column) => change({ ...draft, occurred_at: column || null })}
            />
            <Field
              id={`${fieldId}-format`}
              label="Datetime format"
              hint='As the file writes it, e.g. "%d.%m.%Y %H:%M". A format with %z reads each row&apos;s own UTC offset.'
            >
              <Input
                id={`${fieldId}-format`}
                className="font-mono text-xs"
                placeholder="%d.%m.%Y %H:%M"
                value={draft.datetime_format ?? ""}
                onChange={(event) =>
                  change({ ...draft, datetime_format: event.target.value || null })
                }
              />
            </Field>
            <Field id={`${fieldId}-timezone`} label="Timezone of bare timestamps">
              <NativeSelect
                id={`${fieldId}-timezone`}
                className="w-full"
                value={draft.timezone ?? ""}
                onChange={(event) => change({ ...draft, timezone: event.target.value || null })}
              >
                <option value="">Choose…</option>
                <option value="UTC">UTC</option>
                {TIMEZONES.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <ColumnField
              id={`${fieldId}-quantity`}
              label="Quantity"
              columns={columns}
              value={draft.quantity ?? ""}
              onChange={(column) => change({ ...draft, quantity: column || null })}
            />
            <SourceField
              id={`${fieldId}-symbol`}
              label="Symbol"
              fixedLabel="One symbol for the whole file…"
              columns={columns}
              choice={sourceChoice(draft, "symbol")}
              onChoice={(choice) => change(chooseSource(draft, "symbol", choice))}
            >
              {draft.fixed_symbol !== null && (
                <Input
                  aria-label="Fixed symbol"
                  className="mt-1.5 font-mono text-xs uppercase"
                  placeholder="BTC"
                  value={draft.fixed_symbol}
                  onChange={(event) =>
                    change({ ...draft, fixed_symbol: event.target.value.toUpperCase() })
                  }
                />
              )}
            </SourceField>
            <SourceField
              id={`${fieldId}-type`}
              label="Type"
              fixedLabel="One type for the whole file…"
              columns={columns}
              choice={sourceChoice(draft, "type")}
              onChoice={(choice) => change(chooseSource(draft, "type", choice))}
            >
              {draft.fixed_type !== null && (
                <NativeSelect
                  aria-label="Fixed type"
                  className="mt-1.5 w-full"
                  value={draft.fixed_type}
                  onChange={(event) => change({ ...draft, fixed_type: event.target.value })}
                >
                  <option value="">Choose…</option>
                  {MAPPED_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {TYPE_VOCABULARY[type].label}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </SourceField>
            <ColumnField
              id={`${fieldId}-external`}
              label="Identifier"
              absentLabel="None — derive from row content"
              columns={columns}
              value={draft.external_id ?? ""}
              onChange={(column) => change({ ...draft, external_id: column || null })}
            />
            <ColumnField
              id={`${fieldId}-fee`}
              label="Fee, in the same asset"
              absentLabel="No fee column"
              columns={columns}
              value={draft.fee_quantity ?? ""}
              onChange={(column) => change({ ...draft, fee_quantity: column || null })}
            />
            <ColumnField
              id={`${fieldId}-note`}
              label="Note"
              absentLabel="No note column"
              columns={columns}
              value={draft.note ?? ""}
              onChange={(column) => change({ ...draft, note: column || null })}
            />
          </div>

          {draft.type !== null && (
            <TranslationTable
              seen={interpreted.data.type_values_seen}
              draft={draft}
              onChange={change}
            />
          )}

          {interpreted.data.defects.length > 0 && (
            <ul className="space-y-1 text-sm text-caution" aria-label="Still missing">
              {interpreted.data.defects.map((defect) => (
                <li key={defect}>{defect}</li>
              ))}
            </ul>
          )}

          <InterpretedPreview interpretation={interpreted.data} />

          <div className="flex flex-wrap items-end gap-2.5">
            <Field id={`${fieldId}-name`} label="Save this mapping as">
              <Input
                id={`${fieldId}-name`}
                placeholder="The venue's name"
                value={saveName}
                onChange={(event) => {
                  save.reset();
                  setSaveName(event.target.value);
                }}
              />
            </Field>
            <Button
              variant="outline"
              disabled={!complete || saveName.trim() === "" || save.isPending}
              onClick={() => save.mutate({ name: saveName, mapping: draft })}
            >
              {save.isPending ? "Saving…" : "Save mapping"}
            </Button>
            {save.isSuccess && (
              <p className="pb-2 font-mono text-xs text-signal">
                Saved — a later file reuses it from the picker.
              </p>
            )}
            {save.error && (
              <p role="alert" className="pb-2 text-sm text-alarm">
                {save.error.message}
              </p>
            )}
          </div>
        </>
      )}

      {interpreted.error && (
        <p role="alert" className="text-sm text-alarm">
          {interpreted.error.message}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          variant="outline"
          disabled={!ready || preview.isPending || preview.isSuccess}
          onClick={() => {
            if (!ready || !file) return;
            preview.mutate({ account_id: Number(accountId), content: file.content, mapping: draft });
          }}
        >
          {preview.isPending ? "Previewing…" : "Preview import"}
        </Button>
        {preview.isSuccess && !commit.isSuccess && (
          <Button
            disabled={commit.isPending}
            onClick={() => {
              if (!ready || !file) return;
              commit.mutate({
                account_id: Number(accountId),
                content: file.content,
                mapping: draft,
                label: file.name,
              });
            }}
          >
            {commit.isPending ? "Committing…" : "Commit import"}
          </Button>
        )}
        <Button variant="ghost" className="text-muted-foreground" onClick={onDone}>
          {commit.isSuccess ? "Done" : "Cancel"}
        </Button>
        {commit.isSuccess && (
          <p className="font-mono text-xs text-signal">{committedWords(commit.data)}</p>
        )}
      </div>

      {preview.error && (
        <p role="alert" className="text-sm text-alarm">
          {preview.error.message}
        </p>
      )}
      {commit.error && (
        <p role="alert" className="text-sm text-alarm">
          {commit.error.message}
        </p>
      )}
      {preview.isSuccess && <PreviewReport preview={preview.data} />}
    </section>
  );
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="microlabel block text-muted-foreground">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function ColumnField({
  id,
  label,
  columns,
  value,
  onChange,
  absentLabel = "Choose…",
}: {
  id: string;
  label: string;
  columns: string[];
  value: string;
  onChange: (column: string) => void;
  absentLabel?: string;
}) {
  return (
    <Field id={id} label={label}>
      <NativeSelect
        id={id}
        className="w-full"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{absentLabel}</option>
        {columns.map((column) => (
          <option key={column} value={column}>
            {column}
          </option>
        ))}
      </NativeSelect>
    </Field>
  );
}

function SourceField({
  id,
  label,
  fixedLabel,
  columns,
  choice,
  onChoice,
  children,
}: {
  id: string;
  label: string;
  fixedLabel: string;
  columns: string[];
  choice: string;
  onChoice: (choice: string) => void;
  children?: React.ReactNode;
}) {
  return (
    <Field id={id} label={label}>
      <NativeSelect
        id={id}
        className="w-full"
        value={choice}
        onChange={(event) => onChoice(event.target.value)}
      >
        <option value="">Choose…</option>
        {columns.map((column) => (
          <option key={column} value={column}>
            {column}
          </option>
        ))}
        <option value={FIXED}>{fixedLabel}</option>
      </NativeSelect>
      {children}
    </Field>
  );
}

/**
 * Every value the type column carries, each with its translation into the
 * ledger's vocabulary — or an explicit "leave out", dropped aloud at import.
 */
function TranslationTable({
  seen,
  draft,
  onChange,
}: {
  seen: string[];
  draft: MappingDraft;
  onChange: (draft: MappingDraft) => void;
}) {
  const rows = translationRows(seen, draft.type_values);
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2" aria-label="Type translations">
      <p className="microlabel text-muted-foreground">
        The file's type values, each mapped or deliberately left out
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((raw) => {
          const target = raw in draft.type_values ? draft.type_values[raw] : UNMAPPED;
          return (
            <div key={raw} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={raw}>
                {raw}
              </span>
              <NativeSelect
                aria-label={`Type for ${raw}`}
                className="flex-1"
                value={target}
                onChange={(event) => onChange(withTranslation(draft, raw, event.target.value))}
              >
                <option value={UNMAPPED}>Choose…</option>
                <option value="">Leave out</option>
                {MAPPED_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {TYPE_VOCABULARY[type].label}
                  </option>
                ))}
              </NativeSelect>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The first rows as the import would read them, re-rendered live as the
 * mapping changes: readable cells as ledger values, unreadable ones named in
 * their row, deliberately dropped rows dimmed with their reason.
 */
function InterpretedPreview({ interpretation }: { interpretation: Interpretation }) {
  return (
    <div className="space-y-2" aria-label="Interpreted rows">
      <p className="microlabel text-muted-foreground">{rowCountWords(interpretation.row_count)}</p>
      {interpretation.rows.length > 0 && (
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-border text-left">
              {["#", "When", "Type", "Symbol", "Quantity", "Fee"].map((column) => (
                <th key={column} scope="col" className="microlabel py-2 pr-4 text-muted-foreground">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {interpretation.rows.map((row) => (
              <InterpretedRowLine key={row.number} row={row} />
            ))}
          </tbody>
        </table>
      )}
      {interpretation.row_count > interpretation.rows.length && (
        <p className="font-mono text-xs text-muted-foreground">
          …and {formatNumber(interpretation.row_count - interpretation.rows.length)} more, read the
          same way.
        </p>
      )}
    </div>
  );
}

function InterpretedRowLine({ row }: { row: InterpretedRow }) {
  const dimmed = row.left_out !== null ? "opacity-60" : "";
  return (
    <>
      <tr className={`border-b border-border align-top ${dimmed}`}>
        <td className="py-2 pr-4 font-mono tabular-nums text-muted-foreground">{row.number}</td>
        <td className="py-2 pr-4 font-mono tabular-nums">
          {row.occurred_at !== null ? formatTimestamp(Date.parse(row.occurred_at)) : "—"}
        </td>
        <td className="py-2 pr-4">
          {row.type !== null
            ? (TYPE_VOCABULARY[row.type as keyof typeof TYPE_VOCABULARY]?.label ?? row.type)
            : "—"}
        </td>
        <td className="py-2 pr-4 font-mono">{row.symbol ?? "—"}</td>
        <td className="py-2 pr-4 font-mono tabular-nums">
          {row.quantity !== null ? formatQuantity(row.quantity) : "—"}
        </td>
        <td className="py-2 font-mono tabular-nums">
          {row.fee_quantity !== null ? formatQuantity(row.fee_quantity) : ""}
        </td>
      </tr>
      {(row.problems.length > 0 || row.left_out !== null) && (
        <tr className="border-b border-border">
          <td />
          <td colSpan={5} className="pb-2 text-xs">
            {row.left_out !== null && (
              <span className="text-muted-foreground">Left out — {row.left_out}.</span>
            )}
            {row.problems.map((problem) => (
              <span key={problem} className="block text-alarm">
                {problem}
              </span>
            ))}
          </td>
        </tr>
      )}
    </>
  );
}
