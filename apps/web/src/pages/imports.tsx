import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Table2, Undo2 } from "lucide-react";
import { useId, useState, type ChangeEvent } from "react";
import {
  commitCsvImport,
  fetchCsvConnectors,
  fetchImportBatches,
  previewCsvImport,
  reverseImportBatch,
  type CommittedImport,
  type CsvConnector,
  type ImportBatch,
  type ImportPreview,
} from "@/api/imports";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { MappingPanel } from "@/pages/imports-mapping";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { formatNumber, formatTimestamp } from "@/lib/format";

/** How a batch's row counts read in one line: what it holds, what the Admin has taken over. */
export function rowsWords(batch: ImportBatch): string {
  const rows = batch.rows === 1 ? "1 row" : `${batch.rows} rows`;
  return batch.overridden === 0 ? rows : `${rows} · ${batch.overridden} overridden`;
}

function count(quantity: number, noun: string, locale?: string): string {
  return `${formatNumber(quantity, locale)} ${quantity === 1 ? noun : `${noun}s`}`;
}

/**
 * What the connector declares about its venue's clock, in one line: an
 * export in local time is a stated fact the Admin sees before previewing,
 * never a silent assumption.
 */
export function timezoneWords(connector: CsvConnector): string {
  return connector.timezone === "UTC"
    ? "Timestamps are read as UTC."
    : `Bare timestamps are read as ${connector.timezone} time and converted to UTC.`;
}

/** What the commit did, in one line — "nothing new" said as plainly as a landing. */
export function committedWords(committed: CommittedImport, locale?: string): string {
  if (committed.batch_id === null) {
    return "Nothing new — the ledger already knows everything in this file.";
  }
  const parts = [count(committed.created, "row", locale) + " created"];
  if (committed.duplicates > 0) {
    parts.push(`${formatNumber(committed.duplicates, locale)} already known`);
  }
  if (committed.skipped > 0) parts.push(`${formatNumber(committed.skipped, locale)} left out`);
  if (committed.instruments_created > 0) {
    parts.push(count(committed.instruments_created, "Instrument", locale) + " created");
  }
  return parts.join(" · ");
}

export function ImportsPage() {
  // Which flow is open: a shipped connector's file, or the Admin's own
  // column mapping for a venue nothing ships a connector for.
  const [flow, setFlow] = useState<"connector" | "mapping" | null>(null);
  const importing = flow !== null;
  const batches = useQuery({ queryKey: ["import-batches"], queryFn: fetchImportBatches });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });
  const connectors = useQuery({ queryKey: ["csv-connectors"], queryFn: fetchCsvConnectors });

  const failed = batches.error ?? platforms.error ?? connectors.error;
  const loaded = batches.data && platforms.data && connectors.data;

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Imports"
        description="Every import, recorded as a batch and reversible as a unit. An import previews before it writes, commits as a separate act, and re-importing the same file changes nothing."
        actions={
          !importing && (
            <>
              <Button variant="outline" onClick={() => setFlow("connector")}>
                <FileUp aria-hidden />
                Import a file
              </Button>
              <Button variant="outline" onClick={() => setFlow("mapping")}>
                <Table2 aria-hidden />
                Map a file
              </Button>
            </>
          )
        }
      />

      {flow === "connector" && loaded && (
        <FileImportPanel
          connectors={connectors.data}
          platforms={platforms.data}
          onDone={() => setFlow(null)}
        />
      )}
      {flow === "mapping" && loaded && (
        <MappingPanel platforms={platforms.data} onDone={() => setFlow(null)} />
      )}

      {failed ? (
        <ErrorState
          title="The imports could not be loaded"
          detail="The API did not answer with the import batches, the accounts or the connectors."
          onRetry={() => {
            for (const query of [batches, platforms, connectors]) {
              if (query.error) void query.refetch();
            }
          }}
        />
      ) : loaded && batches.data.length === 0 && !importing ? (
        <EmptyState
          icon={Download}
          title="No imports yet"
          description="Nothing has been imported. Choose a wallet's exported file — or map an unsupported venue's columns yourself — see exactly what it would create, and commit it as one batch — inspectable, and reversible as a unit."
          action={
            <Button variant="outline" onClick={() => setFlow("connector")}>
              <FileUp aria-hidden />
              Import the first file
            </Button>
          }
        />
      ) : loaded && batches.data.length > 0 ? (
        <BatchTable batches={batches.data} platforms={platforms.data} />
      ) : null}
    </div>
  );
}

function FileImportPanel({
  connectors,
  platforms,
  onDone,
}: {
  connectors: CsvConnector[];
  platforms: Platform[];
  onDone: () => void;
}) {
  const fieldId = useId();
  const [connectorKey, setConnectorKey] = useState("");
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<{ name: string; content: string } | null>(null);
  const queryClient = useQueryClient();

  const preview = useMutation({ mutationFn: previewCsvImport });
  const commit = useMutation({
    mutationFn: commitCsvImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });

  const chosen = connectors.find((connector) => connector.connector === connectorKey);
  const ready = chosen !== undefined && accountId !== "" && file !== null;

  /** Any changed input outdates what was previewed or committed. */
  function outdate(): void {
    preview.reset();
    commit.reset();
  }

  async function choose(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    outdate();
    const chosen = event.target.files?.[0];
    setFile(chosen ? { name: chosen.name, content: await chosen.text() } : null);
  }

  return (
    <section
      aria-label="Import a file"
      className="rise space-y-5 border-y border-border py-6"
      style={{ animationDelay: "80ms" }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-connector`} className="microlabel text-muted-foreground">
            Connector
          </label>
          <NativeSelect
            id={`${fieldId}-connector`}
            className="w-full"
            value={connectorKey}
            onChange={(event) => {
              outdate();
              setConnectorKey(event.target.value);
            }}
          >
            <option value="">Choose…</option>
            {connectors.map((connector) => (
              <option key={connector.connector} value={connector.connector}>
                {connector.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-account`} className="microlabel text-muted-foreground">
            Into Account
          </label>
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
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${fieldId}-file`} className="microlabel text-muted-foreground">
            Exported file
          </label>
          <FileInput id={`${fieldId}-file`} onChange={(event) => void choose(event)} />
        </div>
      </div>

      {chosen && (
        <p className="text-sm text-muted-foreground">
          {chosen.expects} <span className="text-foreground">{timezoneWords(chosen)}</span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          variant="outline"
          disabled={!ready || preview.isPending || preview.isSuccess}
          onClick={() => {
            if (!ready || !file) return;
            preview.mutate({
              connector: connectorKey,
              account_id: Number(accountId),
              content: file.content,
            });
          }}
        >
          {preview.isPending ? "Previewing…" : "Preview"}
        </Button>
        {preview.isSuccess && !commit.isSuccess && (
          <Button
            disabled={commit.isPending}
            onClick={() => {
              if (!ready || !file) return;
              commit.mutate({
                connector: connectorKey,
                account_id: Number(accountId),
                content: file.content,
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

/** The one way a file is chosen, shared with the mapping flow. */
export function FileInput({
  id,
  onChange,
}: {
  id: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <input
      id={id}
      type="file"
      accept=".csv,text/csv,text/plain"
      onChange={onChange}
      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1.5 font-mono text-xs file:mr-3 file:border-0 file:bg-transparent file:p-0 file:font-mono file:text-xs file:font-medium"
    />
  );
}

/**
 * What the commit would do, before anything is written: every row to create,
 * every duplicate, every skip with its reason, every Instrument that would
 * have to exist first — the promise the commit then keeps.
 */
export function PreviewReport({ preview }: { preview: ImportPreview }) {
  const shown = preview.to_create.slice(0, 8);
  return (
    <div className="space-y-4" aria-label="Import preview">
      {preview.warnings.map((warning) => (
        <p key={warning} className="text-sm text-caution">
          {warning}
        </p>
      ))}

      <p className="text-sm">
        <span className="font-medium">{count(preview.to_create.length, "row")}</span> to create
        {preview.duplicates > 0 && (
          <span className="text-muted-foreground">
            {" "}
            · {formatNumber(preview.duplicates)} already known, unchanged by a re-import
          </span>
        )}
      </p>

      {shown.length > 0 && (
        <ul className="space-y-1 font-mono text-xs text-muted-foreground">
          {shown.map((row) => (
            <li key={row.external_id} className="flex gap-3">
              <span className="tabular-nums">{formatTimestamp(Date.parse(row.occurred_at))}</span>
              <span>{row.type.replace("_", " ")}</span>
              <span className="truncate">{row.external_id}</span>
            </li>
          ))}
          {preview.to_create.length > shown.length && (
            <li>…and {formatNumber(preview.to_create.length - shown.length)} more</li>
          )}
        </ul>
      )}

      {preview.new_instruments.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Instruments to create first:{" "}
          {preview.new_instruments.map((spec) => spec.symbol).join(", ")}
        </p>
      )}

      {preview.skipped.length > 0 && (
        <div className="space-y-1">
          <p className="microlabel text-muted-foreground">
            Skipped — each with its reason, none in silence
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {preview.skipped.map((skip) => (
              <li key={skip.external_id}>
                <span className="font-mono">{skip.external_id}</span> — {skip.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function BatchTable({ batches, platforms }: { batches: ImportBatch[]; platforms: Platform[] }) {
  const accountName = new Map(
    platforms.flatMap((platform) =>
      platform.accounts.map((account) => [account.id, `${platform.name} · ${account.name}`]),
    ),
  );

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
          {["When", "Import", "Account", "Rows", ""].map((column, index) => (
            <th
              key={column || "actions"}
              scope="col"
              className={`microlabel py-2.5 text-muted-foreground ${index === 4 ? "" : "pr-4"}`}
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {batches.map((batch, index) => (
          <tr
            key={batch.id}
            className="rise border-b border-border align-top"
            style={{ animationDelay: `${120 + index * 40}ms` }}
            aria-label={`Import ${batch.label} from ${batch.source}`}
          >
            <td className="py-3 pr-4 font-mono text-xs tabular-nums text-muted-foreground">
              {formatTimestamp(Date.parse(batch.created_at))}
            </td>
            <td className="py-3 pr-4">
              <span className="font-medium">{batch.label}</span>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">{batch.source}</p>
            </td>
            <td className="py-3 pr-4 text-xs text-muted-foreground">
              {accountName.get(batch.account_id) ?? `Account #${batch.account_id}`}
            </td>
            <td className="py-3 pr-4 font-mono text-xs tabular-nums">{rowsWords(batch)}</td>
            <td className="py-3 text-right">
              <ReverseButton batch={batch} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReverseButton({ batch }: { batch: ImportBatch }) {
  // Reversal removes the batch's rows from the ledger in one act, so it asks
  // once, inline: the first press arms the button, the second one acts.
  const [armed, setArmed] = useState(false);
  const queryClient = useQueryClient();
  const reverse = useMutation({
    mutationFn: () => reverseImportBatch(batch.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-batches"] });
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        className={armed ? "text-alarm" : "text-muted-foreground"}
        disabled={reverse.isPending}
        onBlur={() => setArmed(false)}
        onClick={() => {
          if (armed) {
            reverse.mutate();
          } else {
            setArmed(true);
          }
        }}
        title={
          batch.overridden > 0
            ? "Rows edited by hand are yours now: they stand, and a re-import will not resurrect their originals."
            : "Removes every row this import created, in one act."
        }
      >
        <Undo2 aria-hidden />
        {reverse.isPending ? "Reversing…" : armed ? "Confirm reversal" : "Reverse"}
      </Button>
      {reverse.isError && (
        <p role="alert" className="text-xs text-alarm">
          {reverse.error.message}
        </p>
      )}
    </div>
  );
}
