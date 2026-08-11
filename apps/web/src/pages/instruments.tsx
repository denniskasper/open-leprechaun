import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Shapes } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import {
  fetchCryptoPrices,
  type PricedInstrument,
  type ProviderCondition,
} from "@/api/prices";
import {
  classifyFund,
  createSecurity,
  reviewSecurity,
  searchSecurities,
  type AdminClassification,
  type Candidate,
  type CategorySource,
  type DistributionPolicy,
  type FundCategory,
  type NewSecurity,
} from "@/api/securities";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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
  const [adding, setAdding] = useState(false);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Instruments"
        description="Everything tradable, one concept: crypto keyed on chain and contract, securities on ISIN, cash by currency. A symbol is only a label."
        actions={
          <Button onClick={() => setAdding((open) => !open)}>
            <Plus aria-hidden />
            Add security
          </Button>
        }
      />

      {adding && <AddSecurityPanel onDone={() => setAdding(false)} />}

      {error ? (
        <ErrorState
          title="The instruments could not be loaded"
          detail="The API did not answer with the instrument list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 && !adding ? (
        <EmptyState
          icon={Shapes}
          title="No Instruments yet"
          description="Add a share or fund by searching its ISIN, WKN, ticker or name — or let imports mint Instruments as they arrive."
          action={
            <Button variant="outline" onClick={() => setAdding(true)}>
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
    <section className="rise rounded-xl border border-border p-5" aria-label="Add security">
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
            <p className="mt-3 text-sm text-alarm">{search.error.message}</p>
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
      {add.error != null && <span className="text-sm text-alarm">{add.error.message}</span>}
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
      <div className="grid gap-4 sm:grid-cols-2">
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
      {create.error != null && <p className="text-sm text-alarm">{create.error.message}</p>}
      <Button type="submit" disabled={create.isPending || listingHalf}>
        Create security
      </Button>
    </form>
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
  const [editing, setEditing] = useState<number | null>(null);

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
          {["Symbol", "Name", "Family", "Identity", "Teilfreistellung", "Price", "Listings"].map(
            (column) => (
              <th
                key={column}
                scope="col"
                className="microlabel py-2.5 pr-4 text-muted-foreground"
              >
                {column}
              </th>
            ),
          )}
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
              editing={editing === instrument.id}
              onEdit={(open) => setEditing(open ? instrument.id : null)}
            />
          );
        })}
      </tbody>
    </table>
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
}: {
  instrument: Instrument;
  warning: "dangerous" | "ignored" | null;
  shared: boolean;
  entry: PricedInstrument | undefined;
  index: number;
  editing: boolean;
  onEdit: (open: boolean) => void;
}) {
  const cell = classificationCell(instrument);
  return (
    <>
      <tr
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
        <td className="py-3 pr-4">
          <ClassificationSummary cell={cell} editing={editing} onEdit={onEdit} />
        </td>
        <td className="py-3 pr-4 font-mono tabular-nums">
          <PriceCell entry={entry} family={instrument.family} />
        </td>
        <td className="py-3 font-mono tabular-nums text-muted-foreground">
          {instrument.listings.length === 0
            ? "—"
            : instrument.listings
                .map((listing) => `${listing.venue} · ${listing.quote_currency}`)
                .join(", ")}
        </td>
      </tr>
      {editing && cell.kind !== "not_applicable" && (
        <tr className="border-b border-border">
          <td colSpan={7} className="py-4">
            <SettleForm
              instrument={instrument}
              review={cell.kind === "review"}
              onDone={() => onEdit(false)}
            />
          </td>
        </tr>
      )}
    </>
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
 * The one inline editor: classifying a fund, or — for an import-created
 * security — settling its review by choosing what it actually is.
 */
function SettleForm({
  instrument,
  review,
  onDone,
}: {
  instrument: Instrument;
  review: boolean;
  onDone: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const [type, setType] = useState(review ? "share" : instrument.type);
  const [symbol, setSymbol] = useState(instrument.symbol);
  const [name, setName] = useState(instrument.name);
  const [category, setCategory] = useState(instrument.fund_category ?? "");
  const [policy, setPolicy] = useState(instrument.distribution_policy ?? "");
  const fund = FUND_TYPES.includes(type);

  // The Admin's own act carries no source — the server stamps `admin`.
  const classification: AdminClassification | null =
    fund && category !== ""
      ? {
          fund_category: category as FundCategory,
          distribution_policy: policy === "" ? null : (policy as DistributionPolicy),
        }
      : null;
  const settle = useMutation({
    mutationFn: () => {
      if (review) {
        return reviewSecurity(instrument.id, {
          type,
          symbol: symbol.trim(),
          name: name.trim(),
          classification,
        });
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
      {review && (
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
      {(fund || !review) && (
        <ClassificationSelects
          id={id}
          category={category}
          policy={policy}
          onCategory={setCategory}
          onPolicy={setPolicy}
        />
      )}
      {settle.error != null && <p className="text-sm text-alarm">{settle.error.message}</p>}
      <Button type="submit" disabled={settle.isPending || (!review && classification === null)}>
        {review ? "Settle review" : "Save classification"}
      </Button>
    </form>
  );
}

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
}: {
  id: string;
  category: string;
  policy: string;
  onCategory: (category: string) => void;
  onPolicy: (policy: string) => void;
  className?: string;
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
          <option value="">Not yet classified</option>
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
 * The EUR price the chain answered (ticket 18). A stale figure wears its
 * label and explains its source and age; an Instrument nothing has ever
 * priced says "unpriced" — never a zero. A security says so too: no source
 * prices securities yet (ticket 45), and a value nothing can vouch for is an
 * unknown, not zero. Cash and stablecoins (valued by reference rate) stay a
 * quiet dash.
 */
function PriceCell({
  entry,
  family,
}: {
  entry: PricedInstrument | undefined;
  family: Instrument["family"];
}) {
  if (!entry) {
    if (family === "security") {
      return (
        <span
          className="microlabel text-caution"
          title="Nothing prices this security yet — an unknown value, never zero."
        >
          unpriced
        </span>
      );
    }
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
