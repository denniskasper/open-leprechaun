import { useQuery } from "@tanstack/react-query";
import { ChartLine } from "lucide-react";
import { type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { type DisplayRate, fetchHoldings, type Position } from "@/api/holdings";
import {
  type Development,
  fetchDevelopment,
  fetchRealised,
  type Measurement,
  type Realised,
  type RealisedComponent,
} from "@/api/portfolio";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import type { DisplayCurrency } from "@/lib/display-currency";
import { formatDate, formatMoney, formatPercent } from "@/lib/format";
import {
  counts,
  DisplayCurrencySelect,
  DisplayRateNotice,
  displayMoney,
  FAMILY_LABEL,
  sumFixed,
  totalsOf,
  useDisplayCurrency,
} from "@/pages/holdings";

/** `a − b` over fixed-point strings, never through a float. */
export function subtractFixed(a: string, b: string): string {
  return sumFixed([a, b.startsWith("-") ? b.slice(1) : `-${b}`]);
}

/**
 * The points the value chart draws: every stored snapshot, ending in the
 * portfolio as it stands now. A snapshot already stored for today gives way
 * to the live measurement — the same day, measured later.
 */
export function seriesOf(development: Development): Measurement[] {
  const { snapshots, current } = development;
  return [
    ...snapshots.filter((snapshot) => snapshot.snapshot_date < current.snapshot_date),
    current,
  ];
}

export const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;
export type Range = (typeof RANGES)[number];

const RANGE_LABEL: Record<Range, string> = {
  "1M": "1 month",
  "3M": "3 months",
  "6M": "6 months",
  YTD: "Year to date",
  "1Y": "1 year",
  ALL: "Everything",
};

const MONTHS_BACK: Partial<Record<Range, number>> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 };

/** The first date a range reaches back to, counted from `today` (ISO). */
function rangeStart(range: Range, today: string): string {
  if (range === "ALL") {
    return "";
  }
  const [year = 0, month = 1, day = 1] = today.split("-").map(Number);
  if (range === "YTD") {
    return `${year}-01-01`;
  }
  // The same day of the earlier month, or that month's last day where it
  // has no such day — never spilling into the month after.
  const first = new Date(Date.UTC(year, month - 1 - (MONTHS_BACK[range] ?? 0), 1));
  const lastDay = new Date(
    Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0),
  ).getUTCDate();
  first.setUTCDate(Math.min(day, lastDay));
  return first.toISOString().slice(0, 10);
}

/** The points of a series a range covers, counted back from `today` (ISO). */
export function inRange(series: Measurement[], range: Range, today: string): Measurement[] {
  const start = rangeStart(range, today);
  return series.filter((point) => point.snapshot_date >= start);
}

export interface Change {
  from: string;
  to: string;
  /** How much the value moved between the two points. */
  value: string;
  /** How much of that was put in (or, negative, taken out). */
  netContributions: string;
  /** The rest: what the holdings themselves did. */
  result: string;
  /**
   * Either end leaves something out — a flow nothing could value, a position
   * outside the totals — so part of the result may be a deposit that could
   * not be counted, or a price that went missing.
   */
  partial: boolean;
}

/**
 * The change across a series, split so a deposit never reads as a gain:
 * the move in value, the part of it that was contributed or withdrawn, and
 * the remainder — the result. Measured between the first and last points
 * that state a value; null when fewer than two do.
 */
export function changeOver(series: Measurement[]): Change | null {
  const valued = series.filter((point) => point.value_eur !== null);
  const first = valued[0];
  const last = valued[valued.length - 1];
  if (!first || !last || first === last) {
    return null;
  }
  const value = subtractFixed(last.value_eur ?? "0", first.value_eur ?? "0");
  const netContributions = subtractFixed(last.net_contributions_eur, first.net_contributions_eur);
  return {
    from: first.snapshot_date,
    to: last.snapshot_date,
    value,
    netContributions,
    result: subtractFixed(value, netContributions),
    partial: [first, last].some(
      (point) => point.unvalued_flows > 0 || point.positions_counted < point.positions_held,
    ),
  };
}

export type Dimension = "asset_class" | "instrument" | "platform";

/** A slice smaller than this share of the charted total is grouped. */
export const GROUPING_THRESHOLD = 0.02;

export interface Slice {
  key: string;
  label: string;
  /** EUR, summed exactly. */
  value: string;
  /** Of the charted total, 0–1 — presentation, so a float. */
  share: number;
  positions: number;
  /** The labels a grouped slice stands for; null for a slice of its own. */
  grouped: string[] | null;
}

export interface Allocation {
  slices: Slice[];
  /** How many positions the slices cover, against how many are held. */
  charted: number;
  held: number;
}

const SLICE_OF: Record<Dimension, (position: Position) => { key: string; label: string }> = {
  asset_class: (position) => ({ key: position.family, label: FAMILY_LABEL[position.family] }),
  // By identity, never by ticker: two Instruments may share a symbol.
  instrument: (position) => ({ key: String(position.instrument_id), label: position.symbol }),
  // A Platform is its name and kind together; the name alone may repeat.
  platform: (position) => ({
    key: `${position.platform_kind}:${position.platform_name}`,
    label: position.platform_name,
  }),
};

/**
 * How the portfolio's value divides along one dimension. Only a position
 * that counts and is worth something can hold a share, so the allocation
 * says how many of the held positions it charts. Slices run largest first;
 * those below the threshold are grouped into one — summarised, never
 * dropped — unless there is only one, which keeps its own name.
 */
export function allocate(positions: Position[], dimension: Dimension): Allocation {
  const chartable = positions.filter(
    (position) => counts(position) && position.value_eur !== null && Number(position.value_eur) > 0,
  );
  const buckets = new Map<string, { label: string; values: string[] }>();
  for (const position of chartable) {
    const { key, label } = SLICE_OF[dimension](position);
    const bucket = buckets.get(key) ?? { label, values: [] };
    bucket.values.push(position.value_eur ?? "0");
    buckets.set(key, bucket);
  }
  const total = chartable.reduce((sum, position) => sum + Number(position.value_eur), 0);
  const slices: Slice[] = [...buckets.entries()]
    .map(([key, bucket]) => {
      const value = sumFixed(bucket.values);
      return {
        key,
        label: bucket.label,
        value,
        share: Number(value) / total,
        positions: bucket.values.length,
        grouped: null,
      };
    })
    .sort((a, b) => Number(b.value) - Number(a.value) || a.label.localeCompare(b.label));

  const small = slices.filter((slice) => slice.share < GROUPING_THRESHOLD);
  if (small.length < 2) {
    return { slices, charted: chartable.length, held: positions.length };
  }
  const groupedValue = sumFixed(small.map((slice) => slice.value));
  return {
    slices: [
      ...slices.filter((slice) => slice.share >= GROUPING_THRESHOLD),
      {
        key: "grouped",
        label: `${small.length} smaller`,
        value: groupedValue,
        share: Number(groupedValue) / total,
        positions: small.reduce((sum, slice) => sum + slice.positions, 0),
        grouped: small.map((slice) => slice.label),
      },
    ],
    charted: chartable.length,
    held: positions.length,
  };
}

/** What every allocation chart says about its own completeness. */
export function coverageLine(charted: number, held: number): string {
  return `charts ${charted} of ${held} ${held === 1 ? "position" : "positions"} held`;
}

/** The caveat beside a realised figure that does not cover every event. */
export function realisedLine(realised: Pick<Realised, "stated" | "events">): string | null {
  return realised.stated < realised.events
    ? `over ${realised.stated} of ${realised.events} sales and closes`
    : null;
}

const KIND_LABEL: Record<RealisedComponent["kind"], string> = {
  private_sales: "Coins and foreign cash",
  securities: "Securities",
  futures: "Futures",
};

const DIMENSION_LABEL: Record<Dimension, string> = {
  asset_class: "By asset class",
  instrument: "By Instrument",
  platform: "By Platform",
};

const UNSTATED_VALUE_TITLE =
  "Something is held, but nothing counted states a value — the figure is unknown, not zero.";

const RESULT_TITLE =
  "Value less what was put in, plus what was taken out — everything the holdings did, realised or not: price moves, income, fees.";

const UNVALUED_FLOWS_TITLE =
  "A coin that arrived or left on a day no stored close answers for, or a currency with no stored reference rate. Backfilling the Instrument's closes settles it.";

function tone(amount: string): string {
  return amount.startsWith("-") ? "text-alarm" : "text-signal";
}

function unvaluedFlowsLine(count: number): string {
  return count === 1
    ? "1 contribution or withdrawal could not be valued and stands outside"
    : `${count} contributions or withdrawals could not be valued and stand outside`;
}

interface Display {
  currency: DisplayCurrency;
  rate: DisplayRate | null;
}

export function PortfolioPage() {
  const development = useQuery({ queryKey: ["portfolio-development"], queryFn: fetchDevelopment });
  const holdings = useQuery({ queryKey: ["holdings"], queryFn: fetchHoldings });
  const realised = useQuery({ queryKey: ["portfolio-realised"], queryFn: fetchRealised });
  const displayCurrency = useDisplayCurrency();
  const display: Display = { currency: displayCurrency.shown, rate: displayCurrency.rate };

  return (
    <div className="space-y-12">
      <PageHeader
        eyebrow="Ledger"
        title="Portfolio"
        description="How the portfolio developed — its value kept apart from what was put in and taken out, so a deposit never reads as a gain."
        actions={<DisplayCurrencySelect {...displayCurrency} />}
      />

      <DisplayRateNotice {...displayCurrency} />

      {development.error ? (
        <ErrorState
          title="The portfolio's development could not be loaded"
          detail="The API did not answer with the snapshots."
          onRetry={() => void development.refetch()}
        />
      ) : development.data ? (
        <>
          <ResultStrip
            current={development.data.current}
            positions={holdings.data?.positions ?? null}
            holdingsFailed={holdings.error != null}
            realised={realised.data ?? null}
            realisedFailed={realised.error != null}
            onRetryRealised={() => void realised.refetch()}
            display={display}
          />
          <DevelopmentSection development={development.data} display={display} />
        </>
      ) : null}

      {holdings.error ? (
        <ErrorState
          title="The allocation could not be loaded"
          detail="The API did not answer with the holdings."
          onRetry={() => void holdings.refetch()}
        />
      ) : holdings.data ? (
        <AllocationSection positions={holdings.data.positions} display={display} />
      ) : null}
    </div>
  );
}

function Figure({
  label,
  title,
  children,
}: {
  label: string;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div title={title}>
      <p className="microlabel text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}

function Unstated({ title, size = "text-xl" }: { title: string; size?: string }) {
  return (
    <p className={`mt-1 font-mono tabular-nums text-muted-foreground ${size}`} title={title}>
      cannot be stated
    </p>
  );
}

function ResultStrip({
  current,
  positions,
  holdingsFailed,
  realised,
  realisedFailed,
  onRetryRealised,
  display,
}: {
  current: Measurement;
  positions: Position[] | null;
  holdingsFailed: boolean;
  realised: Realised | null;
  realisedFailed: boolean;
  onRetryRealised: () => void;
  display: Display;
}) {
  const money = (amount: string) => displayMoney(amount, display.currency, display.rate);
  const totals = positions ? totalsOf(positions) : null;
  const uncounted = current.positions_held - current.positions_counted;
  return (
    <section aria-label="Portfolio results" className="rise border-b border-border pb-8">
      <Figure label="Value now">
        {current.value_eur !== null ? (
          <p className="mt-1 font-mono text-display tabular-nums">{money(current.value_eur)}</p>
        ) : (
          <Unstated title={UNSTATED_VALUE_TITLE} size="text-3xl" />
        )}
        {uncounted > 0 && (
          <p className="microlabel mt-2 text-caution">
            over {current.positions_counted} of {current.positions_held} positions —{" "}
            <Link to="/holdings" className="underline underline-offset-2">
              {uncounted} outside the totals
            </Link>
          </p>
        )}
      </Figure>

      <div className="mt-8 grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Net contributions"
          title={`${money(current.contributions_eur)} put in, ${money(current.withdrawals_eur)} taken out — transfers in and out that no confirmed self-transfer explains, Opening Balances and spends.`}
        >
          <p className="mt-1 font-mono text-xl tabular-nums">
            {money(current.net_contributions_eur)}
          </p>
          {current.unvalued_flows > 0 && (
            <p className="microlabel mt-1 text-caution" title={UNVALUED_FLOWS_TITLE}>
              {unvaluedFlowsLine(current.unvalued_flows)}
            </p>
          )}
        </Figure>

        <Figure label="Result" title={RESULT_TITLE}>
          {current.result_eur !== null ? (
            <p className={`mt-1 font-mono text-xl tabular-nums ${tone(current.result_eur)}`}>
              {money(current.result_eur)}
            </p>
          ) : (
            <Unstated title={UNSTATED_VALUE_TITLE} />
          )}
        </Figure>

        <Figure label="Unrealised">
          {holdingsFailed ? (
            <p role="alert" className="mt-1 text-sm text-alarm">
              The holdings could not be loaded — retry below.
            </p>
          ) : totals === null ? (
            <p className="mt-1 font-mono text-xl text-muted-foreground">…</p>
          ) : totals.unrealisedStated === 0 ? (
            <Unstated title="No counted position can state its unrealised result yet." />
          ) : (
            <p className={`mt-1 font-mono text-xl tabular-nums ${tone(totals.unrealised)}`}>
              {money(totals.unrealised)}
            </p>
          )}
          {totals !== null && totals.unrealisedStated < totals.counted && (
            <p
              className="microlabel mt-1 text-caution"
              title="A position whose basis awaits a valuation, or holds unvouched quantity, cannot state its unrealised result."
            >
              over {totals.unrealisedStated} of {totals.counted} counted positions
            </p>
          )}
        </Figure>

        <Figure label="Realised">
          <RealisedFigure
            realised={realised}
            failed={realisedFailed}
            onRetry={onRetryRealised}
            money={money}
          />
        </Figure>
      </div>
    </section>
  );
}

function RealisedFigure({
  realised,
  failed,
  onRetry,
  money,
}: {
  realised: Realised | null;
  failed: boolean;
  onRetry: () => void;
  money: (amount: string) => string;
}) {
  if (failed) {
    // In place and small: the figures beside it stay readable.
    return (
      <div role="alert" className="mt-1 space-y-2 text-sm text-alarm">
        <p>The realised result could not be loaded.</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </div>
    );
  }
  if (realised === null) {
    return <p className="mt-1 font-mono text-xl text-muted-foreground">…</p>;
  }
  const caveat = realisedLine(realised);
  const active = realised.components.filter(
    (component) => component.events > 0 || component.refusal !== null,
  );
  return (
    <>
      {realised.result_eur !== null ? (
        <p className={`mt-1 font-mono text-xl tabular-nums ${tone(realised.result_eur)}`}>
          {money(realised.result_eur)}
        </p>
      ) : (
        <Unstated title="At least one kind of sale cannot state what it made — see below." />
      )}
      {caveat && (
        <p
          className="microlabel mt-1 text-caution"
          title="A sale or close whose gain cannot be stated yet — a price or a basis still awaited — is counted and left out of the sum."
        >
          {caveat}
        </p>
      )}
      {active.length > 0 && (
        <dl className="mt-3 space-y-1.5 text-xs">
          {active.map((component) => (
            <div key={component.kind}>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">{KIND_LABEL[component.kind]}</dt>
                <dd className="font-mono tabular-nums">
                  {component.result_eur !== null ? (
                    money(component.result_eur)
                  ) : (
                    <span className="text-caution">cannot be stated</span>
                  )}
                </dd>
              </div>
              {component.refusal && <p className="mt-0.5 text-caution">{component.refusal}</p>}
            </div>
          ))}
        </dl>
      )}
    </>
  );
}

function DevelopmentSection({
  development,
  display,
}: {
  development: Development;
  display: Display;
}) {
  const [range, setRange] = useState<Range>("ALL");
  const series = seriesOf(development);
  const today = development.current.snapshot_date;
  const points = inRange(series, range, today);
  const change = changeOver(points);
  const money = (amount: string) => displayMoney(amount, display.currency, display.rate);

  return (
    <section aria-labelledby="development-heading" className="rise space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="development-heading" className="text-lg font-semibold tracking-tight">
            Development
          </h2>
          <p className="mt-1 max-w-xl text-sm text-muted-foreground">
            One stored snapshot a day, ending in the portfolio as it stands now.
          </p>
        </div>
        <div role="group" aria-label="Range" className="flex gap-1">
          {RANGES.map((choice) => (
            <Button
              key={choice}
              size="sm"
              variant={choice === range ? "secondary" : "ghost"}
              aria-pressed={choice === range}
              title={RANGE_LABEL[choice]}
              className="font-mono"
              onClick={() => setRange(choice)}
            >
              {choice}
            </Button>
          ))}
        </div>
      </div>

      {development.snapshots.length === 0 ? (
        <EmptyState
          icon={ChartLine}
          title="No snapshot is stored yet"
          description="The Portfolio snapshot task stores one point a day. Until its first run there is only the present to show — run it now, or wait for tonight."
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/settings/scheduled-tasks">Open Scheduled tasks</Link>
            </Button>
          }
        />
      ) : (
        <>
          {change ? (
            <dl
              aria-label={`Change from ${formatDate(change.from)} to ${formatDate(change.to)}`}
              className="grid gap-x-10 gap-y-4 border-y border-border py-4 sm:grid-cols-3"
            >
              <div>
                <dt className="microlabel text-muted-foreground">Change in value</dt>
                <dd className="mt-1 font-mono text-lg tabular-nums">{money(change.value)}</dd>
              </div>
              <div>
                <dt className="microlabel text-muted-foreground">of which put in or taken out</dt>
                <dd className="mt-1 font-mono text-lg tabular-nums">
                  {money(change.netContributions)}
                </dd>
              </div>
              <div title={RESULT_TITLE}>
                <dt className="microlabel text-muted-foreground">of which result</dt>
                <dd className={`mt-1 font-mono text-lg tabular-nums ${tone(change.result)}`}>
                  {money(change.result)}
                </dd>
              </div>
              {change.partial && (
                <p className="microlabel text-caution sm:col-span-3">
                  a point at either end leaves out a position or an unvalued contribution — part
                  of this result may be money moved or a price gone missing, not a gain or loss
                </p>
              )}
            </dl>
          ) : (
            <p className="microlabel border-y border-border py-4 text-muted-foreground">
              {range === "ALL"
                ? "one point states a value so far — a change needs two, and the next snapshot brings the second"
                : "fewer than two points state a value in this range — choose a longer one"}
            </p>
          )}
          {points.length >= 2 && <ValueChart points={points} display={display} />}
          <PointsTable points={points} money={money} />
        </>
      )}
    </section>
  );
}

const CHART_HEIGHT = 280;
const PAD = { top: 16, right: 12, bottom: 28, left: 12 };

function dayOf(isoDate: string): number {
  return Date.parse(`${isoDate}T00:00:00Z`);
}

/** A width that follows its container, so the SVG never scales its text. */
function useMeasuredWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry?.contentRect.width ?? 0);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/**
 * Value against net contributions on one EUR axis: the solid line is what
 * the portfolio was worth, the dashed step what had been put in net — the
 * gap between them is the result. A point with no stated value breaks the
 * line rather than dipping to zero. The readout above follows the pointer
 * or the arrow keys, and rests on the latest point.
 */
function ValueChart({ points, display }: { points: Measurement[]; display: Display }) {
  const [ref, width] = useMeasuredWidth();
  const [active, setActive] = useState<number | null>(null);
  const factor = display.rate ? Number(display.rate.rate) : 1;
  const shown = points[Math.min(active ?? points.length - 1, points.length - 1)] ?? points[0];
  const money = (amount: string) => displayMoney(amount, display.currency, display.rate);

  const first = dayOf(points[0]?.snapshot_date ?? "");
  const last = dayOf(points[points.length - 1]?.snapshot_date ?? "");
  const amounts = points.flatMap((point) => [
    ...(point.value_eur !== null ? [Number(point.value_eur) * factor] : []),
    Number(point.net_contributions_eur) * factor,
  ]);
  const low = Math.min(...amounts);
  const high = Math.max(...amounts);
  const margin = (high - low || Math.abs(high) || 1) * 0.08;
  const bottom = low - margin;
  const top = high + margin;

  const plotWidth = Math.max(width - PAD.left - PAD.right, 1);
  const plotHeight = CHART_HEIGHT - PAD.top - PAD.bottom;
  const x = (point: Measurement) =>
    PAD.left + ((dayOf(point.snapshot_date) - first) / (last - first || 1)) * plotWidth;
  const y = (amount: number) => PAD.top + (1 - (amount - bottom) / (top - bottom)) * plotHeight;
  const valueY = (point: Measurement) => y(Number(point.value_eur) * factor);
  const netY = (point: Measurement) => y(Number(point.net_contributions_eur) * factor);

  // The value line lifts its pen over a point that states no value.
  let pen = false;
  const valuePath = points
    .map((point) => {
      if (point.value_eur === null) {
        pen = false;
        return "";
      }
      const command = `${pen ? "L" : "M"}${x(point).toFixed(1)},${valueY(point).toFixed(1)}`;
      pen = true;
      return command;
    })
    .join("");
  // Contributions hold until the next snapshot says otherwise: a step.
  const netPath = points
    .map((point, index) =>
      index === 0
        ? `M${x(point).toFixed(1)},${netY(point).toFixed(1)}`
        : `H${x(point).toFixed(1)}V${netY(point).toFixed(1)}`,
    )
    .join("");
  const gridlines = [0.25, 0.5, 0.75].map((step) => bottom + (top - bottom) * step);

  const nearest = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const at = event.clientX - bounds.left;
    let best = 0;
    points.forEach((point, index) => {
      if (Math.abs(x(point) - at) < Math.abs(x(points[best] ?? point) - at)) {
        best = index;
      }
    });
    setActive(best);
  };
  const step = (event: KeyboardEvent<SVGSVGElement>) => {
    const move = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (move === 0) {
      return;
    }
    event.preventDefault();
    const from = active ?? points.length - 1;
    setActive(Math.max(0, Math.min(points.length - 1, from + move)));
  };

  if (!shown) {
    return null;
  }
  return (
    <div className="space-y-3">
      <dl className="flex flex-wrap items-baseline gap-x-8 gap-y-2 text-sm" aria-live="off">
        <div>
          <dt className="sr-only">Date</dt>
          <dd className="microlabel text-muted-foreground">
            {formatDate(shown.snapshot_date)}
            {shown === points[points.length - 1] && " · now"}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="flex items-center gap-2 text-muted-foreground">
            <span aria-hidden className="inline-block h-0.5 w-5 bg-foreground" />
            Value
          </dt>
          <dd className="font-mono tabular-nums">
            {shown.value_eur !== null ? (
              money(shown.value_eur)
            ) : (
              <span className="text-caution" title={UNSTATED_VALUE_TITLE}>
                cannot be stated
              </span>
            )}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="flex items-center gap-2 text-muted-foreground">
            <span
              aria-hidden
              className="inline-block w-5 border-t-2 border-dashed border-muted-foreground"
            />
            Net contributions
          </dt>
          <dd className="font-mono tabular-nums">{money(shown.net_contributions_eur)}</dd>
        </div>
        {shown.result_eur !== null && (
          <div className="flex items-baseline gap-2" title={RESULT_TITLE}>
            <dt className="text-muted-foreground">Result</dt>
            <dd className={`font-mono tabular-nums ${tone(shown.result_eur)}`}>
              {money(shown.result_eur)}
            </dd>
          </div>
        )}
        <div
          className={`microlabel ${
            shown.positions_counted < shown.positions_held || shown.unvalued_flows > 0
              ? "text-caution"
              : "text-muted-foreground"
          }`}
          title={shown.unvalued_flows > 0 ? UNVALUED_FLOWS_TITLE : undefined}
        >
          {coverageLine(shown.positions_counted, shown.positions_held)}
          {shown.unvalued_flows > 0 &&
            ` · ${shown.unvalued_flows} unvalued contributions or withdrawals`}
        </div>
      </dl>

      <div ref={ref}>
        {width > 0 && (
          <svg
            width={width}
            height={CHART_HEIGHT}
            role="img"
            aria-label={`Portfolio value against net contributions from ${formatDate(
              points[0]?.snapshot_date ?? "",
            )} to ${formatDate(points[points.length - 1]?.snapshot_date ?? "")}. Arrow keys step through the points.`}
            tabIndex={0}
            className="block touch-none select-none"
            onPointerMove={nearest}
            onPointerDown={nearest}
            onPointerLeave={() => setActive(null)}
            onKeyDown={step}
            onBlur={() => setActive(null)}
          >
            {gridlines.map((amount) => (
              <g key={amount}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y(amount)}
                  y2={y(amount)}
                  className="stroke-border"
                />
                <text
                  x={PAD.left}
                  y={y(amount) - 5}
                  strokeWidth={4}
                  paintOrder="stroke"
                  className="fill-muted-foreground stroke-background font-mono text-2xs"
                >
                  {formatMoney(amount, display.currency, undefined, { maxFractionDigits: 0 })}
                </text>
              </g>
            ))}
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={CHART_HEIGHT - PAD.bottom}
              y2={CHART_HEIGHT - PAD.bottom}
              className="stroke-input"
            />
            <text
              x={PAD.left}
              y={CHART_HEIGHT - 8}
              className="fill-muted-foreground font-mono text-2xs"
            >
              {formatDate(points[0]?.snapshot_date ?? "")}
            </text>
            <text
              x={width - PAD.right}
              y={CHART_HEIGHT - 8}
              textAnchor="end"
              className="fill-muted-foreground font-mono text-2xs"
            >
              {formatDate(points[points.length - 1]?.snapshot_date ?? "")}
            </text>

            <path
              d={netPath}
              fill="none"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              className="stroke-muted-foreground"
            />
            <path
              d={valuePath}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              className="stroke-foreground"
            />
            {/* A valued point with unvalued neighbours has no line to sit on. */}
            {points.map((point, index) =>
              point.value_eur !== null &&
              points[index - 1]?.value_eur == null &&
              points[index + 1]?.value_eur == null ? (
                <circle
                  key={point.snapshot_date}
                  cx={x(point)}
                  cy={valueY(point)}
                  r={2.5}
                  className="fill-foreground"
                />
              ) : null,
            )}

            <g>
              <line
                x1={x(shown)}
                x2={x(shown)}
                y1={PAD.top}
                y2={CHART_HEIGHT - PAD.bottom}
                className="stroke-input"
              />
              <rect
                x={x(shown) - 3.5}
                y={netY(shown) - 3.5}
                width={7}
                height={7}
                strokeWidth={2}
                className="fill-muted-foreground stroke-background"
              />
              {shown.value_eur !== null && (
                <circle
                  cx={x(shown)}
                  cy={valueY(shown)}
                  r={5}
                  strokeWidth={2}
                  className="fill-foreground stroke-background"
                />
              )}
            </g>
          </svg>
        )}
      </div>
    </div>
  );
}

function PointsTable({
  points,
  money,
}: {
  points: Measurement[];
  money: (amount: string) => string;
}) {
  return (
    <details>
      <summary className="microlabel cursor-pointer text-muted-foreground">
        the {points.length} points as a table
      </summary>
      <table className="mt-3 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
              Date
            </th>
            {["Value", "Net contributions", "Result", "Positions counted"].map((column) => (
              <th
                key={column}
                scope="col"
                className="microlabel py-2.5 pr-4 text-right text-muted-foreground"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...points].reverse().map((point) => (
            <tr key={point.snapshot_date} className="border-b border-border">
              <td className="py-2 pr-4 font-mono tabular-nums">{formatDate(point.snapshot_date)}</td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">
                {point.value_eur !== null ? (
                  money(point.value_eur)
                ) : (
                  <span className="microlabel text-caution" title={UNSTATED_VALUE_TITLE}>
                    cannot be stated
                  </span>
                )}
              </td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">
                {money(point.net_contributions_eur)}
                {point.unvalued_flows > 0 && (
                  <span
                    className="microlabel block text-caution"
                    title={UNVALUED_FLOWS_TITLE}
                  >
                    {point.unvalued_flows} unvalued
                  </span>
                )}
              </td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">
                {point.result_eur !== null ? (
                  <span className={tone(point.result_eur)}>{money(point.result_eur)}</span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              <td className="py-2 pr-4 text-right font-mono tabular-nums">
                {point.positions_counted} of {point.positions_held}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function AllocationSection({ positions, display }: { positions: Position[]; display: Display }) {
  return (
    <section aria-labelledby="allocation-heading" className="rise space-y-6">
      <div>
        <h2 id="allocation-heading" className="text-lg font-semibold tracking-tight">
          Allocation
        </h2>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          How the value divides. Only a position that counts and is worth something holds a share
          — each chart says how many that is.
        </p>
      </div>
      {positions.length === 0 ? (
        <EmptyState
          icon={ChartLine}
          title="Nothing is held yet"
          description="An allocation appears as soon as the ledger records something sitting in an Account — record Transactions or run an import first."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button asChild variant="outline" size="sm">
                <Link to="/imports">Go to Imports</Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link to="/transactions">Record a Transaction</Link>
              </Button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-x-12 gap-y-10 lg:grid-cols-3">
          {(["asset_class", "instrument", "platform"] as const).map((dimension) => (
            <AllocationChart
              key={dimension}
              dimension={dimension}
              allocation={allocate(positions, dimension)}
              display={display}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function AllocationChart({
  dimension,
  allocation,
  display,
}: {
  dimension: Dimension;
  allocation: Allocation;
  display: Display;
}) {
  const headingId = `allocation-${dimension}`;
  const complete = allocation.charted === allocation.held;
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="microlabel">
        {DIMENSION_LABEL[dimension]}
      </h3>
      <p className={`microlabel mt-1 ${complete ? "text-muted-foreground" : "text-caution"}`}>
        {coverageLine(allocation.charted, allocation.held)}
      </p>
      {allocation.slices.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">
          No held position states a value, so there is nothing to divide.{" "}
          <Link to="/holdings" className="underline underline-offset-2">
            Holdings
          </Link>{" "}
          says what each position is missing.
        </p>
      ) : (
        <ol className="mt-4 space-y-3.5">
          {allocation.slices.map((slice) => (
            <li
              key={slice.key}
              title={
                slice.grouped
                  ? `Each below ${formatPercent(GROUPING_THRESHOLD)}: ${slice.grouped.join(", ")}`
                  : `${slice.positions} ${slice.positions === 1 ? "position" : "positions"}`
              }
            >
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className={slice.grouped ? "text-muted-foreground" : undefined}>
                  {slice.label}
                </span>
                <span className="font-mono tabular-nums">{formatPercent(slice.share)}</span>
              </div>
              <div className="mt-1.5 h-1.5 rounded-full bg-muted">
                <div
                  className={`h-full min-w-0.5 rounded-full ${
                    slice.grouped ? "bg-muted-foreground" : "bg-foreground"
                  }`}
                  style={{ width: `${slice.share * 100}%` }}
                />
              </div>
              <p className="mt-1 font-mono text-2xs tabular-nums text-muted-foreground">
                {displayMoney(slice.value, display.currency, display.rate)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
