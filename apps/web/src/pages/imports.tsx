import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Undo2 } from "lucide-react";
import { useState } from "react";
import { fetchImportBatches, reverseImportBatch, type ImportBatch } from "@/api/imports";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { formatTimestamp } from "@/lib/format";

/** How a batch's row counts read in one line: what it holds, what the Admin has taken over. */
export function rowsWords(batch: ImportBatch): string {
  const rows = batch.rows === 1 ? "1 row" : `${batch.rows} rows`;
  return batch.overridden === 0 ? rows : `${rows} · ${batch.overridden} overridden`;
}

export function ImportsPage() {
  const batches = useQuery({ queryKey: ["import-batches"], queryFn: fetchImportBatches });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });

  const failed = batches.error ?? platforms.error;
  const loaded = batches.data && platforms.data;

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Imports"
        description="Every import, recorded as a batch and reversible as a unit. An import previews before it writes, commits as a separate act, and re-importing the same file changes nothing."
      />

      {failed ? (
        <ErrorState
          title="The imports could not be loaded"
          detail="The API did not answer with the import batches or the accounts."
          onRetry={() => {
            void batches.refetch();
            void platforms.refetch();
          }}
        />
      ) : loaded && batches.data.length === 0 ? (
        <EmptyState
          icon={Download}
          title="No imports yet"
          description="Nothing has been imported. When a connector or adapter brings history in, each import lands here as one batch — inspectable, and reversible as a unit."
        />
      ) : loaded ? (
        <BatchTable batches={batches.data} platforms={platforms.data} />
      ) : null}
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
