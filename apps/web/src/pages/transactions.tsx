import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2, X } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import {
  bulkReassign,
  bulkRetype,
  DECIMAL_PATTERN,
  fetchTransactions,
  recordTransaction,
  removeTransaction,
  reviseTransaction,
  type CapitalIncome,
  type OriginalAmount,
  type LegRole,
  type NewTransaction,
  type Reconstructed,
  type Transaction,
  type TransactionType,
} from "@/api/transactions";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate, formatMoneyExact, formatQuantity, formatTimestamp } from "@/lib/format";

interface TypeWords {
  /** The event as the ledger and the form both speak it. */
  label: string;
  /** The optgroup the form offers it under. */
  group: string;
}

/**
 * The vocabulary in the order the form offers it: what actually happened, for
 * crypto and securities both, so classification follows from the record.
 */
export const TYPE_VOCABULARY: Record<TransactionType, TypeWords> = {
  trade: { label: "Trade", group: "Exchange of value" },
  spend: { label: "Spend", group: "Exchange of value" },
  transfer_in: { label: "Transfer in", group: "Transfers" },
  transfer_out: { label: "Transfer out", group: "Transfers" },
  // A position that predates the available history — like an inbound
  // transfer, but declaring its record reconstructed rather than observed.
  opening_balance: { label: "Opening balance", group: "Before known history" },
  staking_reward: { label: "Staking reward", group: "Income" },
  lending_interest: { label: "Lending interest", group: "Income" },
  mining_reward: { label: "Mining reward", group: "Income" },
  airdrop: { label: "Airdrop", group: "Income" },
  // Not income: kept but received for nothing, so no Leistung and no
  // Anschaffung — what a keep decision settles an unsolicited inflow as.
  windfall: { label: "Windfall", group: "Received for nothing" },
  dividend: { label: "Dividend", group: "Income" },
  distribution: { label: "Distribution", group: "Income" },
  interest: { label: "Interest", group: "Income" },
  fee: { label: "Fee", group: "Costs" },
};

const TYPE_ORDER = Object.keys(TYPE_VOCABULARY) as TransactionType[];

interface ReconstructedWords {
  /** The choice as the form offers it. */
  label: string;
  /** The chip a ledger row wears, so the assumption never poses as a movement. */
  marker: string;
  /** Why, and which figures the choice will affect — the copy is load-bearing. */
  explanation: string;
}

/**
 * The two variants of an Opening Balance, distinct because the difference
 * decides a tax outcome: an exemption depends on the acquisition date, while
 * the basis may be a genuine estimate.
 */
export const RECONSTRUCTED_WORDS: Record<Reconstructed, ReconstructedWords> = {
  basis: {
    label: "Acquisition date known — basis estimated",
    marker: "basis estimated",
    explanation:
      "The date is used as given: it decides the holding period, so a disposal after more " +
      "than a year is exempt and its gain excluded entirely. The estimated basis only sizes " +
      "a gain that is taxed at all.",
  },
  basis_and_date: {
    label: "Date and basis both reconstructed",
    marker: "date & basis reconstructed",
    explanation:
      "Dated at the start of known history — deliberately late, so disposals count as " +
      "short-term rather than assuming an older, exempt acquisition. Choose this only where " +
      "the date is genuinely unknown: applied to a known date it manufactures tax on an " +
      "exempt holding.",
  },
};

/** What lots minted from an Opening Balance carry — shown wherever the marker is worn. */
const ESTIMATED_LOT_TITLE =
  "Lots minted from an Opening Balance are marked estimated; any disposal consuming one " +
  "is flagged as resting on an estimate.";

/** The instant means something different on each variant, and the label says so. */
export function occurredAtWords(
  type: TransactionType,
  reconstructed: Reconstructed | null,
): string {
  if (type !== "opening_balance") {
    return "Occurred at";
  }
  // Date-known is the default reading: the conservative label appears only
  // once the conservative variant is deliberately chosen.
  return reconstructed === "basis_and_date" ? "Known history begins at" : "Acquired at";
}

/**
 * The legs a fresh event of this type starts from — the balance the type
 * demands, so a buy opens with both the cash spent and the asset acquired
 * already on the form.
 */
export function legTemplate(type: TransactionType): LegRole[] {
  switch (type) {
    case "trade":
      return ["out", "in"];
    case "transfer_out":
    case "spend":
      return ["out"];
    case "fee":
      return ["fee"];
    default:
      return ["in"];
  }
}

/** Positive and fixed-point: digits with at most one point, and not all zero. */
export function isPositiveDecimal(value: string): boolean {
  return DECIMAL_PATTERN.test(value) && /[1-9]/.test(value);
}

/** The types that may declare what was withheld at source. */
const INCOME_TYPES: ReadonlySet<TransactionType> = new Set([
  "dividend",
  "distribution",
  "interest",
]);

/** What the form holds of a capital-income declaration, as typed. */
export interface DraftWithheld {
  payerId: string;
  foreignWithholding: string;
  sourceCountry: string;
  kapitalertragsteuer: string;
  solidaritySurcharge: string;
  churchTax: string;
}

export const EMPTY_WITHHELD: DraftWithheld = {
  payerId: "",
  foreignWithholding: "",
  sourceCountry: "",
  kapitalertragsteuer: "",
  solidaritySurcharge: "",
  churchTax: "",
};

const COUNTRY_PATTERN = /^[A-Za-z]{2}$/;

/**
 * The declaration the draft amounts to — null on a type that declares
 * nothing, and where nothing was entered, so a plain receipt stays plain.
 * A blank amount is zero; entered strings cross exactly as typed.
 */
export function capitalIncomeOf(
  type: TransactionType,
  draft: DraftWithheld,
): CapitalIncome | null {
  if (!INCOME_TYPES.has(type) || Object.values(draft).every((value) => value.trim() === "")) {
    return null;
  }
  return {
    paying_instrument_id: draft.payerId ? Number(draft.payerId) : null,
    foreign_withholding: draft.foreignWithholding || "0",
    source_country: draft.sourceCountry.trim().toUpperCase() || null,
    kapitalertragsteuer: draft.kapitalertragsteuer || "0",
    solidarity_surcharge: draft.solidaritySurcharge || "0",
    church_tax: draft.churchTax || "0",
  };
}

/**
 * The sentence naming why the draft declaration cannot be recorded, or null
 * when it can — the API's own judgements, made before the round trip.
 */
export function withheldDefect(type: TransactionType, draft: DraftWithheld): string | null {
  if (!INCOME_TYPES.has(type)) {
    return null;
  }
  const amounts = [
    draft.foreignWithholding,
    draft.kapitalertragsteuer,
    draft.solidaritySurcharge,
    draft.churchTax,
  ];
  if (amounts.some((amount) => amount !== "" && !DECIMAL_PATTERN.test(amount))) {
    return "Withheld amounts are plain decimals — a point separates the fraction.";
  }
  const country = draft.sourceCountry.trim();
  if (isPositiveDecimal(draft.foreignWithholding) !== (country !== "")) {
    return "A foreign withholding tax and its source country are recorded together.";
  }
  if (country !== "" && !COUNTRY_PATTERN.test(country)) {
    return "The source country is its two-letter code — US, CH, FR.";
  }
  if (type === "distribution" && !draft.payerId) {
    return "A distribution names the fund that paid it — its partial exemption follows the fund.";
  }
  return null;
}

/**
 * What a recorded declaration took out, in a line: each non-zero component
 * by its short name, every amount beside the currency it was withheld in —
 * the received leg's own.
 */
export function withheldWords(declared: CapitalIncome, currency: string): string {
  const parts = [
    [`Quellensteuer ${declared.source_country ?? ""}`.trim(), declared.foreign_withholding],
    ["KESt", declared.kapitalertragsteuer],
    ["Soli", declared.solidarity_surcharge],
    ["KiSt", declared.church_tax],
  ] as const;
  const taken = parts
    .filter(([, amount]) => isPositiveDecimal(amount))
    .map(([name, amount]) => `${name} ${formatQuantity(amount)} ${currency}`);
  return taken.length === 0 ? "nothing withheld" : `withheld · ${taken.join(" · ")}`;
}

/**
 * A trade as its broker priced it, in a line: the amount in the currency it
 * was priced in, the rate applied to settle it and the date that rate is of.
 */
export function originalAmountWords(
  original: OriginalAmount,
  settledCurrency: string,
  locale?: string,
): string {
  return [
    `priced ${formatMoneyExact(original.amount, original.currency, locale)}`,
    `${formatQuantity(original.rate, locale)} ${original.currency} per ${settledCurrency}`,
    `rate of ${formatDate(original.rate_date, locale)}`,
  ].join(" · ");
}

/** The currency a trade settled in: its one cash leg that is no fee. */
function settledSymbol(
  transaction: Transaction,
  instrumentById: ReadonlyMap<number, Instrument>,
): string {
  const settled = transaction.legs.find(
    (leg) => leg.role !== "fee" && instrumentById.get(leg.instrument_id)?.family === "cash",
  );
  return instrumentById.get(settled?.instrument_id ?? -1)?.symbol ?? "settled unit";
}

/** The symbol of the one leg an income event received — what its withheld amounts are in. */
function receivedSymbol(
  transaction: Transaction,
  instrumentById: ReadonlyMap<number, Instrument>,
): string {
  const received = transaction.legs.find((leg) => leg.role === "in");
  if (!received) {
    return "";
  }
  return instrumentById.get(received.instrument_id)?.symbol ?? `#${received.instrument_id}`;
}

function withheldOf(transaction: Transaction | undefined): DraftWithheld {
  const declared = transaction?.capital_income;
  if (!declared) {
    return EMPTY_WITHHELD;
  }
  const amount = (value: string) => (isPositiveDecimal(value) ? value : "");
  return {
    payerId: declared.paying_instrument_id === null ? "" : String(declared.paying_instrument_id),
    foreignWithholding: amount(declared.foreign_withholding),
    sourceCountry: declared.source_country ?? "",
    kapitalertragsteuer: amount(declared.kapitalertragsteuer),
    solidaritySurcharge: amount(declared.solidarity_surcharge),
    churchTax: amount(declared.church_tax),
  };
}

export interface DraftLeg {
  /** Stable across removals, so React state survives reordering. */
  key: number;
  role: LegRole;
  accountId: string;
  instrumentId: string;
  quantity: string;
  /** Position of the sibling this fee was charged against, if any. */
  chargedAgainst: number | null;
}

/**
 * Remove a leg and keep every fee attachment honest: a fee charged against
 * the removed leg loses its attachment, one charged against a later leg
 * follows it down a position.
 */
export function withLegRemoved(legs: DraftLeg[], removed: number): DraftLeg[] {
  return legs
    .filter((_, position) => position !== removed)
    .map((leg) => {
      if (leg.chargedAgainst === null || leg.chargedAgainst === removed) {
        return { ...leg, chargedAgainst: null };
      }
      return leg.chargedAgainst > removed
        ? { ...leg, chargedAgainst: leg.chargedAgainst - 1 }
        : leg;
    });
}

/** What the leg's quantity wears: an inflow gains, an outflow spends, a fee consumes. */
export function signOf(role: LegRole): string {
  return role === "in" ? "+" : "−";
}

/** Why the overridden marker exists — shown wherever it is worn. */
const OVERRIDDEN_TITLE =
  "Edited or moved by hand after import: a re-import will not silently revert it, and " +
  "reversing its batch leaves it standing.";

/** A selection with one membership toggled — the checkbox column's one move. */
export function withToggled(selected: ReadonlySet<number>, id: number): Set<number> {
  const next = new Set(selected);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  return next;
}

/** What a reconciliation gap hands the form: where, what, and how much. */
export interface OpeningBalancePrefill {
  accountId: string;
  instrumentId: string;
  quantity: string;
}

/**
 * The Opening Balance a reconciliation gap asks for, read off the address:
 * `?opening_balance=<account>:<instrument>:<quantity>`. Only the position is
 * carried — what is reconstructed and the estimated basis stay the Admin's to
 * declare. Null for anything but two ids and a positive fixed-point quantity.
 */
export function openingBalancePrefill(search: string): OpeningBalancePrefill | null {
  const [accountId, instrumentId, quantity, ...rest] = (
    new URLSearchParams(search).get("opening_balance") ?? ""
  ).split(":");
  if (
    rest.length > 0 ||
    !accountId ||
    !instrumentId ||
    !quantity ||
    !/^\d+$/.test(accountId) ||
    !/^\d+$/.test(instrumentId) ||
    !isPositiveDecimal(quantity)
  ) {
    return null;
  }
  return { accountId, instrumentId, quantity };
}

/** The address a gap's Opening Balance travels in — openingBalancePrefill's inverse. */
export function openingBalanceSearch(prefill: OpeningBalancePrefill): string {
  return new URLSearchParams({
    opening_balance: `${prefill.accountId}:${prefill.instrumentId}:${prefill.quantity}`,
  }).toString();
}

export function TransactionsPage() {
  const transactions = useQuery({ queryKey: ["transactions"], queryFn: fetchTransactions });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: fetchInstruments });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });
  // A reconciliation gap links here with the position it could not account
  // for; the form then opens on an Opening Balance for exactly that.
  const [search] = useSearchParams();
  const prefill = openingBalancePrefill(search.toString());
  const [recording, setRecording] = useState(prefill !== null);

  const failed = transactions.error ?? instruments.error ?? platforms.error;
  const loaded = transactions.data && instruments.data && platforms.data;

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Transactions"
        description="Every economic event as a set of legs that balance — what left, what arrived, what a fee consumed. A trade's other side is structural, so no disposal goes silently missing."
        actions={
          <Button onClick={() => setRecording((open) => !open)}>
            <Plus aria-hidden />
            Record Transaction
          </Button>
        }
      />

      {recording && loaded && !platforms.data.some((platform) => platform.accounts.length > 0) && (
        <p role="status" className="text-sm text-muted-foreground">
          No Account exists yet, and every leg of a Transaction sits in one —{" "}
          <Link to="/settings/platforms" className="underline underline-offset-2">
            add a Platform and an Account
          </Link>{" "}
          first.
        </p>
      )}

      {recording && loaded && (
        <TransactionForm
          instruments={instruments.data}
          platforms={platforms.data}
          openingBalance={prefill ?? undefined}
          onDone={() => setRecording(false)}
        />
      )}

      {failed ? (
        <ErrorState
          title="The ledger could not be loaded"
          detail="The API did not answer with the transactions, instruments or accounts."
          onRetry={() => {
            void transactions.refetch();
            void instruments.refetch();
            void platforms.refetch();
          }}
        />
      ) : loaded && transactions.data.length === 0 && !recording ? (
        <EmptyState
          icon={Scale}
          title="No Transactions yet"
          description="Record the first economic event by hand — a buy carries both the asset acquired and the cash spent, and a fee is its own leg. Imports will add to the same ledger later."
          action={
            <Button variant="outline" onClick={() => setRecording(true)}>
              <Plus aria-hidden />
              Record the first Transaction
            </Button>
          }
        />
      ) : loaded ? (
        <LedgerTable
          transactions={transactions.data}
          instruments={instruments.data}
          platforms={platforms.data}
        />
      ) : null}
    </div>
  );
}

function LedgerTable({
  transactions,
  instruments,
  platforms,
}: {
  transactions: Transaction[];
  instruments: Instrument[];
  platforms: Platform[];
}) {
  // Built once for the whole ledger; every row reads the same two maps.
  const instrumentById = new Map(instruments.map((instrument) => [instrument.id, instrument]));
  const accountName = new Map(
    platforms.flatMap((platform) =>
      platform.accounts.map((account) => [account.id, `${platform.name} · ${account.name}`]),
    ),
  );
  // The bulk selection: fixing a systematic import error is one act over the
  // chosen rows, not a hundred edits.
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const chosen = transactions.filter((transaction) => selected.has(transaction.id));

  return (
    <div className="space-y-4">
      {chosen.length > 0 && (
        <BulkToolbar
          chosen={chosen}
          platforms={platforms}
          onDone={() => setSelected(new Set())}
        />
      )}
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th scope="col" className="w-8 py-2.5 pr-2">
              <input
                type="checkbox"
                aria-label="Select every Transaction"
                checked={selected.size === transactions.length && transactions.length > 0}
                onChange={() =>
                  setSelected(
                    selected.size === transactions.length
                      ? new Set()
                      : new Set(transactions.map((transaction) => transaction.id)),
                  )
                }
              />
            </th>
            {["When", "Event", "Legs", ""].map((column, index) => (
              <th
                key={column || "actions"}
                scope="col"
                className={`microlabel py-2.5 text-muted-foreground ${index === 3 ? "" : "pr-4"}`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {transactions.map((transaction, index) => (
            <LedgerRow
              key={transaction.id}
              transaction={transaction}
              instruments={instruments}
              platforms={platforms}
              instrumentById={instrumentById}
              accountName={accountName}
              index={index}
              selected={selected.has(transaction.id)}
              onToggle={() => setSelected((current) => withToggled(current, transaction.id))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BulkToolbar({
  chosen,
  platforms,
  onDone,
}: {
  chosen: Transaction[];
  platforms: Platform[];
  onDone: () => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [type, setType] = useState<TransactionType>("trade");
  const id = useId();
  const queryClient = useQueryClient();
  const ids = chosen.map((transaction) => transaction.id);

  const done = async () => {
    await queryClient.invalidateQueries({ queryKey: ["transactions"] });
    onDone();
  };
  const reassign = useMutation({
    mutationFn: () => bulkReassign(ids, Number(accountId)),
    onSuccess: done,
  });
  const retype = useMutation({
    mutationFn: () => bulkRetype(ids, type),
    onSuccess: done,
  });
  const failed = reassign.error ?? retype.error;
  const busy = reassign.isPending || retype.isPending;

  return (
    <div
      className="rise rounded-xl border border-border p-4"
      role="group"
      aria-label="Bulk repair"
    >
      <p className="microlabel mb-3 text-muted-foreground">
        {chosen.length === 1 ? "1 Transaction selected" : `${chosen.length} Transactions selected`}
      </p>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-44 space-y-2">
            <label htmlFor={`${id}-account`} className="microlabel block text-muted-foreground">
              Reassign to Account
            </label>
            <select
              id={`${id}-account`}
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              className={SELECT_SHELL}
            >
              <option value="" disabled className="bg-background text-foreground">
                Select…
              </option>
              {platforms
                .filter((platform) => platform.accounts.length > 0)
                .map((platform) => (
                  <optgroup key={platform.id} label={platform.name}>
                    {platform.accounts.map((account) => (
                      <option
                        key={account.id}
                        value={account.id}
                        className="bg-background text-foreground"
                      >
                        {account.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
            </select>
          </div>
          <Button
            variant="outline"
            disabled={busy || accountId === ""}
            onClick={() => reassign.mutate()}
          >
            {reassign.isPending ? "Reassigning…" : "Reassign"}
          </Button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-2">
            <label htmlFor={`${id}-type`} className="microlabel block text-muted-foreground">
              Re-type as
            </label>
            <TypeSelect id={`${id}-type`} value={type} onChange={setType} />
          </div>
          <Button variant="outline" disabled={busy} onClick={() => retype.mutate()}>
            {retype.isPending ? "Re-typing…" : "Re-type"}
          </Button>
        </div>
        <Button variant="ghost" className="text-muted-foreground" onClick={onDone}>
          Clear selection
        </Button>
      </div>
      {failed && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {failed.message}
        </p>
      )}
    </div>
  );
}

function LedgerRow({
  transaction,
  instruments,
  platforms,
  instrumentById,
  accountName,
  index,
  selected,
  onToggle,
}: {
  transaction: Transaction;
  instruments: Instrument[];
  platforms: Platform[];
  instrumentById: Map<number, Instrument>;
  accountName: Map<number, string>;
  index: number;
  selected: boolean;
  onToggle: () => void;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <>
      <tr
        className="rise border-b border-border align-top"
        style={{ animationDelay: `${120 + index * 40}ms` }}
        aria-label={`${TYPE_VOCABULARY[transaction.type].label} on ${transaction.occurred_at}`}
      >
        <td className="py-3 pr-2">
          <input
            type="checkbox"
            aria-label={`Select the ${TYPE_VOCABULARY[transaction.type].label} on ${transaction.occurred_at}`}
            checked={selected}
            onChange={onToggle}
          />
        </td>
        <td className="py-3 pr-4 font-mono text-xs tabular-nums text-muted-foreground">
          {formatTimestamp(Date.parse(transaction.occurred_at))}
        </td>
        <td className="py-3 pr-4">
          <span className="font-medium">{TYPE_VOCABULARY[transaction.type].label}</span>
          {(transaction.import_source || transaction.manually_overridden) && (
            <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
              {transaction.import_source && (
                <span
                  className="microlabel text-muted-foreground"
                  title="Created by an import; its batch can be reversed as a unit on the Imports screen."
                >
                  imported · {transaction.import_source}
                </span>
              )}
              {transaction.manually_overridden && (
                <span className="microlabel text-caution" title={OVERRIDDEN_TITLE}>
                  overridden by hand
                </span>
              )}
            </p>
          )}
          {transaction.reconstructed && (
            <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
              <span className="microlabel text-caution" title={ESTIMATED_LOT_TITLE}>
                {RECONSTRUCTED_WORDS[transaction.reconstructed].marker}
              </span>
              {transaction.estimated_basis_eur && (
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  est. {formatMoneyExact(transaction.estimated_basis_eur, "EUR")}
                </span>
              )}
            </p>
          )}
          {transaction.capital_income && (
            <p className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
              {withheldWords(
                transaction.capital_income,
                receivedSymbol(transaction, instrumentById),
              )}
            </p>
          )}
          {transaction.original_amount && (
            <p
              className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground"
              title="The trade as the broker priced it, and the rate it applied to settle in the Depot's currency."
            >
              {originalAmountWords(
                transaction.original_amount,
                settledSymbol(transaction, instrumentById),
              )}
            </p>
          )}
          {transaction.note && (
            <p className="mt-0.5 max-w-52 truncate text-xs text-muted-foreground">
              {transaction.note}
            </p>
          )}
        </td>
        <td className="py-3 pr-4">
          <ul className="space-y-1">
            {transaction.legs.map((leg) => (
              <li key={leg.id} className="flex flex-wrap items-baseline gap-x-2">
                <span
                  className={`font-mono tabular-nums ${
                    leg.role === "in" ? "text-signal" : leg.role === "fee" ? "text-caution" : ""
                  }`}
                >
                  {signOf(leg.role)}
                  {formatQuantity(leg.quantity)}{" "}
                  {instrumentById.get(leg.instrument_id)?.symbol ?? `#${leg.instrument_id}`}
                </span>
                {leg.role === "fee" && (
                  <span
                    className="microlabel text-caution"
                    title="A fee is its own leg — its tax treatment follows the leg it was charged against."
                  >
                    fee
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {accountName.get(leg.account_id) ?? `Account #${leg.account_id}`}
                </span>
              </li>
            ))}
          </ul>
        </td>
        <td className="py-3 text-right">
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setEditing((open) => !open)}
            >
              <Pencil aria-hidden />
              Edit
            </Button>
            <RemoveButton transaction={transaction} />
          </div>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-border">
          <td colSpan={5} className="py-4">
            <TransactionForm
              instruments={instruments}
              platforms={platforms}
              revising={transaction}
              onDone={() => setEditing(false)}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function RemoveButton({ transaction }: { transaction: Transaction }) {
  // Removal is destructive and instant, so it asks once, inline: the first
  // press arms the button, the second one acts.
  const [armed, setArmed] = useState(false);
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => removeTransaction(transaction.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["transactions"] }),
  });

  return (
    <Button
      variant="ghost"
      size="sm"
      className={armed ? "text-alarm" : "text-muted-foreground"}
      disabled={remove.isPending}
      onBlur={() => setArmed(false)}
      onClick={() => {
        if (armed) {
          remove.mutate();
        } else {
          setArmed(true);
        }
      }}
    >
      <Trash2 aria-hidden />
      {remove.isPending ? "Removing…" : armed ? "Confirm removal" : "Remove"}
    </Button>
  );
}

/** The instant "now", in the wall-clock shape a datetime-local input speaks. */
function nowForInput(): string {
  const now = new Date();
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}`
  );
}

function toInput(iso: string): string {
  const occurred = new Date(iso);
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${occurred.getFullYear()}-${pad(occurred.getMonth() + 1)}-${pad(occurred.getDate())}` +
    `T${pad(occurred.getHours())}:${pad(occurred.getMinutes())}:${pad(occurred.getSeconds())}`
  );
}

let draftKey = 0;

function freshLeg(role: LegRole): DraftLeg {
  draftKey += 1;
  return { key: draftKey, role, accountId: "", instrumentId: "", quantity: "", chargedAgainst: null };
}

function draftsOf(transaction: Transaction): DraftLeg[] {
  const positionOf = new Map(transaction.legs.map((leg, position) => [leg.id, position]));
  return transaction.legs.map((leg) => {
    draftKey += 1;
    return {
      key: draftKey,
      role: leg.role,
      accountId: String(leg.account_id),
      instrumentId: String(leg.instrument_id),
      quantity: leg.quantity,
      chargedAgainst:
        leg.charged_against_leg_id === null
          ? null
          : (positionOf.get(leg.charged_against_leg_id) ?? null),
    };
  });
}

function TransactionForm({
  instruments,
  platforms,
  revising,
  openingBalance,
  onDone,
}: {
  instruments: Instrument[];
  platforms: Platform[];
  revising?: Transaction;
  /** A reconciliation gap's position: the form opens as its Opening Balance. */
  openingBalance?: OpeningBalancePrefill;
  onDone: () => void;
}) {
  const [type, setType] = useState<TransactionType>(
    revising?.type ?? (openingBalance ? "opening_balance" : "trade"),
  );
  const [occurredAt, setOccurredAt] = useState(
    revising ? toInput(revising.occurred_at) : nowForInput(),
  );
  const [note, setNote] = useState(revising?.note ?? "");
  // An Opening Balance's declarations; carried in state whatever the type,
  // submitted only when the type is opening_balance. Date-known is the
  // default: the conservative variant is for a date genuinely unknown.
  const [reconstructed, setReconstructed] = useState<Reconstructed>(
    revising?.reconstructed ?? "basis",
  );
  const [estimatedBasis, setEstimatedBasis] = useState(revising?.estimated_basis_eur ?? "");
  // What was withheld at source; carried whatever the type, submitted only
  // on a dividend, a distribution or interest.
  const [withheld, setWithheld] = useState<DraftWithheld>(() => withheldOf(revising));
  const [legs, setLegs] = useState<DraftLeg[]>(
    revising
      ? draftsOf(revising)
      : openingBalance
        ? [{ ...freshLeg("in"), ...openingBalance }]
        : legTemplate("trade").map(freshLeg),
  );
  const id = useId();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (transaction: NewTransaction) =>
      revising ? reviseTransaction(revising.id, transaction) : recordTransaction(transaction),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["transactions"] });
      onDone();
    },
  });

  function retype(next: TransactionType) {
    setType(next);
    // A fresh form re-opens with the legs the new type demands; typed-in
    // quantities mean the Admin is mid-thought, so those legs stay.
    if (legs.every((leg) => leg.quantity === "")) {
      setLegs(legTemplate(next).map(freshLeg));
    }
  }

  function amend(position: number, change: Partial<DraftLeg>) {
    setLegs((current) =>
      current.map((leg, at) => (at === position ? { ...leg, ...change } : leg)),
    );
  }

  function declare(change: Partial<DraftWithheld>) {
    setWithheld((current) => ({ ...current, ...change }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({
      type,
      occurred_at: new Date(occurredAt).toISOString(),
      note: note.trim() || null,
      reconstructed: type === "opening_balance" ? reconstructed : null,
      estimated_basis_eur: type === "opening_balance" ? estimatedBasis : null,
      capital_income: capitalIncomeOf(type, withheld),
      legs: legs.map((leg) => ({
        account_id: Number(leg.accountId),
        instrument_id: Number(leg.instrumentId),
        role: leg.role,
        quantity: leg.quantity,
        charged_against: leg.role === "fee" ? leg.chargedAgainst : null,
      })),
    });
  }

  const withheldProblem = withheldDefect(type, withheld);
  const incomplete =
    legs.length === 0 ||
    legs.some(
      (leg) => !leg.accountId || !leg.instrumentId || !isPositiveDecimal(leg.quantity),
    ) ||
    // Zero is a legitimate estimate — the most conservative there is — so the
    // basis is judged by shape alone, not by isPositiveDecimal.
    (type === "opening_balance" && !DECIMAL_PATTERN.test(estimatedBasis)) ||
    withheldProblem !== null;

  return (
    <form
      onSubmit={submit}
      className="rise rounded-xl border border-border p-5"
      aria-label={revising ? "Revise the Transaction" : "Record a Transaction"}
    >
      <p className="microlabel mb-4 text-muted-foreground">
        {revising ? "Revise Transaction" : "New Transaction"}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor={`${id}-type`} className="microlabel block text-muted-foreground">
            Type
          </label>
          <TypeSelect id={`${id}-type`} value={type} onChange={retype} />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-occurred`} className="microlabel block text-muted-foreground">
            {occurredAtWords(type, reconstructed)}
          </label>
          <Input
            id={`${id}-occurred`}
            type="datetime-local"
            step={1}
            required
            value={occurredAt}
            onChange={(event) => setOccurredAt(event.target.value)}
            className="font-mono tabular-nums"
          />
        </div>
        <div className="min-w-48 flex-1 space-y-2">
          <label htmlFor={`${id}-note`} className="microlabel block text-muted-foreground">
            Note
          </label>
          <Input
            id={`${id}-note`}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional"
          />
        </div>
      </div>

      {type === "opening_balance" && (
        <fieldset
          className="mt-5 space-y-4 rounded-md border border-border p-4"
          aria-label="What is reconstructed"
        >
          <legend className="microlabel px-1 text-caution">Reconstructed, not observed</legend>
          <p className="max-w-prose text-xs text-muted-foreground">
            A position that already existed when the available history begins. {ESTIMATED_LOT_TITLE}
          </p>
          <div className="space-y-3">
            {(Object.keys(RECONSTRUCTED_WORDS) as Reconstructed[]).map((variant) => (
              <label key={variant} className="flex max-w-prose cursor-pointer items-start gap-3">
                <input
                  type="radio"
                  name={`${id}-reconstructed`}
                  value={variant}
                  checked={reconstructed === variant}
                  onChange={() => setReconstructed(variant)}
                  className="mt-1"
                />
                <span>
                  <span className="block text-sm font-medium">
                    {RECONSTRUCTED_WORDS[variant].label}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {RECONSTRUCTED_WORDS[variant].explanation}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <div className="max-w-56 space-y-2">
            <label htmlFor={`${id}-basis`} className="microlabel block text-muted-foreground">
              Estimated basis (EUR)
            </label>
            <Input
              id={`${id}-basis`}
              required
              inputMode="decimal"
              pattern={DECIMAL_PATTERN.source}
              title="The reconstructed total cost of the position, in EUR. Zero is a legitimate estimate; a point separates the fraction."
              value={estimatedBasis}
              onChange={(event) => setEstimatedBasis(event.target.value)}
              placeholder="0.00"
              className="font-mono tabular-nums"
            />
          </div>
        </fieldset>
      )}

      {INCOME_TYPES.has(type) && (
        <fieldset
          className="mt-5 space-y-4 rounded-md border border-border p-4"
          aria-label="Withheld at source"
        >
          <legend className="microlabel px-1 text-muted-foreground">Withheld at source</legend>
          <p className="max-w-prose text-xs text-muted-foreground">
            The leg below is the net that arrived. Enter what was taken out before it did, in the
            same currency — the gross is their sum. Leave blank what was not withheld.
          </p>
          <div className="max-w-80 space-y-2">
            <label htmlFor={`${id}-payer`} className="microlabel block text-muted-foreground">
              Paid by{type === "distribution" ? "" : " (optional)"}
            </label>
            <select
              id={`${id}-payer`}
              value={withheld.payerId}
              onChange={(event) => declare({ payerId: event.target.value })}
              className={SELECT_SHELL}
            >
              <option value="" className="bg-background text-foreground">
                —
              </option>
              {instruments
                .filter((instrument) => instrument.family === "security")
                .map((instrument) => (
                  <option
                    key={instrument.id}
                    value={instrument.id}
                    className="bg-background text-foreground"
                  >
                    {instrument.symbol} · {instrument.name}
                  </option>
                ))}
            </select>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <WithheldAmount
              id={`${id}-foreign`}
              label="Foreign withholding tax"
              value={withheld.foreignWithholding}
              onChange={(foreignWithholding) => declare({ foreignWithholding })}
            />
            <div className="space-y-2">
              <label
                htmlFor={`${id}-country`}
                className="microlabel block whitespace-nowrap text-muted-foreground"
              >
                Source country
              </label>
              <Input
                id={`${id}-country`}
                value={withheld.sourceCountry}
                onChange={(event) => declare({ sourceCountry: event.target.value })}
                maxLength={2}
                placeholder="US"
                title="The two-letter code of the country that withheld — creditability depends on it."
                className="w-24 font-mono uppercase"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <WithheldAmount
              id={`${id}-kest`}
              label="Kapitalertragsteuer"
              value={withheld.kapitalertragsteuer}
              onChange={(kapitalertragsteuer) => declare({ kapitalertragsteuer })}
            />
            <WithheldAmount
              id={`${id}-soli`}
              label="Solidaritätszuschlag"
              value={withheld.solidaritySurcharge}
              onChange={(solidaritySurcharge) => declare({ solidaritySurcharge })}
            />
            <WithheldAmount
              id={`${id}-church`}
              label="Church tax"
              value={withheld.churchTax}
              onChange={(churchTax) => declare({ churchTax })}
            />
          </div>
          {withheldProblem && <p className="text-xs text-caution">{withheldProblem}</p>}
        </fieldset>
      )}

      <div className="mt-5 space-y-3">
        <p className="microlabel text-muted-foreground">Legs</p>
        {legs.map((leg, position) => (
          <LegEditor
            key={leg.key}
            id={`${id}-leg-${leg.key}`}
            leg={leg}
            position={position}
            legs={legs}
            instruments={instruments}
            platforms={platforms}
            onChange={(change) => amend(position, change)}
            onRemove={() => setLegs((current) => withLegRemoved(current, position))}
          />
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => setLegs((current) => [...current, freshLeg("fee")])}
        >
          <Plus aria-hidden />
          Add leg
        </Button>
      </div>

      {save.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {save.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={save.isPending || incomplete}>
          {save.isPending ? "Saving…" : revising ? "Save revision" : "Record"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function WithheldAmount({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    // No fixed width on the column: the letter-spaced caption of a long German
    // term is wider than its input, and must push its neighbour rather than
    // run into it.
    <div className="space-y-2">
      <label htmlFor={id} className="microlabel block whitespace-nowrap text-muted-foreground">
        {label}
      </label>
      <Input
        id={id}
        inputMode="decimal"
        pattern={DECIMAL_PATTERN.source}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="0.00"
        className="w-44 font-mono tabular-nums"
      />
    </div>
  );
}

// A native select rather than a shadcn one, as on the Platforms screen: fixed
// options, and the platform control already carries the behaviour. Its shell
// mirrors Input so a row of fields reads as one.
const SELECT_SHELL =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm transition-colors";

function TypeSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: TransactionType;
  onChange: (type: TransactionType) => void;
}) {
  const groups = [...new Set(TYPE_ORDER.map((type) => TYPE_VOCABULARY[type].group))];
  return (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value as TransactionType)}
      className={SELECT_SHELL}
    >
      {groups.map((group) => (
        <optgroup key={group} label={group}>
          {TYPE_ORDER.filter((type) => TYPE_VOCABULARY[type].group === group).map((type) => (
            <option key={type} value={type} className="bg-background text-foreground">
              {TYPE_VOCABULARY[type].label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

const ROLE_WORDS: Record<LegRole, string> = {
  in: "In — arrived",
  out: "Out — left",
  fee: "Fee — consumed",
};

function LegEditor({
  id,
  leg,
  position,
  legs,
  instruments,
  platforms,
  onChange,
  onRemove,
}: {
  id: string;
  leg: DraftLeg;
  position: number;
  legs: DraftLeg[];
  instruments: Instrument[];
  platforms: Platform[];
  onChange: (change: Partial<DraftLeg>) => void;
  onRemove: () => void;
}) {
  const instrumentById = new Map(instruments.map((instrument) => [instrument.id, instrument]));
  const siblings = legs
    .map((sibling, at) => ({ sibling, at }))
    .filter(({ sibling, at }) => at !== position && sibling.role !== "fee");

  return (
    <fieldset
      className="flex flex-wrap items-end gap-3 rounded-md border border-border p-3"
      aria-label={`Leg ${position + 1}`}
    >
      <div className="space-y-2">
        <label htmlFor={`${id}-role`} className="microlabel block text-muted-foreground">
          Role
        </label>
        <select
          id={`${id}-role`}
          value={leg.role}
          onChange={(event) =>
            onChange({ role: event.target.value as LegRole, chargedAgainst: null })
          }
          className={SELECT_SHELL}
        >
          {(Object.keys(ROLE_WORDS) as LegRole[]).map((role) => (
            <option key={role} value={role} className="bg-background text-foreground">
              {ROLE_WORDS[role]}
            </option>
          ))}
        </select>
      </div>
      <div className="min-w-40 space-y-2">
        <label htmlFor={`${id}-account`} className="microlabel block text-muted-foreground">
          Account
        </label>
        <select
          id={`${id}-account`}
          required
          value={leg.accountId}
          onChange={(event) => onChange({ accountId: event.target.value })}
          className={SELECT_SHELL}
        >
          <option value="" disabled className="bg-background text-foreground">
            Select…
          </option>
          {platforms
            .filter((platform) => platform.accounts.length > 0)
            .map((platform) => (
              <optgroup key={platform.id} label={platform.name}>
                {platform.accounts.map((account) => (
                  <option
                    key={account.id}
                    value={account.id}
                    className="bg-background text-foreground"
                  >
                    {account.name}
                  </option>
                ))}
              </optgroup>
            ))}
        </select>
      </div>
      <div className="min-w-32 space-y-2">
        <label htmlFor={`${id}-instrument`} className="microlabel block text-muted-foreground">
          Instrument
        </label>
        <select
          id={`${id}-instrument`}
          required
          value={leg.instrumentId}
          onChange={(event) => onChange({ instrumentId: event.target.value })}
          className={SELECT_SHELL}
        >
          <option value="" disabled className="bg-background text-foreground">
            Select…
          </option>
          {instruments.map((instrument) => (
            <option
              key={instrument.id}
              value={instrument.id}
              className="bg-background text-foreground"
            >
              {instrument.symbol} — {instrument.name}
            </option>
          ))}
        </select>
      </div>
      <div className="min-w-28 space-y-2">
        <label htmlFor={`${id}-quantity`} className="microlabel block text-muted-foreground">
          Quantity
        </label>
        <Input
          id={`${id}-quantity`}
          required
          inputMode="decimal"
          pattern={DECIMAL_PATTERN.source}
          title="A positive decimal, with a point for the fraction."
          value={leg.quantity}
          onChange={(event) => onChange({ quantity: event.target.value })}
          placeholder="0.00"
          className="font-mono tabular-nums"
        />
      </div>
      {leg.role === "fee" && siblings.length > 0 && (
        <div className="space-y-2">
          <label htmlFor={`${id}-against`} className="microlabel block text-muted-foreground">
            Charged against
          </label>
          <select
            id={`${id}-against`}
            value={leg.chargedAgainst ?? ""}
            onChange={(event) =>
              onChange({
                chargedAgainst: event.target.value === "" ? null : Number(event.target.value),
              })
            }
            className={SELECT_SHELL}
            title="The fee's tax treatment follows the leg it was charged against."
          >
            <option value="" className="bg-background text-foreground">
              Nothing — a bare cost
            </option>
            {siblings.map(({ sibling, at }) => (
              <option key={sibling.key} value={at} className="bg-background text-foreground">
                Leg {at + 1} —{" "}
                {instrumentById.get(Number(sibling.instrumentId))?.symbol ?? ROLE_WORDS[sibling.role]}
              </option>
            ))}
          </select>
        </div>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-muted-foreground"
        onClick={onRemove}
        disabled={legs.length === 1}
        aria-label={`Remove leg ${position + 1}`}
      >
        <X aria-hidden />
      </Button>
    </fieldset>
  );
}
