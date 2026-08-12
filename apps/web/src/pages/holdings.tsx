import { useQuery } from "@tanstack/react-query";
import { Coins, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { type CoverageWarning, fetchCoverageWarnings } from "@/api/connections";
import {
  type DisplayRate,
  fetchDisplayRate,
  fetchHoldings,
  type Position,
} from "@/api/holdings";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { NativeSelect } from "@/components/ui/native-select";
import {
  type DisplayCurrency,
  DISPLAY_CURRENCIES,
  getDisplayCurrency,
  setDisplayCurrency,
} from "@/lib/display-currency";
import {
  formatDate,
  formatMoney,
  formatMoneyExact,
  formatQuantity,
  formatTimestamp,
} from "@/lib/format";

export type GroupMode = "asset_class" | "platform" | "custody";

/**
 * Custody is judged from the Platform's kind: a cold-storage device or a
 * software wallet is held by the Admin themself; an exchange, broker or bank
 * holds on the Admin's behalf.
 */
export function custodyOf(kind: Position["platform_kind"]): "self_custody" | "third_party" {
  return kind === "cold_storage" || kind === "software_wallet" ? "self_custody" : "third_party";
}

const CUSTODY_LABEL: Record<ReturnType<typeof custodyOf>, string> = {
  self_custody: "Self-custody",
  third_party: "Third-party custody",
};

const FAMILY_LABEL: Record<Position["family"], string> = {
  crypto: "Crypto",
  cash: "Cash",
  security: "Security",
};

/** How each mode buckets: the label a position files under, and the order the
 * buckets render in — fixed where the vocabulary has one, alphabetical for
 * Platforms. */
const GROUPINGS: Record<
  GroupMode,
  { labelOf: (position: Position) => string; order: (labels: string[]) => string[] }
> = {
  asset_class: {
    labelOf: (position) => FAMILY_LABEL[position.family],
    order: () => ["crypto", "cash", "security"].map((family) => FAMILY_LABEL[family as Position["family"]]),
  },
  platform: {
    labelOf: (position) => position.platform_name,
    order: (labels) => [...labels].sort((a, b) => a.localeCompare(b)),
  },
  custody: {
    labelOf: (position) => CUSTODY_LABEL[custodyOf(position.platform_kind)],
    order: () => [CUSTODY_LABEL.self_custody, CUSTODY_LABEL.third_party],
  },
};

export interface Group {
  label: string;
  positions: Position[];
}

/**
 * Positions bucketed for display: by asset class (the Instrument family), by
 * Platform, or by custody type. Grouping is presentation — the API serves a
 * flat portfolio and every bucket sums client-side.
 */
export function groupHoldings(positions: Position[], mode: GroupMode): Group[] {
  const grouping = GROUPINGS[mode];
  const buckets = new Map<string, Position[]>();
  for (const position of positions) {
    const label = grouping.labelOf(position);
    buckets.set(label, [...(buckets.get(label) ?? []), position]);
  }
  return grouping
    .order([...buckets.keys()])
    .filter((label) => buckets.has(label))
    .map((label) => ({ label, positions: buckets.get(label) ?? [] }));
}

/**
 * Fixed-point decimal strings summed without ever passing through a float:
 * every value scaled to the longest fraction, added as BigInt, the digits
 * reassembled verbatim.
 */
export function sumFixed(values: string[]): string {
  const scale = Math.max(0, ...values.map((value) => (value.split(".")[1] ?? "").length));
  let total = 0n;
  for (const value of values) {
    const negative = value.startsWith("-");
    const [integer = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
    const scaled = BigInt(integer + fraction.padEnd(scale, "0"));
    total += negative ? -scaled : scaled;
  }
  const negative = total < 0n;
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale > 0 ? `.${digits.slice(digits.length - scale)}` : "";
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

/** A position counts toward totals only while nothing marks it. */
export function counts(position: Position): boolean {
  return position.marker === null;
}

export interface Totals {
  /** EUR value summed over every counted position. */
  value: string;
  /** EUR unrealised result summed where the basis is stated. */
  unrealised: string;
  counted: number;
  /** How many counted positions actually state an unrealised result. */
  unrealisedStated: number;
}

export function totalsOf(positions: Position[]): Totals {
  const counted = positions.filter(counts);
  const stated = counted.filter((position) => position.unrealised_eur !== null);
  return {
    value: sumFixed(counted.map((position) => position.value_eur ?? "0")),
    unrealised: sumFixed(stated.map((position) => position.unrealised_eur ?? "0")),
    counted: counted.length,
    unrealisedStated: stated.length,
  };
}

/**
 * One line saying what stands outside the totals and why — never a silently
 * shorter sum. Null when everything counts.
 */
export function exclusionLine(positions: Position[]): string | null {
  const excluded = positions.filter((position) => !counts(position));
  if (excluded.length === 0) {
    return null;
  }
  const byMarker = new Map<string, number>();
  for (const position of excluded) {
    const marker = position.marker ?? "unpriced";
    byMarker.set(marker, (byMarker.get(marker) ?? 0) + 1);
  }
  const parts = [...byMarker.entries()].map(([marker, count]) => `${count} ${marker}`);
  const plural = excluded.length === 1 ? "position stands" : "positions stand";
  return `${excluded.length} ${plural} outside the totals: ${parts.join(", ")}`;
}

/**
 * An EUR figure rendered in the DisplayCurrency. EUR renders exact, digits
 * verbatim off the API; any other currency multiplies by the served
 * reference rate — presentation only, so a float is acceptable here and the
 * underlying tax figure stays EUR and exact.
 */
export function displayMoney(
  amountEur: string,
  currency: DisplayCurrency,
  rate: DisplayRate | null,
  locale?: string,
): string {
  if (currency === "EUR" || rate === null) {
    return formatMoneyExact(amountEur, "EUR", locale);
  }
  return formatMoney(Number(amountEur) * Number(rate.rate), currency, locale);
}

const MARKER_TITLE: Record<NonNullable<Position["marker"]>, string> = {
  dangerous:
    "Marked dangerous everywhere — the position stays visible, but it mints no lot, can never acquire a price source, and stands outside the totals.",
  ignored:
    "Ignored at this Account — the position stays visible, but it never enters the cost basis and stands outside the totals.",
  unacknowledged:
    "Waiting in the Inbox — no Stance is decided yet, so nothing vouches for a basis and the position stands outside the totals.",
  unpriced:
    "Nothing can state this position's value — no stored price and no rate in reach. It stands outside the totals rather than counting as zero.",
};

const BASIS_GAP_TITLE: Record<NonNullable<Position["basis_gap"]>, string> = {
  awaiting_valuation:
    "The remaining lots await a market value no daily rate alone can state — the basis is unknown, not zero.",
  unvouched:
    "The Account holds quantity no Tax Lot vouches for — an unmatched transfer or an inflow that minted nothing — so a stated basis would cover less than is held.",
};

const BASIS_GAP_LABEL: Record<NonNullable<Position["basis_gap"]>, string> = {
  awaiting_valuation: "awaiting valuation",
  unvouched: "unvouched",
};

const NUMERAIRE_TITLE =
  "The numéraire — every figure is expressed in it, so it has no cost basis or unrealised result of its own.";

/** What the value cell's tooltip names: whose word the figure rests on. */
export function valuationTitle(position: Position, locale?: string): string | undefined {
  if (position.price_source === "reference_rate" && position.rate_date !== null) {
    return `Valued by the stored daily reference rate of ${formatDate(position.rate_date, locale)} — presentation of current worth, never a tax figure.`;
  }
  if (position.price_source !== null && position.price_as_of !== null) {
    return `Last known price from ${position.price_source} at ${formatTimestamp(
      Date.parse(position.price_as_of),
      locale,
    )} — the store answers, never a live provider call.`;
  }
  return undefined;
}

/**
 * One coverage gap in words: the venue named by its Platform and Account,
 * both instants as dates — the day coverage begins (the sync window's
 * horizon, or older activity already recorded in the Account) against the
 * day recorded history begins elsewhere. Dates are read from the instants'
 * UTC days, matching the API's own statement of the horizon.
 */
export function describeCoverageWarning(warning: CoverageWarning, locale?: string): string {
  const starts = formatDate(warning.coverage_starts_at.slice(0, 10), locale);
  const elsewhere = formatDate(warning.earliest_elsewhere_at.slice(0, 10), locale);
  return (
    `${warning.platform_name} · ${warning.account_name}: coverage starts ${starts},` +
    ` but activity elsewhere starts ${elsewhere} — older history at this venue cannot` +
    " arrive by sync."
  );
}

/**
 * The dashboard's coverage warnings: a venue whose history window opens
 * later than the earliest activity recorded elsewhere is a silent gap —
 * "no trades found" would pass for "no trades exist" — so it is named here,
 * with the import path that closes it. Absent quietly only while nothing
 * warns: a check that could not run says so, because for a warning whose
 * job is surfacing silence, silence on failure would be dishonest.
 */
function CoverageWarnings() {
  const { data, error } = useQuery({
    queryKey: ["coverage-warnings"],
    queryFn: fetchCoverageWarnings,
  });
  if (error) {
    return (
      <p className="microlabel text-caution">
        the coverage check could not run — a history gap may be going unreported
      </p>
    );
  }
  if (!data || data.length === 0) {
    return null;
  }
  return (
    <section aria-label="Coverage warnings" className="rise space-y-2.5">
      {data.map((warning) => (
        <aside
          key={`${warning.connection_id}-${warning.account_id}`}
          className="flex gap-2.5 rounded-lg border border-border p-3.5 text-sm"
        >
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-caution" />
          <div className="space-y-1">
            <p>{describeCoverageWarning(warning)}</p>
            <p className="text-xs text-muted-foreground">
              <Link to="/imports" className="underline underline-offset-2">
                Import the missing history
              </Link>{" "}
              to close the gap — a file export reaches further back than the venue's API.
            </p>
          </div>
        </aside>
      ))}
    </section>
  );
}

export function HoldingsPage() {
  const { data, error, refetch } = useQuery({ queryKey: ["holdings"], queryFn: fetchHoldings });
  const [groupMode, setGroupMode] = useState<GroupMode>("asset_class");
  const [currency, setCurrency] = useState<DisplayCurrency>(getDisplayCurrency);
  // The rate arrives separately and only when a foreign display currency is
  // chosen: the holdings figures are EUR either way, so a missing rate
  // degrades the presentation, never the data.
  const rateQuery = useQuery({
    queryKey: ["display-rate", currency],
    queryFn: () => fetchDisplayRate(currency),
    enabled: currency !== "EUR",
  });
  const rate = currency !== "EUR" ? (rateQuery.data ?? null) : null;
  const shown: DisplayCurrency = rate === null ? "EUR" : currency;

  const choose = (choice: DisplayCurrency) => {
    setDisplayCurrency(choice);
    setCurrency(choice);
  };

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Holdings"
        description="Everything held — crypto, securities and cash — with its cost basis read from the Tax Lots, so the portfolio and the tax report cannot disagree."
        actions={
          <>
            <NativeSelect
              aria-label="Group by"
              value={groupMode}
              onChange={(event) => setGroupMode(event.target.value as GroupMode)}
            >
              <option value="asset_class">By asset class</option>
              <option value="platform">By Platform</option>
              <option value="custody">By custody</option>
            </NativeSelect>
            <NativeSelect
              aria-label="Display currency"
              value={currency}
              onChange={(event) => choose(event.target.value as DisplayCurrency)}
            >
              {DISPLAY_CURRENCIES.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </NativeSelect>
          </>
        }
      />

      <CoverageWarnings />

      {error ? (
        <ErrorState
          title="The holdings could not be loaded"
          detail="The API did not answer with the portfolio."
          onRetry={() => void refetch()}
        />
      ) : data && data.positions.length === 0 ? (
        <EmptyState
          icon={Coins}
          title="Nothing is held yet"
          description="Positions appear here as soon as the ledger records something sitting in an Account — record Transactions or run an import first."
        />
      ) : data ? (
        <div className="space-y-8">
          {currency !== "EUR" && rateQuery.error != null && (
            <p className="microlabel text-caution">
              the {currency} rate could not be loaded — figures shown in EUR
            </p>
          )}
          {currency !== "EUR" && rateQuery.isPending && (
            <p className="microlabel text-muted-foreground">
              loading the {currency} rate — figures shown in EUR meanwhile
            </p>
          )}
          <TotalsStrip positions={data.positions} currency={shown} rate={rate} />
          <HoldingsTable
            positions={data.positions}
            groupMode={groupMode}
            currency={shown}
            rate={rate}
          />
        </div>
      ) : null}
    </div>
  );
}

function TotalsStrip({
  positions,
  currency,
  rate,
}: {
  positions: Position[];
  currency: DisplayCurrency;
  rate: DisplayRate | null;
}) {
  const totals = totalsOf(positions);
  const exclusions = exclusionLine(positions);
  const negative = totals.unrealised.startsWith("-");
  return (
    <section aria-label="Portfolio totals" className="rise border-y border-border py-5">
      <div className="flex flex-wrap items-end gap-x-12 gap-y-4">
        <div>
          <p className="microlabel text-muted-foreground">Total value</p>
          <p className="mt-1 font-mono text-display tabular-nums">
            {displayMoney(totals.value, currency, rate)}
          </p>
        </div>
        <div>
          <p className="microlabel text-muted-foreground">Unrealised result</p>
          {totals.unrealisedStated === 0 ? (
            <p
              className="mt-1 font-mono text-xl tabular-nums text-muted-foreground"
              title="No counted position can state its unrealised result yet."
            >
              —
            </p>
          ) : (
            <p
              className={`mt-1 font-mono text-xl tabular-nums ${negative ? "text-alarm" : "text-signal"}`}
            >
              {displayMoney(totals.unrealised, currency, rate)}
            </p>
          )}
          {totals.unrealisedStated < totals.counted && (
            <p
              className="microlabel mt-1 text-caution"
              title="A position whose basis awaits a valuation, or holds unvouched quantity, cannot state its unrealised result."
            >
              over {totals.unrealisedStated} of {totals.counted} counted positions
            </p>
          )}
        </div>
        <div>
          <p className="microlabel text-muted-foreground">Positions</p>
          <p className="mt-1 font-mono text-xl tabular-nums">{positions.length}</p>
        </div>
      </div>
      {(exclusions || rate) && (
        <div className="mt-3 space-y-1">
          {exclusions && <p className="microlabel text-caution">{exclusions}</p>}
          {rate && (
            <p className="microlabel text-muted-foreground">
              converted at {formatQuantity(rate.rate)} {rate.currency}/EUR, rate of{" "}
              {formatDate(rate.rate_date)} — presentation only, tax figures stay in EUR
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function HoldingsTable({
  positions,
  groupMode,
  currency,
  rate,
}: {
  positions: Position[];
  groupMode: GroupMode;
  currency: DisplayCurrency;
  rate: DisplayRate | null;
}) {
  const groups = groupHoldings(positions, groupMode);
  let row = 0;
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
          <th scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
            Position
          </th>
          {["Quantity", "Avg cost", "Value", "Unrealised"].map((column) => (
            <th
              key={column}
              scope="col"
              className="microlabel py-2.5 pr-4 text-right text-muted-foreground"
            >
              {column}
            </th>
          ))}
          <th scope="col" className="microlabel py-2.5 text-muted-foreground">
            Location
          </th>
        </tr>
      </thead>
      {groups.map((group) => (
        <tbody key={group.label}>
          <tr className="border-b border-border bg-canvas/50">
            <th scope="rowgroup" colSpan={2} className="microlabel py-2 pr-4 text-left">
              {group.label}
            </th>
            <td colSpan={2} className="microlabel py-2 pr-4 text-right text-muted-foreground">
              {displayMoney(totalsOf(group.positions).value, currency, rate)}
            </td>
            <td />
          </tr>
          {group.positions.map((position) => (
            <PositionRow
              key={`${position.account_id}:${position.instrument_id}`}
              position={position}
              currency={currency}
              rate={rate}
              index={row++}
            />
          ))}
        </tbody>
      ))}
    </table>
  );
}

function PositionRow({
  position,
  currency,
  rate,
  index,
}: {
  position: Position;
  currency: DisplayCurrency;
  rate: DisplayRate | null;
  index: number;
}) {
  return (
    <tr className="rise border-b border-border" style={{ animationDelay: `${120 + index * 30}ms` }}>
      <td className="py-3 pr-4">
        <span className="font-mono tabular-nums">{position.symbol}</span>
        {position.is_numeraire && (
          <span className="microlabel ml-2 text-signal" title={NUMERAIRE_TITLE}>
            numéraire
          </span>
        )}
        {position.marker && (
          <span
            className={`microlabel ml-2 ${
              position.marker === "dangerous" ? "text-alarm" : "text-caution"
            }`}
            title={MARKER_TITLE[position.marker]}
          >
            {position.marker}
          </span>
        )}
        <span className="block text-muted-foreground">
          {position.name} · {FAMILY_LABEL[position.family]} {position.type}
        </span>
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums">
        {formatQuantity(position.quantity)}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums">
        {position.is_numeraire ? (
          <span className="text-muted-foreground" title={NUMERAIRE_TITLE}>
            —
          </span>
        ) : position.average_cost_eur !== null ? (
          displayMoney(position.average_cost_eur, currency, rate)
        ) : position.basis_gap !== null ? (
          <span className="microlabel text-caution" title={BASIS_GAP_TITLE[position.basis_gap]}>
            {BASIS_GAP_LABEL[position.basis_gap]}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums" title={valuationTitle(position)}>
        {position.value_eur !== null ? (
          displayMoney(position.value_eur, currency, rate)
        ) : (
          <span
            className="microlabel text-caution"
            title={position.marker ? MARKER_TITLE[position.marker] : undefined}
          >
            unpriced
          </span>
        )}
      </td>
      <td className="py-3 pr-4 text-right font-mono tabular-nums">
        {position.unrealised_eur !== null ? (
          <span className={position.unrealised_eur.startsWith("-") ? "text-alarm" : "text-signal"}>
            {displayMoney(position.unrealised_eur, currency, rate)}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-3">
        {position.platform_name} · {position.account_name}
        {position.access_software && (
          <span
            className="block text-muted-foreground"
            title="Extra software is needed to reach this Account."
          >
            via {position.access_software}
          </span>
        )}
      </td>
    </tr>
  );
}
