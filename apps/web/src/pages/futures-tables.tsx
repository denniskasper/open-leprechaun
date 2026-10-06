import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import { fetchPositionEvents, type FuturesPosition, type LivePosition } from "@/api/futures";
import { ErrorState } from "@/components/patterns/error-state";
import { TONE, type Tone } from "@/components/patterns/lamp";
import {
  formatAssetAmount,
  formatEur,
  formatMoneyExact,
  formatNumber,
  formatPercentExact,
  formatQuantity,
  formatSignedAssetAmount,
  formatSignedPercentExact,
  formatTimestamp,
} from "@/lib/format";

/** An Account by the name the Admin knows it under — null while unknown. */
export type AccountName = (accountId: number | null) => string | null;

/** How a signed figure reads: a gain, a loss, or nothing either way. */
export function toneOf(value: string | null): Tone {
  if (value === null || !/[1-9]/.test(value)) return "idle";
  return value.startsWith("-") ? "alarm" : "signal";
}

const HEAD = "microlabel py-2 pl-4 text-right font-normal text-muted-foreground whitespace-nowrap";
// The symbol stays in view while the figures scroll sideways under it.
const HEAD_FIRST =
  "microlabel sticky left-0 bg-background py-2 pr-4 text-left font-normal text-muted-foreground";
const FIGURE = "py-3 pl-4 text-right font-mono text-xs tabular-nums whitespace-nowrap";
const UNSTATED = <span className="text-muted-foreground">—</span>;

/** A price as the venue states it: a plain figure, because the venue names no currency for it. */
function price(value: string | null): ReactNode {
  return value === null ? UNSTATED : formatQuantity(value);
}

function TableFrame({
  minWidth,
  headings,
  children,
}: {
  minWidth: string;
  headings: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className={`w-full text-sm ${minWidth}`}>
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
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

/**
 * The first cell of every position row: the control that opens what the
 * position rests on — where the ledger has it — then the symbol and what
 * tells this position from another on the same symbol.
 */
function SymbolCell({
  symbol,
  detail,
  caution,
  open,
  onToggle,
}: {
  symbol: string;
  detail: string;
  caution?: string;
  open: boolean;
  /** Absent where the ledger holds nothing to open. */
  onToggle?: () => void;
}) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <th scope="row" className="sticky left-0 bg-background py-3 pr-4 text-left font-normal">
      <div className="flex items-start gap-1.5">
        {onToggle ? (
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} the fills and funding of ${symbol}`}
            onClick={onToggle}
            className="-mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Icon aria-hidden className="size-4" />
          </button>
        ) : (
          <span className="size-6 shrink-0" />
        )}
        <div className="min-w-48">
          <p className="font-mono text-xs whitespace-nowrap">{symbol}</p>
          <p className="mt-1 max-w-64 text-xs text-pretty text-muted-foreground">{detail}</p>
          {caution && <p className="mt-1 max-w-64 text-xs text-pretty text-caution">{caution}</p>}
        </div>
      </div>
    </th>
  );
}

function EventsRow({ columns, position }: { columns: number; position: FuturesPosition }) {
  return (
    <tr>
      <td colSpan={columns} className="pb-5">
        <Events position={position} />
      </td>
    </tr>
  );
}

/** Live Positions, as one venue states them: every figure its own, none recomputed. */
export function LiveTable({
  positions,
  ledger,
}: {
  positions: LivePosition[];
  /** The ledger's positions, to open the one a stated position matches. */
  ledger: FuturesPosition[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const headings = [
    "Size",
    "Mark price",
    "Entry price",
    "Est. liq. price",
    "Breakeven price",
    "Floating result",
    "MMR",
    "Margin",
  ];
  return (
    <TableFrame minWidth="min-w-5xl" headings={headings}>
      {positions.map((position) => {
        const key = `${position.symbol}-${position.side}`;
        const matched = ledger.find((entry) => entry.id === position.ledger_position_id);
        const unit = position.settlement_symbol;
        return (
          <Fragment key={key}>
            <tr className="align-top">
              <SymbolCell
                symbol={position.symbol}
                detail={
                  position.leverage
                    ? `${position.side}, ${formatQuantity(position.leverage)}×`
                    : position.side
                }
                caution={
                  matched ? undefined : "Not in the ledger — opened before the synced history."
                }
                open={open === key}
                onToggle={matched ? () => setOpen(open === key ? null : key) : undefined}
              />
              <td className={FIGURE}>
                {position.quantity_unit
                  ? formatAssetAmount(position.quantity, position.quantity_unit)
                  : formatQuantity(position.quantity)}
                {position.notional_usd && (
                  <p className="mt-1 text-muted-foreground">
                    {formatMoneyExact(position.notional_usd, "USD")}
                  </p>
                )}
              </td>
              <td className={FIGURE}>{price(position.mark_price)}</td>
              <td className={FIGURE}>{price(position.entry_price)}</td>
              <td className={FIGURE}>{price(position.liquidation_price)}</td>
              <td className={FIGURE}>{price(position.breakeven_price)}</td>
              <td className={`${FIGURE} ${TONE[toneOf(position.floating_result)].text}`}>
                {position.floating_result === null ? (
                  UNSTATED
                ) : (
                  <>
                    {formatSignedAssetAmount(position.floating_result, unit)}
                    {position.floating_result_ratio && (
                      <p className="mt-1">
                        {formatSignedPercentExact(position.floating_result_ratio)}
                      </p>
                    )}
                  </>
                )}
              </td>
              <td className={FIGURE}>
                {position.margin_ratio ? formatPercentExact(position.margin_ratio) : UNSTATED}
              </td>
              <td className={FIGURE}>
                {position.margin === null ? UNSTATED : formatAssetAmount(position.margin, unit)}
                {position.margin_mode && (
                  <p className="mt-1 font-sans text-muted-foreground">{position.margin_mode}</p>
                )}
              </td>
            </tr>
            {matched && open === key && (
              <EventsRow columns={headings.length + 1} position={matched} />
            )}
          </Fragment>
        );
      })}
    </TableFrame>
  );
}

/** The ledger's own positions: closed ones with their close and EUR value, open ones without. */
export function LedgerTable({
  positions,
  accountName,
  closed,
}: {
  positions: FuturesPosition[];
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
    <TableFrame minWidth="min-w-5xl" headings={headings}>
      {positions.map((position) => {
        const unit = position.settlement_symbol;
        const account = accountName(position.account_id);
        return (
          <Fragment key={position.id}>
            <tr className="align-top">
              <SymbolCell
                symbol={position.symbol}
                detail={[
                  position.side,
                  ...(account ? [account] : []),
                  ...(position.origin === "manual" ? ["entered by hand"] : []),
                ].join(", ")}
                open={open === position.id}
                onToggle={() => setOpen(open === position.id ? null : position.id)}
              />
              <td className={FIGURE}>{formatTimestamp(Date.parse(position.opened_at))}</td>
              {closed && (
                <td className={FIGURE}>
                  {position.closed_at && formatTimestamp(Date.parse(position.closed_at))}
                </td>
              )}
              <td className={FIGURE}>{formatSignedAssetAmount(position.realized, unit)}</td>
              <td className={FIGURE}>{formatAssetAmount(position.fees, unit)}</td>
              <td className={FIGURE}>{formatSignedAssetAmount(position.funding, unit)}</td>
              <td className={`${FIGURE} ${TONE[toneOf(position.net)].text}`}>
                {formatSignedAssetAmount(position.net, unit)}
              </td>
              {closed && (
                <td className={FIGURE}>
                  {position.net_eur === null ? (
                    <span className="font-sans text-caution">awaiting a rate</span>
                  ) : (
                    formatEur(position.net_eur)
                  )}
                </td>
              )}
            </tr>
            {open === position.id && (
              <EventsRow columns={headings.length + 1} position={position} />
            )}
          </Fragment>
        );
      })}
    </TableFrame>
  );
}

/**
 * What one position rests on: every fill it was derived from, and beneath
 * them the funding attributed to it — its total first, then each payment in
 * a list that scrolls, because a long-held position collects hundreds.
 */
function Events({ position }: { position: FuturesPosition }) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["futures-events", position.id],
    queryFn: () => fetchPositionEvents(position.id),
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

  const unit = position.settlement_symbol;
  const figure = "py-1.5 font-mono text-xs tabular-nums whitespace-nowrap";
  const cell = `${figure} pl-4 text-right`;
  const time = `${figure} text-left`;
  const head = "microlabel py-1.5 pl-4 text-right font-normal text-muted-foreground";
  return (
    // Pinned, so it stays in view while the table scrolls sideways under it.
    <div className="sticky left-0 max-w-2xl space-y-5 pt-1">
      <div>
        <p className="text-sm font-medium">
          Fills{" "}
          <span className="font-mono text-xs text-muted-foreground">
            {formatNumber(data.fills.length)}
          </span>
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
                  <th
                    scope="col"
                    className="microlabel py-1.5 text-left font-normal text-muted-foreground"
                  >
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
                    <td className={time}>{formatTimestamp(Date.parse(fill.occurred_at))}</td>
                    <td className={`${cell} font-sans`}>{fill.side}</td>
                    <td className={cell}>{formatQuantity(fill.price)}</td>
                    <td className={cell}>{formatQuantity(fill.size)}</td>
                    <td className={cell}>{formatAssetAmount(fill.fee, unit)}</td>
                    <td className={cell}>
                      {fill.realized === null
                        ? UNSTATED
                        : formatSignedAssetAmount(fill.realized, unit)}
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
          <span className="font-mono text-xs text-muted-foreground">
            {formatNumber(data.funding.length)}
          </span>
        </p>
        {data.funding.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">No payment is attributed to it.</p>
        ) : (
          <>
            <p className="mt-1 font-mono text-xs tabular-nums">
              {formatSignedAssetAmount(position.funding, unit)}
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
                      <td className={time}>{formatTimestamp(Date.parse(payment.occurred_at))}</td>
                      <td className={cell}>{formatSignedAssetAmount(payment.amount, unit)}</td>
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
