import { useQuery } from "@tanstack/react-query";
import { CandlestickChart, ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { Fragment, useId, useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  fetchFutures,
  fetchLivePositions,
  fetchPositionEvents,
  type Futures,
  type KindLive,
  type LivePosition,
  type Position,
} from "@/api/futures";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { TONE, type Tone } from "@/components/patterns/lamp";
import { Button } from "@/components/ui/button";
import {
  formatMoney,
  formatQuantity,
  formatSignedQuantity,
  formatTimestamp,
} from "@/lib/format";

/** The ledger's closed positions, the latest close on top. */
export function closedNewestFirst(positions: Position[]): Position[] {
  return positions
    .filter((position) => position.closed_at !== null)
    .sort((a, b) => Date.parse(b.closed_at ?? "") - Date.parse(a.closed_at ?? ""));
}

/**
 * The positions the ledger holds open that no venue statement covers — a
 * venue that did not answer, or a position entered by hand. They stay
 * visible: what the ledger says is open is never hidden by a venue's silence.
 */
export function ledgerOnly(positions: Position[], live: KindLive[]): Position[] {
  const covered = new Set(
    live.flatMap((kind) => kind.positions.map((position) => position.ledger_position_id)),
  );
  return positions.filter((position) => position.closed_at === null && !covered.has(position.id));
}

/** A share (0.02 for 2 %) with its direction in the figure, to the venue's two decimals. */
export function ratioWords(ratio: string, locale?: string): string {
  const share = Number(ratio);
  const words = new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(share));
  return share === 0 ? words : `${share < 0 ? "−" : "+"}${words}`;
}

/** The venue's maintenance margin ratio, as the percentage its own screen shows. */
export function marginRatioWords(ratio: string, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(ratio));
}

/** How a signed figure reads: a gain, a loss, or nothing either way. */
export function toneOf(value: string | null): Tone {
  if (value === null || !/[1-9]/.test(value)) return "idle";
  return value.startsWith("-") ? "alarm" : "signal";
}

/** Fixed-point amounts summed exactly — scaled to integers, never through a float. */
export function signedSum(values: string[]): string {
  const scale = Math.max(0, ...values.map((value) => (value.split(".")[1] ?? "").length));
  const total = values.reduce((sum, value) => {
    const negative = value.startsWith("-");
    const [integer = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
    const scaled = BigInt(integer + fraction.padEnd(scale, "0"));
    return negative ? sum - scaled : sum + scaled;
  }, 0n);
  const digits = (total < 0n ? -total : total).toString().padStart(scale + 1, "0");
  const integer = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale).replace(/0+$/, "");
  return `${total < 0n ? "-" : ""}${integer}${fraction ? `.${fraction}` : ""}`;
}

/** A fixed-point figure that may be negative, digits verbatim, no plus on a gain. */
function plain(value: string): string {
  return value.startsWith("-") ? `−${formatQuantity(value.slice(1))}` : formatQuantity(value);
}

const HEAD = "microlabel py-2 pl-4 text-right font-normal text-muted-foreground whitespace-nowrap";
// The symbol stays in view while the figures scroll sideways under it.
const HEAD_FIRST =
  "microlabel sticky left-0 bg-background py-2 pr-4 text-left font-normal text-muted-foreground";
const FIGURE = "py-3 pl-4 text-right font-mono text-xs tabular-nums whitespace-nowrap";
const UNSTATED = <span className="text-muted-foreground">—</span>;

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
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });

  const accountName = accountNames(platforms.data ?? []);
  const positions = futures.data?.positions ?? [];
  const closed = closedNewestFirst(positions);
  const nothingAnywhere =
    futures.data !== undefined &&
    positions.length === 0 &&
    live.data !== undefined &&
    live.data.length === 0;

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
                  ["history", `Position history (${closed.length})`],
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
                  live={live.data}
                  error={live.error}
                  fetching={live.isFetching}
                  askedAt={live.dataUpdatedAt}
                  onRefresh={() => void live.refetch()}
                  ledgerOpen={ledgerOnly(positions, live.data ?? [])}
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

type AccountName = (accountId: number | null) => string | null;

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
 * What derivation could not settle: funding no position could claim, and fill
 * streams it refused to guess at. Both bear on the tax result, so they stand
 * above everything else — and are absent when there is nothing to say.
 */
function Unresolved({ futures, accountName }: { futures: Futures; accountName: AccountName }) {
  const { unattributable_funding: funding, derivation_issues: issues } = futures;
  if (funding.length === 0 && issues.length === 0) return null;
  return (
    <section
      aria-label="Unresolved"
      className="rounded-xl border border-caution/40 bg-caution/5 px-5 py-4"
    >
      <p className="text-sm font-medium">Not settled by the ledger</p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {issues.map((issue) => (
          <li key={`issue-${issue.id}`}>
            <span className="font-mono text-xs">{issue.symbol}</span>
            <span className="text-muted-foreground">
              {" "}
              {accountName(issue.account_id) && `at ${accountName(issue.account_id)} `}derived no
              position: {issue.reason}
            </span>
          </li>
        ))}
        {funding.length > 0 && (
          <li>
            <span className="font-mono text-xs tabular-nums">{funding.length}</span>
            <span className="text-muted-foreground">
              {" "}
              funding {funding.length === 1 ? "payment" : "payments"} on{" "}
              {[...new Set(funding.map((payment) => payment.symbol))].join(", ")} matched no
              position open at the time, and {funding.length === 1 ? "counts" : "count"} in no
              result.
            </span>
          </li>
        )}
      </ul>
    </section>
  );
}

function OpenPositions({
  live,
  error,
  fetching,
  askedAt,
  onRefresh,
  ledgerOpen,
  accountName,
}: {
  live: KindLive[] | undefined;
  error: Error | null;
  fetching: boolean;
  askedAt: number;
  onRefresh: () => void;
  ledgerOpen: Position[];
  accountName: AccountName;
}) {
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="max-w-xl text-sm text-muted-foreground">
          {live === undefined && fetching
            ? "Asking each venue for its open positions…"
            : live !== undefined
              ? `As the venues stated them at ${formatTimestamp(askedAt)}. Shown, never stored — the tax figures rest on fills alone.`
              : "The venues have not been asked yet."}
        </p>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={fetching}>
          <RefreshCw aria-hidden className={fetching ? "animate-spin" : undefined} />
          {fetching ? "Asking…" : "Refresh"}
        </Button>
      </div>

      {error && (
        <ErrorState
          title="The venues could not be asked"
          detail="The API did not answer with the live positions. Position history is unaffected."
          onRetry={onRefresh}
        />
      )}

      {live?.map((kind) => (
        <section key={`${kind.connection_id}-${kind.adapter_kind}`} aria-label={kind.connection_label}>
          <div className="flex flex-wrap items-baseline gap-x-3">
            <h2 className="text-base font-medium">{kind.connection_label}</h2>
            <span className="text-sm text-muted-foreground">
              {accountName(kind.account_id) ?? "not paired with an Account"}
            </span>
          </div>
          {kind.error ? (
            <p role="alert" className="mt-2 text-sm text-alarm">
              {kind.error}
            </p>
          ) : !kind.supported ? (
            <p className="mt-2 text-sm text-muted-foreground">
              This venue does not state its open positions. What the ledger derived from its
              fills is below and under Position history.
            </p>
          ) : kind.positions.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">No position is open here.</p>
          ) : (
            <LiveTable positions={kind.positions} />
          )}
        </section>
      ))}

      {ledgerOpen.length > 0 && (
        <section aria-label="Open in the ledger only">
          <h2 className="text-base font-medium">Open in the ledger only</h2>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            The ledger holds these open, and no venue statement above covers them — the venue
            did not answer, states none, or the position was entered by hand.
          </p>
          <LedgerTable positions={ledgerOpen} accountName={accountName} closed={false} />
        </section>
      )}
    </div>
  );
}

function LiveTable({ positions }: { positions: LivePosition[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-5xl text-sm">
        <thead>
          <tr className="border-y border-border">
            <th scope="col" className={HEAD_FIRST}>
              Symbol
            </th>
            {[
              "Size",
              "Mark price",
              "Entry price",
              "Est. liq. price",
              "Breakeven price",
              "Floating result",
              "MMR",
              "Margin",
            ].map((heading) => (
              <th key={heading} scope="col" className={HEAD}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {positions.map((position) => {
            const key = `${position.symbol}-${position.side}`;
            const tone = toneOf(position.floating_result);
            const matched = position.ledger_position_id;
            return (
              <Fragment key={key}>
                <tr className="align-top">
                  <th scope="row" className="sticky left-0 bg-background py-3 pr-4 text-left font-normal">
                    <div className="flex items-start gap-1.5">
                      {matched !== null ? (
                        <Expander
                          open={open === key}
                          label={position.symbol}
                          onToggle={() => setOpen(open === key ? null : key)}
                        />
                      ) : (
                        <span className="size-6 shrink-0" />
                      )}
                      <div>
                        <p className="font-mono text-xs whitespace-nowrap">{position.symbol}</p>
                        <p className="mt-1 text-xs whitespace-nowrap text-muted-foreground">
                          {position.side}
                          {position.leverage && `, ${plain(position.leverage)}×`}
                          {position.margin_mode && `, ${position.margin_mode}`}
                        </p>
                        {matched === null && (
                          <p className="mt-1 text-xs whitespace-nowrap text-caution">
                            Not in the ledger — opened before the synced history.
                          </p>
                        )}
                      </div>
                    </div>
                  </th>
                  <td className={FIGURE}>
                    {plain(position.quantity)} {position.quantity_unit}
                    {position.notional_usd && (
                      <p className="mt-1 text-muted-foreground">
                        {formatMoney(Number(position.notional_usd), "USD")}
                      </p>
                    )}
                  </td>
                  <td className={FIGURE}>{price(position.mark_price)}</td>
                  <td className={FIGURE}>{price(position.entry_price)}</td>
                  <td className={FIGURE}>{price(position.liquidation_price)}</td>
                  <td className={FIGURE}>{price(position.breakeven_price)}</td>
                  <td className={`${FIGURE} ${TONE[tone].text}`}>
                    {position.floating_result === null ? (
                      UNSTATED
                    ) : (
                      <>
                        {formatSignedQuantity(position.floating_result)}{" "}
                        {position.settlement_symbol}
                        {position.floating_result_ratio && (
                          <p className="mt-1">{ratioWords(position.floating_result_ratio)}</p>
                        )}
                      </>
                    )}
                  </td>
                  <td className={FIGURE}>
                    {position.margin_ratio ? marginRatioWords(position.margin_ratio) : UNSTATED}
                  </td>
                  <td className={FIGURE}>
                    {position.margin === null ? (
                      UNSTATED
                    ) : (
                      <>
                        {plain(position.margin)} {position.settlement_symbol}
                      </>
                    )}
                  </td>
                </tr>
                {matched !== null && open === key && (
                  <tr>
                    <td colSpan={9} className="pb-5">
                      <Events positionId={matched} settlement={position.settlement_symbol} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function price(value: string | null): ReactNode {
  return value === null ? UNSTATED : plain(value);
}

function History({ positions, accountName }: { positions: Position[]; accountName: AccountName }) {
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
      <p className="max-w-xl text-sm text-muted-foreground">
        Closed positions as the ledger derived them from fills. The net is the result less fees
        plus funding, and is what a close puts into the Termingeschäfte figure of its year.
      </p>
      <LedgerTable positions={positions} accountName={accountName} closed />
    </div>
  );
}

/** The ledger's own positions: closed ones with their close and EUR value, open ones without. */
function LedgerTable({
  positions,
  accountName,
  closed,
}: {
  positions: Position[];
  accountName: AccountName;
  closed: boolean;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const headings = [
    "Opened",
    ...(closed ? ["Closed"] : []),
    "Result",
    "Fees",
    "Funding",
    "Net",
    ...(closed ? ["Net in EUR"] : []),
  ];
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-4xl text-sm">
        <thead>
          <tr className="border-y border-border">
            <th scope="col" className={HEAD_FIRST}>
              Symbol
            </th>
            {headings.map((heading) => (
              <th key={heading} scope="col" className={HEAD}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {positions.map((position) => (
            <Fragment key={position.id}>
              <tr className="align-top">
                <th scope="row" className="sticky left-0 bg-background py-3 pr-4 text-left font-normal">
                  <div className="flex items-start gap-1.5">
                    <Expander
                      open={open === position.id}
                      label={position.symbol}
                      onToggle={() => setOpen(open === position.id ? null : position.id)}
                    />
                    <div>
                      <p className="font-mono text-xs whitespace-nowrap">{position.symbol}</p>
                      <p className="mt-1 text-xs whitespace-nowrap text-muted-foreground">
                        {position.side}
                        {accountName(position.account_id) &&
                          `, ${accountName(position.account_id)}`}
                        {position.origin === "manual" && ", entered by hand"}
                      </p>
                    </div>
                  </div>
                </th>
                <td className={FIGURE}>{formatTimestamp(Date.parse(position.opened_at))}</td>
                {closed && (
                  <td className={FIGURE}>
                    {position.closed_at && formatTimestamp(Date.parse(position.closed_at))}
                  </td>
                )}
                <td className={FIGURE}>{formatSignedQuantity(position.realized)}</td>
                <td className={FIGURE}>{plain(position.fees)}</td>
                <td className={FIGURE}>{formatSignedQuantity(position.funding)}</td>
                <td className={`${FIGURE} ${TONE[toneOf(position.net)].text}`}>
                  {formatSignedQuantity(position.net)} {position.settlement_symbol}
                </td>
                {closed && (
                  <td className={FIGURE}>
                    {position.net_eur === null ? (
                      <span className="font-sans text-caution">awaiting a rate</span>
                    ) : (
                      formatMoney(Number(position.net_eur), "EUR")
                    )}
                  </td>
                )}
              </tr>
              {open === position.id && (
                <tr>
                  <td colSpan={headings.length + 1} className="pb-5">
                    <Events positionId={position.id} settlement={position.settlement_symbol} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Expander({
  open,
  label,
  onToggle,
}: {
  open: boolean;
  label: string;
  onToggle: () => void;
}) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={`${open ? "Hide" : "Show"} the fills and funding of ${label}`}
      onClick={onToggle}
      className="-mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <Icon aria-hidden className="size-4" />
    </button>
  );
}

/**
 * What one position rests on: every fill it was derived from, and beneath
 * them the funding attributed to it — its sum first, then each payment in a
 * list that scrolls, because a long-held position collects hundreds.
 */
function Events({ positionId, settlement }: { positionId: number; settlement: string }) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["futures-events", positionId],
    queryFn: () => fetchPositionEvents(positionId),
  });

  if (error) {
    return (
      <ErrorState
        title="The fills and funding could not be loaded"
        detail="The API did not answer with what this position was derived from."
        onRetry={() => void refetch()}
      />
    );
  }
  if (isPending) {
    return (
      <p role="status" className="microlabel text-muted-foreground">
        reading the fills and funding
      </p>
    );
  }

  const figure = "py-1.5 font-mono text-xs tabular-nums whitespace-nowrap";
  const cell = `${figure} pl-4 text-right`;
  const time = `${figure} text-left`;
  const head = "microlabel py-1.5 pl-4 text-right font-normal text-muted-foreground";
  return (
    <div className="sticky left-0 max-w-2xl space-y-5 pt-1">
      <div>
        <p className="text-sm font-medium">
          Fills <span className="font-mono text-xs text-muted-foreground">{data.fills.length}</span>
        </p>
        {data.fills.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">
            None stored — a position entered by hand rests on no fills.
          </p>
        ) : (
          <div className="mt-1 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="microlabel py-1.5 text-left font-normal text-muted-foreground">
                    Time
                  </th>
                  {["Side", "Price", "Size", "Fee", "Result"].map((heading) => (
                    <th key={heading} scope="col" className={head}>
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.fills.map((fill) => (
                  <tr key={fill.id}>
                    <td className={time}>
                      {formatTimestamp(Date.parse(fill.occurred_at))}
                    </td>
                    <td className={`${cell} font-sans`}>{fill.side}</td>
                    <td className={cell}>{plain(fill.price)}</td>
                    <td className={cell}>{plain(fill.size)}</td>
                    <td className={cell}>{plain(fill.fee)}</td>
                    <td className={cell}>
                      {fill.realized === null ? UNSTATED : formatSignedQuantity(fill.realized)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <p className="text-sm font-medium">
          Funding{" "}
          <span className="font-mono text-xs text-muted-foreground">{data.funding.length}</span>
        </p>
        {data.funding.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">No payment is attributed to it.</p>
        ) : (
          <>
            <p className="mt-1 font-mono text-xs tabular-nums">
              {formatSignedQuantity(signedSum(data.funding.map((payment) => payment.amount)))}{" "}
              {settlement}
              <span className="ml-2 font-sans text-muted-foreground">in total</span>
            </p>
            <div
              className="mt-2 max-h-56 overflow-y-auto border-y border-border"
              tabIndex={0}
              role="group"
              aria-label="Funding payments"
            >
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  {data.funding.map((payment) => (
                    <tr key={payment.id}>
                      <td className={time}>
                        {formatTimestamp(Date.parse(payment.occurred_at))}
                      </td>
                      <td className={cell}>{formatSignedQuantity(payment.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
