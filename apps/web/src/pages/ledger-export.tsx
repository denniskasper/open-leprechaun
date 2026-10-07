import { useQuery } from "@tanstack/react-query";
import { FileDown, Scale } from "lucide-react";
import { Link } from "react-router";
import {
  type ExportFormat,
  fetchLedgerExport,
  type LedgerExport,
  type LeftOut,
  ledgerExportFileUrl,
} from "@/api/ledger-export";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { formatNumber, formatTimestamp } from "@/lib/format";

/** The tool each format is written for, as its own name is spelled. */
const TOOL: Record<ExportFormat, string> = { cointracking: "CoinTracking" };

/**
 * What the second engine must be set to before the file means the same
 * there as here. Stated before the download, not discovered after it.
 */
const SETTINGS: { term: string; value: string; why: string }[] = [
  {
    term: "Account currency",
    value: "EUR",
    why: "An opening balance states its estimated basis in the numéraire.",
  },
  {
    term: "Time zone",
    value: "UTC",
    why: "Every instant in the file is UTC; read as local time, a trade near midnight on 31 December changes its Tax Year.",
  },
];

export interface LeftOutGroup {
  reason: string;
  entries: LeftOut[];
}

/**
 * The left-out Transactions under the sentence they share, in the order each
 * reason first appears — a hundred trades of one security read as one fact.
 */
export function leftOutByReason(leftOut: LeftOut[]): LeftOutGroup[] {
  const groups = new Map<string, LeftOut[]>();
  for (const entry of leftOut) {
    groups.set(entry.reason, [...(groups.get(entry.reason) ?? []), entry]);
  }
  return [...groups].map(([reason, entries]) => ({ reason, entries }));
}

export function LedgerExportPage() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["ledger-export"],
    queryFn: fetchLedgerExport,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Export for verification"
        description="The ledger written out for an independent tax tool, so a second engine computes the same year from identical transactions — and where the two disagree, they disagree about rules, not about data."
      />

      {error ? (
        <ErrorState
          title="The export could not be prepared"
          detail="The API did not answer with what the file would carry."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <p role="status" className="microlabel text-muted-foreground">
          reading the ledger
        </p>
      ) : data.row_count === 0 && data.left_out.length === 0 ? (
        <EmptyState
          icon={Scale}
          title="The ledger holds nothing to export yet"
          description="The file carries one row per movement — record Transactions or run an import first."
          action={
            <Link to="/imports" className="text-sm underline underline-offset-2">
              Go to Imports
            </Link>
          }
        />
      ) : (
        <>
          <Manifest data={data} />
          <Settings tool={TOOL[data.format]} />
          <LeftOutSection tool={TOOL[data.format]} groups={leftOutByReason(data.left_out)} />
        </>
      )}
    </div>
  );
}

/** What the file is, as figures, with the one action the screen exists for. */
function Manifest({ data }: { data: LedgerExport }) {
  const tool = TOOL[data.format];
  return (
    <section aria-label="The export file" className="rise measure-list space-y-6">
      <dl className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3">
        <div>
          <dt className="microlabel text-muted-foreground">Rows in the file</dt>
          <dd className="mt-1.5 font-mono text-2xl tabular-nums">{formatNumber(data.row_count)}</dd>
        </div>
        <div>
          <dt className="microlabel text-muted-foreground">Transactions left out</dt>
          <dd
            className={`mt-1.5 font-mono text-2xl tabular-nums ${
              data.left_out.length > 0 ? "text-caution" : "text-muted-foreground"
            }`}
          >
            {formatNumber(data.left_out.length)}
          </dd>
        </div>
        <div>
          <dt className="microlabel text-muted-foreground">Written for</dt>
          <dd className="mt-1.5 text-2xl font-medium">{tool}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-y border-border py-4">
        <Button asChild>
          <a href={ledgerExportFileUrl(data.format)} download={data.filename}>
            <FileDown aria-hidden />
            Download the {tool} file
          </a>
        </Button>
        <p className="font-mono text-xs text-muted-foreground">{data.filename}</p>
        <p className="text-sm text-muted-foreground sm:ml-auto">
          Outward only — nothing is ever read back from {tool}.
        </p>
      </div>

      <p className="measure-prose text-sm text-pretty text-muted-foreground">
        The same ledger always produces the same file. It carries amounts, symbols, the Account
        each movement happened at and its instant — no notes, no addresses or references, no prices
        of this ledger's own. A fee is part of the amount sold, or already off the amount bought,
        and stated beside it.
      </p>
      <p className="measure-prose text-sm text-pretty text-muted-foreground">
        The file holds Transactions only: futures fills and funding, corporate actions and tax
        withheld at source are not in it, and income is stated as the net that arrived.
      </p>
    </section>
  );
}

function Settings({ tool }: { tool: string }) {
  return (
    <section
      aria-labelledby="export-settings"
      className="rise measure-list space-y-3"
      style={{ animationDelay: "60ms" }}
    >
      <h2 id="export-settings" className="microlabel text-muted-foreground">
        Set in {tool} before importing
      </h2>
      <dl className="border-t border-border">
        {SETTINGS.map((setting) => (
          <div
            key={setting.term}
            className="grid gap-x-6 gap-y-1 border-b border-border py-3 text-sm sm:grid-cols-[11rem_6rem_1fr]"
          >
            <dt>{setting.term}</dt>
            <dd className="font-mono tabular-nums">{setting.value}</dd>
            <dd className="text-pretty text-muted-foreground">{setting.why}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * Every Transaction the file does not carry, under the reason it shares.
 * A second engine's figure differs by exactly these, so they are stated
 * rather than discovered.
 */
function LeftOutSection({ tool, groups }: { tool: string; groups: LeftOutGroup[] }) {
  return (
    <section
      aria-labelledby="export-left-out"
      className="rise measure-list space-y-3"
      style={{ animationDelay: "120ms" }}
    >
      <h2 id="export-left-out" className="microlabel text-muted-foreground">
        Left out of the file
      </h2>
      {groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing — every Transaction in the ledger is in the file.
        </p>
      ) : (
        <>
          <p className="measure-prose text-sm text-pretty text-muted-foreground">
            {tool} will compute its year without these. A difference between its figures and this
            ledger's starts here.
          </p>
          <ul className="border-t border-border">
            {groups.map((group) => (
              <li key={group.reason} className="border-b border-border py-4">
                <div className="flex items-baseline justify-between gap-6">
                  <p className="text-sm text-pretty">{group.reason}</p>
                  <p className="shrink-0 font-mono text-sm tabular-nums text-caution">
                    {formatNumber(group.entries.length)}
                  </p>
                </div>
                <ul className="mt-2.5 space-y-1">
                  {group.entries.map((entry) => (
                    <li
                      key={entry.transaction_id}
                      className="flex flex-wrap gap-x-4 font-mono text-xs tabular-nums text-muted-foreground"
                    >
                      <span>#{entry.transaction_id}</span>
                      <span>{formatTimestamp(Date.parse(entry.occurred_at))}</span>
                      <span>{entry.type.replaceAll("_", " ")}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
