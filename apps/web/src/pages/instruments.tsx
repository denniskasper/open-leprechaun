import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search, Shapes } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import {
  addDeployment,
  fetchInstruments,
  removeInstrument,
  type Instrument,
  type Listing,
} from "@/api/instruments";
import {
  fetchCryptoPrices,
  fetchSecurityPrices,
  type PricedInstrument,
  type ProviderCondition,
} from "@/api/prices";
import {
  choosePriceSource,
  classifyFund,
  createListing,
  createSecurity,
  editSecurity,
  removeListing,
  resolveListings,
  reviewSecurity,
  searchSecurities,
  type AdminClassification,
  type Candidate,
  type CategorySource,
  type DistributionPolicy,
  type FundCategory,
  type NewSecurity,
  type ResolvedListing,
} from "@/api/securities";
import { fetchFundRedemptionValues } from "@/api/statutory";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Price } from "@/components/patterns/figure";
import { RemoveButtons, useRemoval } from "@/components/patterns/removal";
import { Cell, DetailRow, Heading, Table } from "@/components/patterns/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatQuantity, formatTimestamp } from "@/lib/format";
import { AddInstrumentPanel, requestedKind } from "./add-instrument";

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

/** The chains a token is deployed on beyond the home one it is shown under (ADR-0032). */
export function otherChains(
  instrument: Pick<Instrument, "deployments">,
): string[] {
  return instrument.deployments.slice(1).map((deployment) => deployment.chain);
}

/**
 * The tokens an unfamiliar one may be settled as a Deployment of: every other
 * token, those wearing its symbol first — the likeliest answer — then by
 * symbol. Never a coin, security or currency: only a token has Deployments.
 */
export function deploymentCandidates(
  self: { id: number; symbol: string },
  instruments: Instrument[],
): Instrument[] {
  const tokens = instruments.filter(
    (instrument) =>
      instrument.id !== self.id &&
      instrument.family === "crypto" &&
      instrument.type === "token",
  );
  const rank = (instrument: Instrument) =>
    instrument.symbol === self.symbol ? 0 : 1;
  return tokens.sort(
    (a, b) =>
      rank(a) - rank(b) || a.symbol.localeCompare(b.symbol) || a.id - b.id,
  );
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

/** The Teilfreistellung categories of §20 InvStG, in their domain spelling. */
export const CATEGORY_LABEL: Record<FundCategory, string> = {
  aktienfonds: "Aktienfonds",
  mischfonds: "Mischfonds",
  immobilienfonds: "Immobilienfonds",
  auslands_immobilienfonds: "Auslands-Immobilienfonds",
  sonstige: "Sonstige (no exemption)",
};

const POLICY_LABEL: Record<DistributionPolicy, string> = {
  distributing: "distributing",
  accumulating: "accumulating",
};

/** The security types that are investment funds under §20 InvStG. */
export const FUND_TYPES = ["etf", "fund"];

const SECURITY_TYPES = ["share", "etf", "fund", "bond", "certificate"];

export type ClassificationCell =
  | { kind: "not_applicable" }
  // An import-created security awaiting the Admin's review — its type, and
  // with it whether a classification is even due, is not yet settled.
  | { kind: "review" }
  | { kind: "unclassified" }
  | {
      kind: "classified";
      category: FundCategory;
      source: CategorySource;
      policy: DistributionPolicy | null;
    };

/**
 * What the Teilfreistellung column says for one row. Review outranks
 * everything: until the Admin settles what an auto-created security is,
 * nothing can say whether a classification is due.
 */
export function classificationCell(instrument: Instrument): ClassificationCell {
  if (instrument.family !== "security") {
    return { kind: "not_applicable" };
  }
  if (instrument.needs_review || instrument.type === "unknown") {
    return { kind: "review" };
  }
  if (!FUND_TYPES.includes(instrument.type)) {
    return { kind: "not_applicable" };
  }
  if (instrument.fund_category === null || instrument.fund_category_source === null) {
    return { kind: "unclassified" };
  }
  return {
    kind: "classified",
    category: instrument.fund_category,
    source: instrument.fund_category_source,
    policy: instrument.distribution_policy,
  };
}

/**
 * Whether a row offers the Edit action: a security already settled. A flagged
 * one is settled by its review instead; a coin or currency has no type, symbol
 * or name to correct here.
 */
export function editable(instrument: Instrument): boolean {
  return instrument.family === "security" && !instrument.needs_review;
}

/**
 * The classification an edit states: only one the Admin actually changed. The
 * selects open on what is stored, so sending them back unchanged would restamp
 * a provider's prefill as the Admin's own; and a category left unchosen stays
 * unstated, so a security newly typed a fund remains unclassified.
 */
export function editedClassification(
  instrument: Instrument,
  type: string,
  category: string,
  policy: string,
): AdminClassification | null {
  if (!FUND_TYPES.includes(type) || category === "") {
    return null;
  }
  const unchanged =
    category === (instrument.fund_category ?? "") &&
    policy === (instrument.distribution_policy ?? "");
  if (unchanged) {
    return null;
  }
  return {
    fund_category: category as FundCategory,
    distribution_policy: policy === "" ? null : (policy as DistributionPolicy),
  };
}

/**
 * What creating a picked candidate sends: ticker before WKN before ISIN as
 * the display symbol, the listing only where the provider named venue and
 * currency together, and the provider's classification prefill wearing its
 * `provider` source — the Admin's own edit later changes it to `admin`.
 */
export function securityPayload(candidate: Candidate): NewSecurity {
  const listed = candidate.venue !== null && candidate.currency !== null;
  return {
    isin: candidate.isin,
    name: candidate.name,
    symbol: candidate.ticker ?? candidate.wkn ?? candidate.isin,
    type: candidate.type,
    wkn: candidate.wkn,
    ticker: candidate.ticker,
    venue: listed ? candidate.venue : null,
    quote_currency: listed ? candidate.currency : null,
    classification:
      candidate.fund_category === null
        ? null
        : {
            fund_category: candidate.fund_category,
            fund_category_source: "provider",
            distribution_policy: candidate.distribution_policy,
          },
  };
}

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

/**
 * The resolved markets not already held as Listings — venue and currency
 * compared as a pair, so a second currency on a known venue still offers
 * itself. The venue compares case-insensitively, matching the pricing
 * provider's own rule (ADR-0021): a holder of "XETRA" must not be offered
 * "Xetra" as a near-duplicate.
 */
export function unheldListings(resolved: ResolvedListing[], held: Listing[]): ResolvedListing[] {
  const key = (venue: string, currency: string) => `${venue.toLowerCase()} ${currency}`;
  const known = new Set(held.map((listing) => key(listing.venue, listing.quote_currency)));
  return resolved.filter((listing) => !known.has(key(listing.venue, listing.quote_currency)));
}

/**
 * Why the first market on offer is the one to price by, or null where nothing
 * sets it apart. The API answers the markets best first — EUR before any
 * other currency, then the most traded over four weeks — so only the head of
 * the list can carry a reason, and only if the provider stated a volume.
 */
export function recommendation(offered: ResolvedListing[]): string | null {
  const best = offered[0];
  if (!best || best.traded_four_weeks === null) return null;
  return best.quote_currency === "EUR"
    ? "The most traded EUR market over the last four weeks: its daily closes rest on the most trades, and need no conversion."
    : "No EUR market is on offer, so this is the most traded market over the last four weeks; its closes are converted by the ECB reference rate.";
}

/** A four-week volume in whole units, for reading. */
export function tradedWords(traded: string, locale?: string): string {
  return `${formatQuantity(traded.split(".")[0]!, locale)} traded in 4 weeks`;
}

/** "a", "a and b", "a, b and c". */
function listed(parts: string[]): string {
  return parts.length === 1 ? parts[0]! : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

/**
 * What the row says before a removal is confirmed (issue 9): what the Admin
 * declared about the Instrument that goes with it — its Stance, its Listings,
 * a fund's redemption values by year. `redemptionYears` is null when they
 * could not be looked up, so the warning stands without the years. Null when
 * nothing declared would go; stored prices go too, but nobody typed those in.
 */
export function whatGoesWith(
  instrument: Instrument,
  redemptionYears: number[] | null,
): string | null {
  const parts: string[] = [];
  const decisions = instrument.stances.length + (instrument.dangerous ? 1 : 0);
  if (decisions > 0) {
    parts.push(decisions === 1 ? "its Stance" : "its Stances");
  }
  if (instrument.listings.length > 0) {
    const markets = instrument.listings.map(
      (listing) => `${listing.venue} (${listing.quote_currency})`,
    );
    parts.push(`its ${markets.length === 1 ? "Listing" : "Listings"} on ${listed(markets)}`);
  }
  if (redemptionYears === null) {
    parts.push("any redemption values entered for it");
  } else if (redemptionYears.length > 0) {
    const years = [...redemptionYears].sort((a, b) => a - b).map(String);
    parts.push(`its redemption values for ${listed(years)}`);
  }
  return parts.length === 0 ? null : `Removing it also removes ${listed(parts)}.`;
}

export function InstrumentsPage() {
  const { data, error, refetch } = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });
  // Prices arrive separately: the providers may be slow or down, and the
  // instrument list must not wait on them — a failed report leaves the table
  // standing with its price column honestly empty.
  const prices = useQuery({ queryKey: ["crypto-prices"], queryFn: fetchCryptoPrices });
  const securityPrices = useQuery({
    queryKey: ["security-prices"],
    queryFn: fetchSecurityPrices,
  });
  const conditions = conditionLine([
    ...(prices.data?.conditions ?? []),
    ...(securityPrices.data?.conditions ?? []),
  ]);
  // A refused sync sends the Admin here with the symbol it could not resolve
  // (`?add=USD&kind=cash`), so the form opens already knowing what is being
  // added, and on the kind that will answer to it.
  const [search, setSearch] = useSearchParams();
  const requested = search.get("add");
  const [adding, setAdding] = useState<"security" | "coin" | null>(
    requested === null ? null : "coin",
  );
  const toggle = (panel: "security" | "coin") =>
    setAdding((open) => (open === panel ? null : panel));
  const closeCoin = () => {
    setAdding(null);
    if (requested !== null) setSearch({}, { replace: true });
  };

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Instruments"
        description="Everything tradable, one concept: crypto keyed on chain and contract, securities on ISIN, cash by currency. A symbol is only a label."
        actions={
          <>
            <Button variant="outline" onClick={() => toggle("coin")}>
              <Plus aria-hidden />
              Add coin or currency
            </Button>
            <Button onClick={() => toggle("security")}>
              <Plus aria-hidden />
              Add security
            </Button>
          </>
        }
      />

      {adding === "security" && <AddSecurityPanel onDone={() => setAdding(null)} />}
      {adding === "coin" && (
        <AddInstrumentPanel
          instruments={data ?? []}
          symbol={requested ?? ""}
          kind={requestedKind(search.get("kind"))}
          onDone={closeCoin}
        />
      )}

      {error ? (
        <ErrorState
          title="The instruments could not be loaded"
          detail="The API did not answer with the instrument list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 && adding === null ? (
        <EmptyState
          icon={Shapes}
          title="No Instruments yet"
          description="Add a share or fund by searching its ISIN, WKN, ticker or name, add a coin or currency by hand — or let imports mint Instruments as they arrive."
          action={
            <Button variant="outline" onClick={() => setAdding("security")}>
              <Plus aria-hidden />
              Add the first security
            </Button>
          }
        />
      ) : data && data.length > 0 ? (
        <div className="space-y-3">
          {prices.error != null && (
            <ErrorState
              title="The crypto price report could not be loaded"
              detail="The API did not answer with prices, so the Price column below is empty — not zero, and not a statement about value."
              onRetry={() => void prices.refetch()}
            />
          )}
          {securityPrices.error != null && (
            <ErrorState
              title="The security price report could not be loaded"
              detail="The API did not answer with security prices, so those rows show no price — not zero, and not a statement about value."
              onRetry={() => void securityPrices.refetch()}
            />
          )}
          {conditions && (
            <p className="microlabel measure-prose text-caution">
              price providers: {conditions} — stale prices below are last known, with their age
            </p>
          )}
          <InstrumentTable
            instruments={data}
            prices={[...(prices.data?.prices ?? []), ...(securityPrices.data?.prices ?? [])]}
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * The add-security flow: one query — ISIN, WKN, ticker or name alike —
 * answered with provider candidates ready to pick, and a by-hand form for
 * what no provider covers.
 */
function AddSecurityPanel({ onDone }: { onDone: () => void }) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [manual, setManual] = useState(false);
  const search = useMutation({ mutationFn: searchSecurities });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length >= 2) search.mutate(query.trim());
  };

  return (
    <section
      className="rise measure-form rounded-xl border border-border p-5"
      aria-label="Add security"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="microlabel text-muted-foreground">New security</p>
        <Button variant="ghost" size="sm" onClick={() => setManual((byHand) => !byHand)}>
          {manual ? "Back to search" : "No provider coverage? Create by hand"}
        </Button>
      </div>

      {manual ? (
        <ManualSecurityForm onDone={onDone} />
      ) : (
        <>
          <form onSubmit={submit} className="mt-4 flex gap-2">
            <label htmlFor={`${id}-query`} className="sr-only">
              Search securities
            </label>
            <Input
              id={`${id}-query`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="IE00B4L5Y983 · A0RPWH · EUNL · MSCI World"
              className="font-mono"
              autoFocus
            />
            <Button type="submit" disabled={search.isPending || query.trim().length < 2}>
              <Search aria-hidden />
              Search
            </Button>
          </form>
          <p className="microlabel mt-2 text-muted-foreground">
            ISIN · WKN · ticker · name — candidates from onvista
          </p>

          {search.error != null && (
            <p role="alert" className="mt-3 text-sm text-alarm">{search.error.message}</p>
          )}
          {search.data && search.data.length === 0 && (
            <p className="mt-3 text-sm text-muted-foreground">
              The provider knows nothing matching — create the security by hand and it stays
              unpriced rather than valued at zero.
            </p>
          )}
          {search.data && search.data.length > 0 && (
            <ul className="mt-4 divide-y divide-border border-t border-border">
              {search.data.map((candidate) => (
                <CandidateRow key={candidate.isin} candidate={candidate} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function CandidateRow({ candidate }: { candidate: Candidate }) {
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: () => createSecurity(securityPayload(candidate)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["instruments"] }),
  });
  const known = candidate.instrument_id !== null || add.isSuccess;
  const listing =
    candidate.venue !== null && candidate.currency !== null
      ? `${candidate.venue} · ${candidate.currency}`
      : null;
  const prefill =
    candidate.fund_category !== null
      ? [
          CATEGORY_LABEL[candidate.fund_category],
          candidate.distribution_policy !== null
            ? POLICY_LABEL[candidate.distribution_policy]
            : null,
        ]
          .filter((part) => part !== null)
          .join(" · ")
      : null;

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
      <span className="font-mono text-sm tabular-nums">{candidate.isin}</span>
      <span className="font-mono text-xs tabular-nums text-muted-foreground">
        {[candidate.wkn, candidate.ticker].filter(Boolean).join(" · ") || "—"}
      </span>
      <span className="min-w-40 flex-1 text-sm">{candidate.name}</span>
      <span className="text-xs text-muted-foreground">
        {candidate.type}
        {listing && ` · ${listing}`}
      </span>
      {prefill && (
        <span
          className="microlabel text-signal"
          title="The provider's Teilfreistellung prefill — recorded with source “provider”, always overridable."
        >
          {prefill}
        </span>
      )}
      {add.error != null && (
        <span role="alert" className="text-sm text-alarm">
          {add.error.message}
        </span>
      )}
      {known ? (
        <span className="microlabel text-muted-foreground">in the ledger</span>
      ) : (
        <Button variant="outline" size="sm" onClick={() => add.mutate()} disabled={add.isPending}>
          Add
        </Button>
      )}
    </li>
  );
}

function ManualSecurityForm({ onDone }: { onDone: () => void }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [isin, setIsin] = useState("");
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [type, setType] = useState("share");
  const [venue, setVenue] = useState("");
  const [currency, setCurrency] = useState("");
  const [category, setCategory] = useState("");
  const [policy, setPolicy] = useState("");
  const fund = FUND_TYPES.includes(type);

  const create = useMutation({
    mutationFn: () =>
      createSecurity({
        isin: isin.trim(),
        name: name.trim(),
        symbol: ticker.trim() || isin.trim(),
        type,
        ticker: ticker.trim() || null,
        venue: venue.trim() || null,
        quote_currency: currency.trim() || null,
        classification:
          fund && category !== ""
            ? {
                fund_category: category as FundCategory,
                fund_category_source: "admin",
                distribution_policy: policy === "" ? null : (policy as DistributionPolicy),
              }
            : null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
      onDone();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  const listingHalf = (venue.trim() === "") !== (currency.trim() === "");

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <div className="grid gap-4 @lg:grid-cols-2">
        <div className="space-y-1.5">
          <label htmlFor={`${id}-isin`} className="microlabel block text-muted-foreground">
            ISIN
          </label>
          <Input
            id={`${id}-isin`}
            value={isin}
            onChange={(event) => setIsin(event.target.value.toUpperCase())}
            className="font-mono"
            required
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-name`} className="microlabel block text-muted-foreground">
            Name
          </label>
          <Input
            id={`${id}-name`}
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-ticker`} className="microlabel block text-muted-foreground">
            Ticker (optional)
          </label>
          <Input
            id={`${id}-ticker`}
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
            className="font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-type`} className="microlabel block text-muted-foreground">
            Type
          </label>
          <NativeSelect
            id={`${id}-type`}
            value={type}
            onChange={(event) => setType(event.target.value)}
            className="w-full"
          >
            {SECURITY_TYPES.map((securityType) => (
              <option key={securityType} value={securityType}>
                {securityType}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-venue`} className="microlabel block text-muted-foreground">
            Listing venue (optional)
          </label>
          <Input
            id={`${id}-venue`}
            value={venue}
            onChange={(event) => setVenue(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-currency`} className="microlabel block text-muted-foreground">
            Listing currency (optional)
          </label>
          <Input
            id={`${id}-currency`}
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            className="font-mono"
          />
        </div>
        {fund && (
          <ClassificationSelects
            id={id}
            category={category}
            policy={policy}
            onCategory={setCategory}
            onPolicy={setPolicy}
            className="w-full"
          />
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Without a provider nothing can vouch for a value — the security is created unpriced,
        shown as an unknown value rather than zero.
      </p>
      {listingHalf && (
        <p className="text-sm text-caution">A Listing names its venue and currency together.</p>
      )}
      {create.error != null && (
        <p role="alert" className="text-sm text-alarm">
          {create.error.message}
        </p>
      )}
      <Button type="submit" disabled={create.isPending || listingHalf}>
        Create security
      </Button>
    </form>
  );
}

const INSTRUMENT_COLUMNS = [
  "Symbol",
  "Name",
  "Family",
  "Identity",
  "Teilfreistellung",
  "Price",
  "Listings",
];

// The data columns, and the trailing one each row's Remove stands in.
const COLUMN_COUNT = INSTRUMENT_COLUMNS.length + 1;

function InstrumentTable({
  instruments,
  prices,
}: {
  instruments: Instrument[];
  prices: PricedInstrument[];
}) {
  const shared = sharedSymbols(instruments);
  const priceOf = new Map(prices.map((entry) => [entry.instrument_id, entry]));
  const [editing, setEditing] = useState<{ id: number; editor: RowEditor } | null>(null);
  const [managing, setManaging] = useState<number | null>(null);

  return (
    <Table>
      <thead>
        <tr>
          {INSTRUMENT_COLUMNS.map((column) => (
            <Heading key={column} figure={column === "Price"}>
              {column}
            </Heading>
          ))}
          <Heading>
            <span className="sr-only">Remove</span>
          </Heading>
        </tr>
      </thead>
      <tbody>
        {instruments.map((instrument, index) => {
          const warning = stanceWarning(instrument);
          return (
            <InstrumentRow
              key={instrument.id}
              instrument={instrument}
              warning={warning}
              shared={shared.has(instrument.symbol)}
              entry={priceOf.get(instrument.id)}
              index={index}
              editing={editing?.id === instrument.id ? editing.editor : null}
              onEdit={(editor) => setEditing(editor ? { id: instrument.id, editor } : null)}
              managing={managing === instrument.id}
              onManage={(open) => setManaging(open ? instrument.id : null)}
            />
          );
        })}
      </tbody>
    </Table>
  );
}

function InstrumentRow({
  instrument,
  warning,
  shared,
  entry,
  index,
  editing,
  onEdit,
  managing,
  onManage,
}: {
  instrument: Instrument;
  warning: "dangerous" | "ignored" | null;
  shared: boolean;
  entry: PricedInstrument | undefined;
  index: number;
  editing: RowEditor | null;
  onEdit: (editor: RowEditor | null) => void;
  managing: boolean;
  onManage: (open: boolean) => void;
}) {
  const cell = classificationCell(instrument);
  const removal = useRemoval(() => removeInstrument(instrument.id), ["instruments"]);
  const goes = useWhatGoesWith(instrument, removal.confirming);
  // The row shows one thing at a time: a removal half asked for, or refused,
  // does not stand beside an editor opened after it — nor an open editor
  // beside a removal asked for after it.
  const opening = (open: (opened: boolean) => void) => (opened: boolean) => {
    if (opened) {
      removal.keep();
      removal.forget();
    }
    open(opened);
  };
  const classifying = (open: boolean) => onEdit(open ? "classification" : null);
  const correcting = (open: boolean) => onEdit(open ? "details" : null);
  const asking = {
    ...removal,
    ask: () => {
      if (editing) onEdit(null);
      if (managing) onManage(false);
      removal.ask();
    },
  };
  return (
    <>
      <tr className="rise" style={{ animationDelay: `${120 + index * 40}ms` }}>
        <Cell data>
          {instrument.symbol}
          {instrument.is_numeraire && (
            <span
              className="microlabel ml-2 text-signal"
              title="The currency every taxable figure is expressed in — moving it is not a disposal."
            >
              numéraire
            </span>
          )}
          {shared && (
            // Two Instruments legitimately share this label; the identity
            // column is what tells them apart.
            <span className="microlabel ml-2 text-caution">shared</span>
          )}
          {instrument.needs_review && (
            <span
              className="microlabel ml-2 text-caution"
              title="Auto-created by an import for an identifier the ledger did not know — review settles what it is."
            >
              review
            </span>
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
        </Cell>
        <Cell>{instrument.name}</Cell>
        <Cell className="text-muted-foreground">
          {FAMILY_LABEL[instrument.family]} · {instrument.type}
        </Cell>
        <Cell data title={instrument.contract_address ?? undefined}>
          <IdentitySummary
            instrument={instrument}
            managing={managing}
            onManage={opening(onManage)}
          />
        </Cell>
        <Cell>
          <ClassificationSummary
            cell={cell}
            // While the details editor is open the cell offers only to close
            // it — opening the classification would drop what was typed.
            editing={editing !== null}
            onEdit={opening(classifying)}
          />
        </Cell>
        <Cell figure>
          <PriceCell entry={entry} />
        </Cell>
        <Cell data className="text-muted-foreground">
          <ListingsSummary
            instrument={instrument}
            managing={managing}
            onManage={opening(onManage)}
          />
        </Cell>
        <Cell className="text-right whitespace-nowrap">
          {editable(instrument) && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-muted-foreground"
              aria-label={`Edit ${instrument.symbol} ${identityOf(instrument)}`}
              aria-expanded={editing === "details"}
              onClick={() => opening(correcting)(editing !== "details")}
            >
              <Pencil aria-hidden />
              {editing === "details" ? "Cancel" : "Edit"}
            </Button>
          )}
          <RemoveButtons
            removal={asking}
            name={`${instrument.symbol} ${identityOf(instrument)}`}
            className="h-7 px-2"
          />
        </Cell>
      </tr>
      {((removal.confirming && goes) || removal.refusal) && (
        <DetailRow columns={COLUMN_COUNT}>
          {removal.confirming && goes && (
            <p className="measure-prose text-sm text-muted-foreground">{goes}</p>
          )}
          {removal.refusal && (
            <p role="alert" className="measure-prose text-sm text-alarm">
              {removal.refusal}
            </p>
          )}
        </DetailRow>
      )}
      {editing === "classification" && cell.kind !== "not_applicable" && (
        <DetailRow columns={COLUMN_COUNT}>
          <SettleForm
            instrument={instrument}
            mode={cell.kind === "review" ? "review" : "classify"}
            onDone={() => onEdit(null)}
          />
        </DetailRow>
      )}
      {editing === "details" && (
        <DetailRow columns={COLUMN_COUNT}>
          <SettleForm instrument={instrument} mode="edit" onDone={() => onEdit(null)} />
        </DetailRow>
      )}
      {managing && instrument.family === "security" && (
        <DetailRow columns={COLUMN_COUNT}>
          <ListingsEditor instrument={instrument} />
        </DetailRow>
      )}
      {managing && instrument.type === "token" && (
        <DetailRow columns={COLUMN_COUNT}>
          <DeploymentsEditor instrument={instrument} />
        </DetailRow>
      )}
    </>
  );
}

/**
 * The sentence a row shows while its removal waits to be confirmed. A fund's
 * redemption values are looked up only then; until they answer the row says
 * nothing rather than leave a year out, and a failed lookup still warns.
 */
function useWhatGoesWith(instrument: Instrument, confirming: boolean): string | null {
  const fund = instrument.family === "security" && FUND_TYPES.includes(instrument.type);
  const redemption = useQuery({
    queryKey: ["fund-redemption-values"],
    queryFn: fetchFundRedemptionValues,
    enabled: confirming && fund,
  });
  if (!fund) {
    return whatGoesWith(instrument, []);
  }
  if (redemption.error) {
    return whatGoesWith(instrument, null);
  }
  if (!redemption.data) {
    return null;
  }
  const years = redemption.data.values
    .filter((value) => value.instrument_id === instrument.id)
    .map((value) => value.year);
  return whatGoesWith(instrument, years);
}

/**
 * The Identity cell. A token's opens its Deployments (ADR-0032) — the chains
 * beyond the home one named after it — the way a security's Listings cell
 * opens its markets; anything else is its identity, read only.
 */
function IdentitySummary({
  instrument,
  managing,
  onManage,
}: {
  instrument: Instrument;
  managing: boolean;
  onManage: (open: boolean) => void;
}) {
  if (instrument.type !== "token") {
    return <>{identityOf(instrument)}</>;
  }
  const others = otherChains(instrument);
  return (
    // A dotted underline marks the identity as the way into its Deployments.
    <button
      type="button"
      className="text-left underline decoration-muted-foreground/40 decoration-dotted underline-offset-4 hover:decoration-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      aria-expanded={managing}
      aria-label={`${managing ? "Close" : "Edit"} the Deployments of ${instrument.symbol} ${identityOf(instrument)}`}
      onClick={() => onManage(!managing)}
    >
      {identityOf(instrument)}
      {others.length > 0 && (
        <span className="text-muted-foreground"> + {others.join(", ")}</span>
      )}
    </button>
  );
}

/**
 * The inline Deployments editor: every chain's contract the token is, the
 * home one marked, and a by-hand form for another. The rule is said before
 * the control that acts on it — the ledger cannot tell a native contract from
 * a bridged one, so the Admin's word is the whole check.
 */
function DeploymentsEditor({ instrument }: { instrument: Instrument }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [chain, setChain] = useState("");
  const [contract, setContract] = useState("");
  const add = useMutation({
    mutationFn: () =>
      addDeployment(instrument.id, {
        chain: chain.trim().toLowerCase(),
        contract_address: contract.trim(),
      }),
    onSuccess: () => {
      setChain("");
      setContract("");
      return queryClient.invalidateQueries({ queryKey: ["instruments"] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };

  return (
    <div
      className="space-y-4"
      aria-label={`Deployments of ${instrument.symbol}`}
    >
      <ul className="space-y-1">
        {instrument.deployments.map((deployment, index) => (
          <li
            key={`${deployment.chain} ${deployment.contract_address}`}
            className="flex min-h-8 flex-wrap items-center gap-x-3"
          >
            <span className="w-24 text-sm">{deployment.chain}</span>
            <span className="font-mono text-sm break-all tabular-nums">
              {deployment.contract_address}
            </span>
            {index === 0 && (
              <span
                className="microlabel text-muted-foreground"
                title="The contract this token was added with — the one it is shown under and priced by."
              >
                home
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="measure-prose text-sm text-muted-foreground">
        Add a chain only where the issuer itself mints this token. A bridged or
        wrapped version is a claim on someone else and stays an Instrument of
        its own; swapping into it is a disposal.
      </p>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
        <div className="space-y-1.5">
          <label
            htmlFor={`${id}-chain`}
            className="microlabel block text-muted-foreground"
          >
            Chain
          </label>
          <Input
            id={`${id}-chain`}
            value={chain}
            onChange={(event) => setChain(event.target.value)}
            className="w-32"
          />
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <label
            htmlFor={`${id}-contract`}
            className="microlabel block text-muted-foreground"
          >
            Contract address
          </label>
          <Input
            id={`${id}-contract`}
            value={contract}
            onChange={(event) => setContract(event.target.value)}
            className="font-mono"
          />
        </div>
        <Button
          type="submit"
          variant="outline"
          disabled={
            add.isPending || chain.trim() === "" || contract.trim() === ""
          }
        >
          <Plus aria-hidden />
          {add.isPending ? "Adding…" : "Add deployment"}
        </Button>
      </form>
      {add.error != null && (
        <p role="alert" className="measure-prose text-sm text-alarm">
          {add.error.message}
        </p>
      )}
    </div>
  );
}

/**
 * The Listings cell: each market with the price source marked, opening the
 * editor for a security — a crypto or cash Instrument has no Listings to
 * manage, and stays a quiet dash.
 */
function ListingsSummary({
  instrument,
  managing,
  onManage,
}: {
  instrument: Instrument;
  managing: boolean;
  onManage: (open: boolean) => void;
}) {
  if (instrument.family !== "security") {
    return <>—</>;
  }
  if (managing) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="-my-1 -ml-2 h-7 px-2"
        aria-label={`Close the Listings of ${instrument.symbol}`}
        onClick={() => onManage(false)}
      >
        Close
      </Button>
    );
  }
  if (instrument.listings.length === 0) {
    return (
      <Button
        variant="outline"
        size="sm"
        className="-my-1 h-7 px-2"
        onClick={() => onManage(true)}
        title="Without a Listing nothing can vouch for a price — the security stays unpriced, never zero."
      >
        <span className="text-caution">Add listing</span>
      </Button>
    );
  }
  return (
    // A dotted underline marks the markets as the way into their editor.
    <button
      type="button"
      className="text-left underline decoration-muted-foreground/40 decoration-dotted underline-offset-4 hover:text-foreground hover:decoration-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      title="Add, remove or reprice this security's Listings"
      aria-label={`Edit the Listings of ${instrument.symbol}`}
      onClick={() => onManage(true)}
    >
      {instrument.listings.map((listing, index) => (
        <span key={listing.id}>
          {index > 0 && ", "}
          {listing.venue} · {listing.quote_currency}
          {listing.price_source && (
            <span
              className="microlabel ml-1.5 text-signal"
              title="This Listing's market prices the Instrument — quotes and daily closes come from here."
            >
              prices
            </span>
          )}
        </span>
      ))}
    </button>
  );
}

/**
 * One held market in the Listings editor: the price source marked or handed
 * over here, and the two-step Remove. The server refuses to remove the price
 * source while another Listing remains, and that refusal is shown in place.
 */
function HeldListing({
  instrument,
  listing,
  moving,
  onPrice,
}: {
  instrument: Instrument;
  listing: Listing;
  moving: boolean;
  onPrice: () => void;
}) {
  const removal = useRemoval(() => removeListing(instrument.id, listing.id), ["instruments"]);
  const name = `${listing.venue} ${listing.quote_currency}`;
  return (
    <li className="space-y-1">
      <div className="flex min-h-8 items-center gap-3">
        <span className="font-mono text-sm tabular-nums">
          {listing.venue} · {listing.quote_currency}
        </span>
        {listing.price_source ? (
          <span
            className="microlabel text-signal"
            title="This Listing's market prices the Instrument — quotes and daily closes come from here."
          >
            price source
          </span>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            onClick={onPrice}
            disabled={moving}
          >
            Use for pricing
          </Button>
        )}
        <RemoveButtons removal={removal} name={name} className="h-7 px-2" />
      </div>
      {removal.refusal && (
        <p role="alert" className="measure-prose text-sm text-alarm">
          {removal.refusal}
        </p>
      )}
    </li>
  );
}

/**
 * The inline Listings editor (ticket 45): the held markets with the price
 * source movable among them, the provider's resolved markets one click from
 * held, and a by-hand form for what no provider resolves.
 */
function ListingsEditor({ instrument }: { instrument: Instrument }) {
  const id = useId();
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["instruments"] });
    void queryClient.invalidateQueries({ queryKey: ["security-prices"] });
  };
  const [venue, setVenue] = useState("");
  const [currency, setCurrency] = useState("");
  const resolve = useMutation({
    mutationFn: () => resolveListings(instrument.isin ?? instrument.symbol),
  });
  const move = useMutation({
    mutationFn: (listingId: number) => choosePriceSource(instrument.id, listingId),
    onSuccess: refresh,
  });
  const add = useMutation({
    // The server gives a bare security's first Listing the price source, so
    // one market needs no second click to become priceable.
    mutationFn: (listing: { venue: string; quote_currency: string }) =>
      createListing(instrument.id, { ...listing, price_source: false }),
    onSuccess: refresh,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(
      { venue: venue.trim(), quote_currency: currency.trim().toUpperCase() },
      {
        onSuccess: () => {
          setVenue("");
          setCurrency("");
        },
      },
    );
  };
  const unheld = unheldListings(resolve.data ?? [], instrument.listings);
  // Only the overall best earns the mark: once it is held, the next one down
  // is merely what is left.
  const recommended = unheld[0] === resolve.data?.[0] ? recommendation(unheld) : null;

  return (
    <div className="space-y-4" aria-label={`Listings of ${instrument.symbol}`}>
      {instrument.listings.length > 0 && (
        <ul className="space-y-1">
          {instrument.listings.map((listing) => (
            <HeldListing
              key={listing.id}
              instrument={instrument}
              listing={listing}
              moving={move.isPending}
              onPrice={() => move.mutate(listing.id)}
            />
          ))}
        </ul>
      )}
      {move.error != null && (
        <p role="alert" className="text-sm text-alarm">
          {move.error.message}
        </p>
      )}

      <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
        <div className="space-y-1.5">
          <label htmlFor={`${id}-venue`} className="microlabel block text-muted-foreground">
            Venue
          </label>
          <Input
            id={`${id}-venue`}
            value={venue}
            onChange={(event) => setVenue(event.target.value)}
            className="w-44"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-currency`} className="microlabel block text-muted-foreground">
            Currency
          </label>
          <Input
            id={`${id}-currency`}
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            className="w-20 font-mono"
          />
        </div>
        <Button
          type="submit"
          variant="outline"
          disabled={add.isPending || venue.trim() === "" || currency.trim() === ""}
        >
          <Plus aria-hidden />
          Add by hand
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => resolve.mutate()}
          disabled={resolve.isPending}
          title="Ask the resolution provider which markets it knows for this identifier."
        >
          <Search aria-hidden />
          Fetch markets from provider
        </Button>
      </form>
      {add.error != null && (
        <p role="alert" className="text-sm text-alarm">
          {add.error.message}
        </p>
      )}
      {resolve.error != null && (
        <p role="alert" className="text-sm text-alarm">
          {resolve.error.message}
        </p>
      )}

      {resolve.data && resolve.data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          The provider knows no markets for this identifier — enter the Listing by hand.
        </p>
      )}
      {resolve.data && resolve.data.length > 0 && unheld.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Every market the provider knows is already held.
        </p>
      )}
      {unheld.length > 0 && (
        <ul className="divide-y divide-border border-t border-border">
          {unheld.map((listing, index) => (
            <li
              key={`${listing.venue} ${listing.quote_currency}`}
              className="flex items-center gap-4 py-2"
            >
              <span className="min-w-40 font-mono text-sm tabular-nums">
                {listing.venue} · {listing.quote_currency}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => add.mutate(listing)}
                disabled={add.isPending}
              >
                Add
              </Button>
              {index === 0 && recommended && (
                <span className="microlabel text-signal" title={recommended}>
                  recommended
                </span>
              )}
              {listing.traded_four_weeks !== null && (
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                  {tradedWords(listing.traded_four_weeks)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The Teilfreistellung cell: the value with its source, or the open action. */
function ClassificationSummary({
  cell,
  editing,
  onEdit,
}: {
  cell: ClassificationCell;
  editing: boolean;
  onEdit: (open: boolean) => void;
}) {
  if (cell.kind === "not_applicable") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (editing) {
    return (
      <Button variant="ghost" size="sm" onClick={() => onEdit(false)}>
        Cancel
      </Button>
    );
  }
  if (cell.kind === "review") {
    return (
      <Button variant="outline" size="sm" onClick={() => onEdit(true)}>
        Review
      </Button>
    );
  }
  if (cell.kind === "unclassified") {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => onEdit(true)}
        title="An unclassified fund blocks report finalisation — nothing silently assumes a zero exemption."
      >
        <span className="text-caution">Classify</span>
      </Button>
    );
  }
  return (
    <button type="button" className="group text-left" onClick={() => onEdit(true)}>
      {CATEGORY_LABEL[cell.category]}
      {cell.policy !== null && (
        <span className="text-muted-foreground"> · {POLICY_LABEL[cell.policy]}</span>
      )}
      <span
        className="microlabel ml-2 text-muted-foreground group-hover:text-foreground"
        title={
          cell.source === "provider"
            ? "Prefilled by the provider — click to override; your value is then recorded as the Admin's."
            : "Stated by the Admin — click to change."
        }
      >
        {cell.source}
      </span>
    </button>
  );
}

/**
 * Which inline editor a row has open: `classification` from the
 * Teilfreistellung cell (a review, or a fund's classification), `details`
 * from the row's Edit action.
 */
type RowEditor = "classification" | "details";

/** What the inline editor states: a review, a classification, or a correction. */
type SettleMode = "review" | "classify" | "edit";

/**
 * The one inline editor: classifying a fund; for an import-created security,
 * settling its review by choosing what it actually is; or correcting a
 * settled security's type, symbol and name.
 */
function SettleForm({
  instrument,
  mode,
  onDone,
}: {
  instrument: Instrument;
  mode: SettleMode;
  onDone: () => void;
}) {
  const review = mode === "review";
  const identifies = mode !== "classify";
  const id = useId();
  const queryClient = useQueryClient();
  const [type, setType] = useState(review ? "share" : instrument.type);
  const [symbol, setSymbol] = useState(instrument.symbol);
  const [name, setName] = useState(instrument.name);
  const [category, setCategory] = useState(instrument.fund_category ?? "");
  const [policy, setPolicy] = useState(instrument.distribution_policy ?? "");
  const fund = FUND_TYPES.includes(type);

  // The Admin's own act carries no source — the server stamps `admin`. An
  // edit states only what the Admin changed.
  const classification: AdminClassification | null =
    mode === "edit"
      ? editedClassification(instrument, type, category, policy)
      : fund && category !== ""
        ? {
            fund_category: category as FundCategory,
            distribution_policy: policy === "" ? null : (policy as DistributionPolicy),
          }
        : null;
  const settle = useMutation({
    mutationFn: () => {
      if (identifies) {
        const settled = { type, symbol: symbol.trim(), name: name.trim(), classification };
        return review ? reviewSecurity(instrument.id, settled) : editSecurity(instrument.id, settled);
      }
      if (classification === null) {
        // Unreachable while the button disables itself, and never a guess.
        return Promise.reject(new Error("Choose a Teilfreistellung category first."));
      }
      return classifyFund(instrument.id, classification);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
      onDone();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    settle.mutate();
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
      {identifies && (
        <>
          <div className="space-y-1.5">
            <label htmlFor={`${id}-type`} className="microlabel block text-muted-foreground">
              Type
            </label>
            <NativeSelect
              id={`${id}-type`}
              value={type}
              onChange={(event) => setType(event.target.value)}
            >
              {SECURITY_TYPES.map((securityType) => (
                <option key={securityType} value={securityType}>
                  {securityType}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <label htmlFor={`${id}-symbol`} className="microlabel block text-muted-foreground">
              Symbol
            </label>
            <Input
              id={`${id}-symbol`}
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              className="w-28 font-mono"
              required
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor={`${id}-name`} className="microlabel block text-muted-foreground">
              Name
            </label>
            <Input
              id={`${id}-name`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-64"
              required
            />
          </div>
        </>
      )}
      {(fund || !identifies) && (
        <ClassificationSelects
          id={id}
          category={category}
          policy={policy}
          onCategory={setCategory}
          onPolicy={setPolicy}
          // An edit never unstates a category — it would save one thing
          // while the select showed another.
          stated={mode === "edit" && instrument.fund_category !== null}
        />
      )}
      {mode === "edit" && fund && category === "" && (
        <p className="measure-prose basis-full text-sm text-caution">
          A fund without a Teilfreistellung category blocks finalising the tax report — choose one
          now or classify it later.
        </p>
      )}
      {settle.error != null && (
        <p role="alert" className="text-sm text-alarm">
          {settle.error.message}
        </p>
      )}
      <Button
        type="submit"
        disabled={settle.isPending || (mode === "classify" && classification === null)}
      >
        {SETTLE_LABEL[mode]}
      </Button>
    </form>
  );
}

const SETTLE_LABEL: Record<SettleMode, string> = {
  review: "Settle review",
  classify: "Save classification",
  edit: "Save changes",
};

/**
 * The two selects a classification is stated with, shared by the by-hand
 * form and the inline editor: the Teilfreistellung category and the
 * distribution policy, each with an honest "not yet" default.
 */
function ClassificationSelects({
  id,
  category,
  policy,
  onCategory,
  onPolicy,
  className,
  stated = false,
}: {
  id: string;
  category: string;
  policy: string;
  onCategory: (category: string) => void;
  onPolicy: (policy: string) => void;
  className?: string;
  // A category is already stored: the select offers no way back to none.
  stated?: boolean;
}) {
  return (
    <>
      <div className="space-y-1.5">
        <label htmlFor={`${id}-category`} className="microlabel block text-muted-foreground">
          Teilfreistellung
        </label>
        <NativeSelect
          id={`${id}-category`}
          value={category}
          onChange={(event) => onCategory(event.target.value)}
          className={className}
        >
          {!stated && <option value="">Not yet classified</option>}
          {Object.entries(CATEGORY_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-1.5">
        <label htmlFor={`${id}-policy`} className="microlabel block text-muted-foreground">
          Distribution policy
        </label>
        <NativeSelect
          id={`${id}-policy`}
          value={policy}
          onChange={(event) => onPolicy(event.target.value)}
          className={className}
        >
          <option value="">Not yet known</option>
          <option value="distributing">Distributing</option>
          <option value="accumulating">Accumulating</option>
        </NativeSelect>
      </div>
    </>
  );
}

/**
 * The EUR price the providers answered (tickets 18 and 45). A stale figure
 * wears its label and explains its source and age; an Instrument nothing has
 * ever priced says "unpriced" — never a zero. Cash and stablecoins (valued
 * by reference rate) stay a quiet dash, as does a row whose report has not
 * arrived.
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
      {entry.price_eur !== null && <Price value={entry.price_eur} currency="EUR" />}
      {entry.status === "stale" && (
        <span className="microlabel ml-2 text-caution" title={staleExplanation(entry)}>
          stale
        </span>
      )}
    </>
  );
}
