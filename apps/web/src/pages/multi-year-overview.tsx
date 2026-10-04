import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, TriangleAlert } from "lucide-react";
import { Link } from "react-router";
import {
  type CarryforwardLayer,
  fetchMultiYearOverview,
  type OverviewYear,
  type PotCarryforward,
  type RegimeYear,
} from "@/api/multi-year-overview";
import { appendixUrl, fetchReports, generateReport, type ReportSummary } from "@/api/reports";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Lamp } from "@/components/patterns/lamp";
import { Button } from "@/components/ui/button";
import { formatEur, formatTimestamp } from "@/lib/format";
import { NAV_SECTIONS } from "@/navigation";

type RegimeKey = "private_sales" | "other_income" | "capital_income";

interface Regime {
  key: RegimeKey;
  title: string;
  statute: string;
  /** What the allowance column is called under this regime. */
  allowance: string;
  about: string;
}

/** The three regimes, in the order the return meets them. */
const REGIMES: Regime[] = [
  {
    key: "private_sales",
    title: "Private sales",
    statute: "§ 23 EStG",
    allowance: "Freigrenze",
    about:
      "Crypto and other private assets sold inside the Haltefrist. The Freigrenze is all or nothing: under the limit the whole gain is free, at the limit all of it is taxable.",
  },
  {
    key: "other_income",
    title: "Other income",
    statute: "§ 22 Nr. 3 EStG",
    allowance: "Freigrenze",
    about:
      "Sonstige Einkünfte: staking rewards, lending interest, mining and airdrops at their market value on receipt, pooled under one Freigrenze of their own.",
  },
  {
    key: "capital_income",
    title: "Capital income",
    statute: "§ 20 EStG",
    allowance: "Sparerpauschbetrag",
    about:
      "Securities, dividends, interest and futures. Losses and carryforwards offset inside their own pot; the allowance is deducted once across what survives.",
  },
];

const POT_LABEL: Record<PotCarryforward["category"], string> = {
  aktien: "Aktien",
  sonstige: "Sonstige",
  termingeschaefte: "Termingeschäfte",
};

const PERSONAL_RATE_TITLE =
  "Taxed at your personal marginal rate, which the ledger does not know — the taxable amount is the answer here.";

/** A fixed-point amount with no non-zero digit — however many zeros it is written with. */
function isZero(value: string): boolean {
  return !/[1-9]/.test(value);
}

/** The years with an unfinished prerequisite, in the order served. */
export function blockedYears(years: OverviewYear[]): OverviewYear[] {
  return years.filter((year) => year.blockers.length > 0);
}

export interface CarryforwardRow {
  year: number;
  pot: PotCarryforward;
}

/**
 * The carryforward table's rows: one per pot and year in which the pot held,
 * consumed or produced a carryforward. A pot that stayed empty all year says
 * nothing, so the rows that remain are the ones worth reading.
 */
export function carryforwardRows(years: OverviewYear[]): CarryforwardRow[] {
  return years.flatMap((year) =>
    (year.capital_income?.categories ?? [])
      .filter(
        (pot) =>
          !isZero(pot.carryforward_in_eur) ||
          !isZero(pot.produced_eur) ||
          !isZero(pot.carryforward_out_eur),
      )
      .map((pot) => ({ year: year.year, pot })),
  );
}

/** Where a slice of carryforward came from, in words. */
export function describeOrigin(layer: CarryforwardLayer): string {
  return layer.opening
    ? `opening ${layer.origin_year}`
    : `from ${layer.origin_year}`;
}

/**
 * The name of the screen a blocker's path leads to, read from the one place
 * navigation is declared — null for a path no screen is registered at, so
 * the page never offers a link that lands nowhere.
 */
export function resolveLabel(path: string): string | null {
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (item.to === path) {
        return item.label;
      }
    }
  }
  return null;
}

/**
 * Each year's figure as a percentage of the largest, for the hairline gauge
 * under the taxable column — presentation only, so a float is acceptable.
 * An unstated year has no gauge.
 */
export function gaugeShares(values: (string | null)[]): (number | null)[] {
  const largest = Math.max(0, ...values.map((value) => (value === null ? 0 : Number(value))));
  return values.map((value) => {
    if (value === null) {
      return null;
    }
    return largest === 0 ? 0 : Math.round((Number(value) / largest) * 100);
  });
}

export function MultiYearOverviewPage() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["multi-year-overview"],
    queryFn: fetchMultiYearOverview,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Tax"
        title="Multi-year overview"
        description="Every Tax Year under each regime, as the ledger stands now — so a carryforward or a trend is read across the years rather than dug out of single reports."
      />

      {error ? (
        <ErrorState
          title="The overview could not be loaded"
          detail="The API did not answer with the years."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <p role="status" className="microlabel text-muted-foreground">
          computing every year from the ledger
        </p>
      ) : data.years.length === 0 ? (
        <EmptyState
          icon={CalendarRange}
          title="No Tax Year has anything in it yet"
          description="A row appears for every year from the ledger's first Transaction onward — record Transactions or run an import first."
          action={
            <Link to="/imports" className="text-sm underline underline-offset-2">
              Go to Imports
            </Link>
          }
        />
      ) : (
        <>
          <BlockedYears years={blockedYears(data.years)} />
          {REGIMES.map((regime, index) => (
            <RegimeSection key={regime.key} regime={regime} years={data.years} index={index} />
          ))}
          <Reports years={data.years} />
        </>
      )}
    </div>
  );
}

/**
 * Every blocked year with each reason and the screen that fixes it. Stated
 * once, above the tables, because a blocker belongs to the year rather than
 * to one regime; each table's row points back here.
 */
function BlockedYears({ years }: { years: OverviewYear[] }) {
  if (years.length === 0) {
    return null;
  }
  return (
    <section aria-label="Blocked years" className="rise space-y-2.5">
      {years.map((year) => (
        <aside
          key={year.year}
          id={`blocked-${year.year}`}
          className="flex scroll-mt-20 gap-2.5 rounded-lg border border-border p-3.5 text-sm"
        >
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-caution" />
          <div className="min-w-0 space-y-2">
            <p>
              <span className="font-mono tabular-nums">{year.year}</span> is blocked
              <span className="text-muted-foreground">
                {" "}
                — whatever it states is provisional until this is settled.
              </span>
            </p>
            <ul className="space-y-1.5">
              {year.blockers.map((blocker) => (
                <li key={`${blocker.kind}:${blocker.detail}`} className="text-muted-foreground">
                  {blocker.detail} <ResolveLink path={blocker.resolve_path} />
                </li>
              ))}
            </ul>
          </div>
        </aside>
      ))}
    </section>
  );
}

function ResolveLink({ path }: { path: string }) {
  const label = resolveLabel(path);
  if (label === null) {
    return null;
  }
  return (
    <Link to={path} className="whitespace-nowrap text-foreground underline underline-offset-2">
      Open {label}
    </Link>
  );
}

/**
 * The newest report of each Tax Year — the listing arrives newest first, so
 * the first one met for a year is that year's latest.
 */
export function latestReports(reports: ReportSummary[]): Map<number, ReportSummary> {
  const latest = new Map<number, ReportSummary>();
  for (const report of reports) {
    if (!latest.has(report.year)) {
      latest.set(report.year, report);
    }
  }
  return latest;
}

/** A report's lifecycle in words; staleness outranks draft or final. */
export function describeReport(report: Pick<ReportSummary, "status" | "stale">): string {
  if (report.stale) {
    return report.status === "final" ? "Final — stale" : "Draft — stale";
  }
  return report.status === "final" ? "Final" : "Draft";
}

/**
 * Where a year's figures are frozen into a report: the figures above are the
 * ledger as it stands now and move with it; a report is what was stated on
 * the day it was generated, with its appendix to download.
 */
function Reports({ years }: { years: OverviewYear[] }) {
  const queryClient = useQueryClient();
  const reports = useQuery({ queryKey: ["reports"], queryFn: fetchReports });
  const generate = useMutation({
    mutationFn: generateReport,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["reports"] }),
        queryClient.invalidateQueries({ queryKey: ["first-run-checklist"] }),
      ]),
  });
  const latest = latestReports(reports.data ?? []);

  return (
    <section
      aria-labelledby="reports"
      className="rise space-y-4"
      style={{ animationDelay: `${120 + REGIMES.length * 90}ms` }}
    >
      <div>
        <p className="microlabel text-muted-foreground">Frozen figures</p>
        <h2 id="reports" className="mt-1 text-lg font-medium">
          Reports
        </h2>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">
          The tables above move with the ledger. Generating a report freezes a Tax Year&apos;s
          figures as a draft, with every figure&apos;s working in its appendix; generating again
          adds a new report and leaves the earlier one as it was.
        </p>
      </div>
      {reports.error && (
        <ErrorState
          title="The reports could not be loaded"
          detail="The API did not answer with the reports generated so far. A new one can still be generated below."
          onRetry={() => void reports.refetch()}
        />
      )}
      {generate.error && (
        <p role="alert" className="text-sm text-alarm">
          {generate.error.message}
        </p>
      )}
      {generate.isSuccess && (
        <p role="status" className="text-sm text-signal">
          The {generate.variables} report was generated as a draft.
        </p>
      )}
      <ul className="divide-y divide-border border-y border-border">
        {years.map((year) => {
          const report = latest.get(year.year);
          return (
            <li
              key={year.year}
              aria-label={`${year.year} report`}
              className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3 text-sm"
            >
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="font-mono tabular-nums">{year.year}</span>
                {report ? (
                  <span className="text-muted-foreground">
                    <span className={report.stale ? "text-caution" : "text-foreground"}>
                      {describeReport(report)}
                    </span>
                    , generated{" "}
                    <span className="font-mono tabular-nums">
                      {formatTimestamp(Date.parse(report.generated_at))}
                    </span>
                    {report.stale && " — the ledger has changed since; generate again"}
                  </span>
                ) : (
                  <span className="text-muted-foreground">
                    No report yet — generate one to freeze this year&apos;s figures.
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                {report && (
                  <>
                    <a
                      href={appendixUrl(report.id, "pdf")}
                      className="underline underline-offset-2"
                    >
                      Appendix PDF
                    </a>
                    <a
                      href={appendixUrl(report.id, "csv")}
                      className="underline underline-offset-2"
                    >
                      CSV
                    </a>
                  </>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={generate.isPending}
                  onClick={() => generate.mutate(year.year)}
                >
                  {generate.isPending && generate.variables === year.year
                    ? "Generating…"
                    : report
                      ? "Generate again"
                      : "Generate report"}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function RegimeSection({
  regime,
  years,
  index,
}: {
  regime: Regime;
  years: OverviewYear[];
  index: number;
}) {
  const headingId = `regime-${regime.key}`;
  const shares = gaugeShares(years.map((year) => year[regime.key]?.taxable_eur ?? null));
  return (
    <section
      aria-labelledby={headingId}
      className="rise space-y-4"
      style={{ animationDelay: `${120 + index * 90}ms` }}
    >
      <div>
        <p className="microlabel text-muted-foreground">{regime.statute}</p>
        <h2 id={headingId} className="mt-1 text-lg font-medium">
          {regime.title}
        </h2>
        <p className="mt-1 max-w-xl text-sm text-muted-foreground">{regime.about}</p>
      </div>
      <div className="overflow-x-auto pr-0.5">
        <table className="w-full border-collapse whitespace-nowrap text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
                Year
              </th>
              {["Gross", "Offsets", regime.allowance, "Taxable", "Tax"].map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="microlabel py-2.5 pl-4 text-right text-muted-foreground"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map((year, row) => (
              <RegimeRow
                key={year.year}
                year={year}
                figures={year[regime.key]}
                share={shares[row] ?? null}
              />
            ))}
          </tbody>
        </table>
      </div>
      {regime.key === "capital_income" && <Carryforwards years={years} />}
    </section>
  );
}

function RegimeRow({
  year,
  figures,
  share,
}: {
  year: OverviewYear;
  figures: RegimeYear | null;
  share: number | null;
}) {
  const blocked = year.blockers.length > 0;
  return (
    <tr className="border-b border-border align-top">
      <th scope="row" className="py-3 pr-4 text-left font-normal">
        <span className="font-mono tabular-nums">{year.year}</span>
        {blocked && (
          <a
            href={`#blocked-${year.year}`}
            className="microlabel mt-1 flex items-center gap-1.5 text-caution"
          >
            <Lamp tone="caution" size="sm" pulsing={false} />
            blocked
          </a>
        )}
      </th>
      {figures === null ? (
        <td colSpan={5} className="microlabel py-3 pl-4 text-right text-caution">
          not stated — see what blocks {year.year}
        </td>
      ) : (
        <>
          <Figure value={figures.gross_eur} />
          <Figure value={figures.offsets_eur} />
          <td className="py-3 pl-4 text-right font-mono tabular-nums">
            {formatEur(figures.allowance_eur)}
            <span className="microlabel block text-muted-foreground">
              of {formatEur(figures.allowance_limit_eur)}
            </span>
          </td>
          <td className="py-3 pl-4 text-right font-mono tabular-nums">
            {formatEur(figures.taxable_eur)}
            {/* The trend at a glance: this year's taxable amount against the largest. */}
            <span aria-hidden className="mt-1.5 flex h-px justify-end bg-border">
              <span className="h-px bg-foreground" style={{ width: `${share ?? 0}%` }} />
            </span>
          </td>
          <td className="py-3 pl-4 text-right font-mono tabular-nums">
            {figures.tax_eur !== null ? (
              formatEur(figures.tax_eur)
            ) : (
              <span className="microlabel text-muted-foreground" title={PERSONAL_RATE_TITLE}>
                personal rate
              </span>
            )}
          </td>
        </>
      )}
    </tr>
  );
}

function Figure({ value }: { value: string }) {
  return (
    <td
      className={`py-3 pl-4 text-right font-mono tabular-nums ${
        isZero(value) ? "text-muted-foreground" : ""
      }`}
    >
      {formatEur(value)}
    </td>
  );
}

/**
 * The loss carryforward per Verlustverrechnungstopf and year: what the pot
 * walked in with, what the year consumed and from which year, what the
 * year's own loss added, and what walks on. Never summed across pots.
 */
function Carryforwards({ years }: { years: OverviewYear[] }) {
  const rows = carryforwardRows(years);
  return (
    <div className="space-y-3 pt-2">
      <h3 className="microlabel text-muted-foreground">Loss carryforward by pot</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No pot carries a loss into or out of any year shown.
        </p>
      ) : (
        <div className="overflow-x-auto pr-0.5">
          <table className="w-full border-collapse whitespace-nowrap text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
                  Year
                </th>
                <th scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
                  Pot
                </th>
                {["In", "Consumed", "Produced", "Out"].map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="microlabel py-2.5 pl-4 text-right text-muted-foreground"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ year, pot }) => (
                <tr key={`${year}:${pot.category}`} className="border-b border-border align-top">
                  <th scope="row" className="py-3 pr-4 text-left font-mono font-normal tabular-nums">
                    {year}
                  </th>
                  <td className="py-3 pr-4">{POT_LABEL[pot.category]}</td>
                  <Layered total={pot.carryforward_in_eur} layers={pot.carryforward_in} />
                  <Layered total={pot.consumed_eur} layers={pot.consumed} />
                  <Figure value={pot.produced_eur} />
                  <Layered total={pot.carryforward_out_eur} layers={pot.carryforward_out} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** A carryforward total with the slices it is made of, each naming its origin. */
function Layered({ total, layers }: { total: string; layers: CarryforwardLayer[] }) {
  return (
    <td
      className={`py-3 pl-4 text-right font-mono tabular-nums ${
        isZero(total) ? "text-muted-foreground" : ""
      }`}
    >
      {formatEur(total)}
      {layers.map((layer) => (
        <span
          key={`${layer.origin_year}:${layer.opening}`}
          className={`microlabel block ${layer.opening ? "text-signal" : "text-muted-foreground"}`}
          title={
            layer.opening
              ? `Entered for ${layer.origin_year} from an assessment predating the ledger.`
              : undefined
          }
        >
          {layers.length > 1 && `${formatEur(layer.amount_eur)} `}
          {describeOrigin(layer)}
        </span>
      ))}
    </td>
  );
}
