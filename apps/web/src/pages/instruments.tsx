import { useQuery } from "@tanstack/react-query";
import { Shapes } from "lucide-react";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import {
  fetchCryptoPrices,
  type PricedInstrument,
  type ProviderCondition,
} from "@/api/prices";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { formatMoneyExact, formatTimestamp } from "@/lib/format";

/** The attributes identity is read from — an Instrument row and an inbox item alike. */
export interface InstrumentIdentity {
  family: Instrument["family"];
  symbol: string;
  chain: string | null;
  contract_address: string | null;
  isin: string | null;
}

/**
 * The one line that tells two same-symbol rows apart: the family's identifying
 * attributes, never the symbol. A token is its chain and contract, a native
 * coin its chain, a security its ISIN, cash its currency code.
 */
export function identityOf(instrument: InstrumentIdentity): string {
  if (instrument.contract_address) {
    return `${instrument.chain} · ${abbreviate(instrument.contract_address)}`;
  }
  if (instrument.family === "crypto") {
    return `${instrument.chain} · native`;
  }
  return instrument.isin ?? instrument.symbol;
}

/** Symbols displayed by more than one Instrument — legitimate, and worth a flag. */
export function sharedSymbols(instruments: Instrument[]): Set<string> {
  const seen = new Set<string>();
  const shared = new Set<string>();
  for (const { symbol } of instruments) {
    (seen.has(symbol) ? shared : seen).add(symbol);
  }
  return shared;
}

function abbreviate(contractAddress: string): string {
  return `${contractAddress.slice(0, 6)}…${contractAddress.slice(-4)}`;
}

/**
 * The warning an ignored or dangerous position wears — visible, never hidden
 * (ADR-0012). Dangerous is global and outranks everything; ignored warns as
 * long as any Account ignores the Instrument. A kept holding needs no flag.
 */
export function stanceWarning(instrument: Instrument): "dangerous" | "ignored" | null {
  if (instrument.dangerous) {
    return "dangerous";
  }
  if (instrument.stances.some(({ stance }) => stance === "ignored")) {
    return "ignored";
  }
  return null;
}

const STANCE_WARNING_TITLE: Record<"dangerous" | "ignored", string> = {
  dangerous:
    "Marked dangerous everywhere — the position stays visible, but it mints no lot and can never acquire a price source.",
  ignored:
    "Ignored where it arrived — the position stays visible, but it mints no lot there, and while ignored wherever it appears the Instrument can never acquire a price source.",
};

const FAMILY_LABEL: Record<Instrument["family"], string> = {
  crypto: "Crypto",
  security: "Security",
  cash: "Cash",
};

/**
 * One line naming each failing provider and what its failure actually was —
 * a rate limit is its own condition, never conflated with an outage. Null
 * when every provider answered.
 */
export function conditionLine(conditions: ProviderCondition[]): string | null {
  if (conditions.length === 0) {
    return null;
  }
  return conditions
    .map(
      ({ provider, condition }) =>
        `${provider} ${condition === "rate_limited" ? "rate-limited" : "outage"}`,
    )
    .join(" · ");
}

/**
 * What a stale price's label explains on demand: whose answer is being
 * served, and from when — so a stale figure is never mistaken for current.
 */
export function staleExplanation(entry: PricedInstrument, locale?: string): string {
  const age =
    entry.as_of === null ? "an unknown time" : formatTimestamp(Date.parse(entry.as_of), locale);
  return `Every provider failed just now — this is the last known price, from ${entry.source} at ${age}.`;
}

export function InstrumentsPage() {
  const { data, error, refetch } = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });
  // Prices arrive separately: the provider chain may be slow or down, and the
  // instrument list must not wait on it — a failed report leaves the table
  // standing with its price column honestly empty.
  const prices = useQuery({ queryKey: ["crypto-prices"], queryFn: fetchCryptoPrices });
  const conditions = conditionLine(prices.data?.conditions ?? []);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Instruments"
        description="Everything tradable, one concept: crypto keyed on chain and contract, securities on ISIN, cash by currency. A symbol is only a label."
      />

      {error ? (
        <ErrorState
          title="The instruments could not be loaded"
          detail="The API did not answer with the instrument list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          icon={Shapes}
          title="No Instruments yet"
          description="Instruments appear here as imports and later tickets create them — nothing has minted one so far."
        />
      ) : data ? (
        <div className="space-y-3">
          {prices.error != null && (
            <ErrorState
              title="The crypto price report could not be loaded"
              detail="The API did not answer with prices, so the Price column below is empty — not zero, and not a statement about value."
              onRetry={() => void prices.refetch()}
            />
          )}
          {conditions && (
            <p className="microlabel text-caution">
              price providers: {conditions} — stale prices below are last known, with their age
            </p>
          )}
          <InstrumentTable instruments={data} prices={prices.data?.prices ?? []} />
        </div>
      ) : null}
    </div>
  );
}

function InstrumentTable({
  instruments,
  prices,
}: {
  instruments: Instrument[];
  prices: PricedInstrument[];
}) {
  const shared = sharedSymbols(instruments);
  const priceOf = new Map(prices.map((entry) => [entry.instrument_id, entry]));

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
          {["Symbol", "Name", "Family", "Identity", "Price", "Listings"].map((column) => (
            <th key={column} scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {instruments.map((instrument, index) => {
          const warning = stanceWarning(instrument);
          return (
          <tr
            key={instrument.id}
            className="rise border-b border-border"
            style={{ animationDelay: `${120 + index * 40}ms` }}
          >
            <td className="py-3 pr-4 font-mono tabular-nums">
              {instrument.symbol}
              {instrument.is_numeraire && (
                <span
                  className="microlabel ml-2 text-signal"
                  title="The currency every taxable figure is expressed in — moving it is not a disposal."
                >
                  numéraire
                </span>
              )}
              {shared.has(instrument.symbol) && (
                // Two Instruments legitimately share this label; the identity
                // column is what tells them apart.
                <span className="microlabel ml-2 text-caution">shared</span>
              )}
              {warning && (
                <span
                  className={`microlabel ml-2 ${
                    warning === "dangerous" ? "text-alarm" : "text-caution"
                  }`}
                  title={STANCE_WARNING_TITLE[warning]}
                >
                  {warning}
                </span>
              )}
            </td>
            <td className="py-3 pr-4">{instrument.name}</td>
            <td className="py-3 pr-4 text-muted-foreground">
              {FAMILY_LABEL[instrument.family]} · {instrument.type}
            </td>
            <td
              className="py-3 pr-4 font-mono tabular-nums"
              title={instrument.contract_address ?? undefined}
            >
              {identityOf(instrument)}
            </td>
            <td className="py-3 pr-4 font-mono tabular-nums">
              <PriceCell entry={priceOf.get(instrument.id)} />
            </td>
            <td className="py-3 font-mono tabular-nums text-muted-foreground">
              {instrument.listings.length === 0
                ? "—"
                : instrument.listings
                    .map((listing) => `${listing.venue} · ${listing.quote_currency}`)
                    .join(", ")}
            </td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * The EUR price the chain answered (ticket 18). A stale figure wears its
 * label and explains its source and age; an Instrument nothing has ever
 * priced says "unpriced" — never a zero. Instruments the chain does not
 * price at all — securities (ticket 45), cash and stablecoins (valued by
 * reference rate) — stay a quiet dash.
 */
function PriceCell({ entry }: { entry: PricedInstrument | undefined }) {
  if (!entry) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (entry.status === "unpriced") {
    return (
      <span
        className="microlabel text-caution"
        title="No provider prices this Instrument and no price was ever known — an unknown value, not zero."
      >
        unpriced
      </span>
    );
  }
  return (
    <>
      {entry.price_eur !== null && formatMoneyExact(entry.price_eur, "EUR")}
      {entry.status === "stale" && (
        <span className="microlabel ml-2 text-caution" title={staleExplanation(entry)}>
          stale
        </span>
      )}
    </>
  );
}
