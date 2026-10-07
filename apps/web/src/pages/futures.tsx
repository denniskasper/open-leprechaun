import { useQuery } from "@tanstack/react-query";
import { CandlestickChart, RefreshCw } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router";
import {
  fetchFutures,
  fetchLivePositions,
  type Futures,
  type FuturesPosition,
  type UnattributableFunding,
  type VenueStatement,
} from "@/api/futures";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Amount } from "@/components/patterns/figure";
import { Button } from "@/components/ui/button";
import { formatNumber, formatTimestamp } from "@/lib/format";
import { LedgerTable, LiveTable, type AccountName } from "./futures-tables";
import { sumFixed } from "./holdings";

/** The ledger's closed positions, the latest close on top. */
export function closedNewestFirst(positions: FuturesPosition[]): FuturesPosition[] {
  return positions
    .filter((position) => position.closed_at !== null)
    .sort((a, b) => Date.parse(b.closed_at ?? "") - Date.parse(a.closed_at ?? ""));
}

/**
 * The positions the ledger holds open that no venue statement covers — a
 * venue that did not answer, or a position entered by hand. They stay
 * visible: what the ledger says is open is never hidden by a venue's silence.
 */
export function ledgerOnly(
  positions: FuturesPosition[],
  statements: VenueStatement[],
): FuturesPosition[] {
  const covered = new Set(
    statements.flatMap((statement) =>
      statement.positions.map((position) => position.ledger_position_id),
    ),
  );
  return positions.filter((position) => position.closed_at === null && !covered.has(position.id));
}

export interface UnattributableFundingGroup {
  account_id: number;
  symbol: string;
  settlement_symbol: string;
  count: number;
  /** The payments' exact sum — fixed-point, never through a float. */
  total: string;
  first_at: string;
  last_at: string;
}

/**
 * Unattributable funding, gathered by where and on what it was paid: there can be dozens on one symbol, and a line each would bury the
 * rest of what is unresolved.
 */
export function groupUnattributableFunding(
  payments: UnattributableFunding[],
): UnattributableFundingGroup[] {
  const gathered = new Map<string, UnattributableFunding[]>();
  for (const payment of payments) {
    const key = `${payment.account_id}|${payment.symbol}|${payment.settlement_symbol}`;
    gathered.set(key, [...(gathered.get(key) ?? []), payment]);
  }
  return [...gathered.values()].map((group) => {
    const instants = group.map((payment) => payment.occurred_at).sort();
    const first = group[0]!;
    return {
      account_id: first.account_id,
      symbol: first.symbol,
      settlement_symbol: first.settlement_symbol,
      count: group.length,
      total: sumFixed(group.map((payment) => payment.amount)),
      first_at: instants[0]!,
      last_at: instants[instants.length - 1]!,
    };
  });
}

function accountNames(platforms: Platform[]): AccountName {
  const names = new Map<number, string>();
  for (const platform of platforms) {
    for (const account of platform.accounts) {
      names.set(account.id, `${platform.name}, ${account.name}`);
    }
  }
  return (accountId) => (accountId === null ? null : (names.get(accountId) ?? null));
}

/**
 * Whether the whole screen has nothing to say: no position, no venue to ask,
 * and nothing left unresolved. What is unresolved is never hidden behind an
 * empty state — and while either answer is still out, nothing is concluded.
 */
export function nothingToShow(
  futures: Futures | undefined,
  statements: VenueStatement[] | undefined,
): boolean {
  return (
    futures !== undefined &&
    statements !== undefined &&
    futures.positions.length === 0 &&
    futures.unattributable_funding.length === 0 &&
    futures.derivation_issues.length === 0 &&
    statements.length === 0
  );
}

type Tab = "open" | "history";

export function FuturesPage() {
  const id = useId();
  const [tab, setTab] = useState<Tab>("open");
  const futures = useQuery({ queryKey: ["futures"], queryFn: fetchFutures });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });
  // A live call to the venues: asked when the screen opens and on Refresh,
  // never behind the Admin's back.
  const live = useQuery({
    queryKey: ["futures-live"],
    queryFn: fetchLivePositions,
    staleTime: Infinity,
    // Never kept once the screen is left: coming back asks the venues again
    // rather than repeating an old statement as if it were this moment's.
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });

  const accountName = accountNames(platforms.data ?? []);
  const positions = futures.data?.positions ?? [];
  const closed = closedNewestFirst(positions);
  const nothingAnywhere = nothingToShow(futures.data, live.data);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Ledger"
        title="Futures"
        description="Open positions as each venue states them right now, and the closed positions the ledger derived from fills. Nothing here trades: a Connection's key can only read."
      />

      {futures.error ? (
        <ErrorState
          title="The futures positions could not be loaded"
          detail="The API did not answer with the ledger's positions."
          onRetry={() => void futures.refetch()}
        />
      ) : nothingAnywhere ? (
        <EmptyState
          icon={CandlestickChart}
          title="No futures yet"
          description="Positions appear once a Connection with a futures kind is paired with an Account and synced."
          action={
            <Button variant="outline" asChild>
              <Link to="/settings/connections">Open Connections</Link>
            </Button>
          }
        />
      ) : (
        <>
          {futures.data && <Unresolved futures={futures.data} accountName={accountName} />}

          <div className="space-y-5">
            <div role="tablist" aria-label="Positions" className="flex gap-1">
              {(
                [
                  ["open", "Open positions"],
                  ["history", `Position history (${formatNumber(closed.length)})`],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  role="tab"
                  id={`${id}-tab-${value}`}
                  aria-selected={tab === value}
                  aria-controls={`${id}-panel-${value}`}
                  size="sm"
                  variant={tab === value ? "secondary" : "ghost"}
                  onClick={() => setTab(value)}
                >
                  {label}
                </Button>
              ))}
            </div>

            {tab === "open" ? (
              <div role="tabpanel" id={`${id}-panel-open`} aria-labelledby={`${id}-tab-open`}>
                <OpenPositions
                  statements={live.data}
                  error={live.error}
                  asking={live.isFetching}
                  onRefresh={() => void live.refetch()}
                  positions={positions}
                  accountName={accountName}
                />
              </div>
            ) : (
              <div
                role="tabpanel"
                id={`${id}-panel-history`}
                aria-labelledby={`${id}-tab-history`}
              >
                <History positions={closed} accountName={accountName} />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * What derivation could not settle: fill streams it refused to guess at, and
 * funding no position could claim. Both bear on the tax result, so they
 * stand above everything else — and are absent when there is nothing to say.
 */
function Unresolved({ futures, accountName }: { futures: Futures; accountName: AccountName }) {
  const issues = futures.derivation_issues;
  const funding = groupUnattributableFunding(futures.unattributable_funding);
  if (issues.length === 0 && funding.length === 0) return null;
  return (
    <section
      aria-label="Unresolved"
      className="measure-list rounded-xl border border-caution/40 bg-caution/5 px-5 py-4"
    >
      <p className="text-sm font-medium">Not settled by the ledger</p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {issues.map((issue) => (
          <li key={`issue-${issue.id}`}>
            <span className="font-mono text-xs">{issue.symbol}</span>
            <span className="text-muted-foreground">
              {accountName(issue.account_id) && ` at ${accountName(issue.account_id)}`} derived no
              position: {issue.reason}
            </span>
          </li>
        ))}
        {funding.map((group) => (
          <li key={`funding-${group.account_id}-${group.symbol}-${group.settlement_symbol}`}>
            <span className="font-mono text-xs">{group.symbol}</span>
            <span className="text-muted-foreground">
              {accountName(group.account_id) && ` at ${accountName(group.account_id)}`}:{" "}
              {formatNumber(group.count)} funding {group.count === 1 ? "payment" : "payments"}
              {", "}
            </span>
            <span className="font-mono text-xs tabular-nums">
              <Amount value={group.total} symbol={group.settlement_symbol} signed />
            </span>
            <span className="text-muted-foreground">
              {group.count === 1
                ? ` on ${formatTimestamp(Date.parse(group.first_at))}`
                : ` between ${formatTimestamp(Date.parse(group.first_at))} and ${formatTimestamp(Date.parse(group.last_at))}`}
            </span>
          </li>
        ))}
      </ul>
      {funding.length > 0 && (
        <p className="mt-2 measure-prose text-sm text-muted-foreground">
          No single position could claim these — none was open for the symbol when they were
          paid, or more than one was — so they count in no result.
        </p>
      )}
    </section>
  );
}

function OpenPositions({
  statements,
  error,
  asking,
  onRefresh,
  positions,
  accountName,
}: {
  statements: VenueStatement[] | undefined;
  error: Error | null;
  asking: boolean;
  onRefresh: () => void;
  positions: FuturesPosition[];
  accountName: AccountName;
}) {
  // Only once the venues have answered, or could not be asked at all: while
  // the first answer is still out, nothing is yet known to be uncovered.
  const ledgerOpen =
    statements !== undefined || error ? ledgerOnly(positions, statements ?? []) : [];
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="measure-prose text-sm text-muted-foreground">
          {statements === undefined && asking
            ? "Asking each venue for its open positions…"
            : "Each venue is asked when this screen opens and on Refresh. Shown, never stored — the tax figures rest on fills alone."}
        </p>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={asking}>
          <RefreshCw aria-hidden className={asking ? "animate-spin" : undefined} />
          {asking ? "Asking…" : "Refresh"}
        </Button>
      </div>

      {error && (
        <ErrorState
          title="The venues could not be asked"
          detail="The API did not answer with the live positions. Position history is unaffected."
          onRetry={onRefresh}
        />
      )}

      {statements?.map((statement) => (
        <section
          key={`${statement.connection_id}-${statement.adapter_kind}`}
          aria-label={statement.connection_label}
          className="space-y-3"
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-base font-medium">{statement.connection_label}</h2>
            <span className="text-sm text-muted-foreground">
              {accountName(statement.account_id) ?? "not paired with an Account"}
            </span>
            {statement.stated_at && (
              <span className="ml-auto text-sm text-muted-foreground">
                stated at{" "}
                <span className="font-mono text-xs tabular-nums">
                  {formatTimestamp(Date.parse(statement.stated_at))}
                </span>
              </span>
            )}
          </div>
          {statement.error ? (
            <ErrorState
              title="This venue did not state its positions"
              detail={statement.error}
              onRetry={onRefresh}
            />
          ) : !statement.supported ? (
            <p className="measure-prose text-sm text-muted-foreground">
              This venue does not state its open positions. What the ledger derived from its
              fills is below and under Position history.
            </p>
          ) : statement.positions.length === 0 ? (
            <EmptyState
              title="No position is open here"
              description="The venue states none right now. Closed ones are under Position history."
            />
          ) : (
            <LiveTable positions={statement.positions} ledger={positions} />
          )}
        </section>
      ))}

      {ledgerOpen.length > 0 && (
        <section aria-label="Open in the ledger only" className="space-y-3">
          <div>
            <h2 className="text-base font-medium">Open in the ledger only</h2>
            <p className="mt-1 measure-prose text-sm text-muted-foreground">
              The ledger holds these open, and no venue statement above covers them — the venue
              did not answer, states none, or the position was entered by hand.
            </p>
          </div>
          <LedgerTable positions={ledgerOpen} accountName={accountName} closed={false} />
        </section>
      )}
    </div>
  );
}

function History({
  positions,
  accountName,
}: {
  positions: FuturesPosition[];
  accountName: AccountName;
}) {
  if (positions.length === 0) {
    return (
      <EmptyState
        icon={CandlestickChart}
        title="No position has closed yet"
        description="A position moves here once its last fill closes it. Until then it stands under Open positions."
      />
    );
  }
  return (
    <div className="space-y-3">
      <p className="measure-prose text-sm text-muted-foreground">
        Closed positions as the ledger derived them from fills. The net is the result less fees
        plus funding, and is what a close puts into the Termingeschäfte figure of its year.
      </p>
      <LedgerTable positions={positions} accountName={accountName} closed />
    </div>
  );
}
