import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2, X } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import {
  DECIMAL_PATTERN,
  fetchTransactions,
  recordTransaction,
  removeTransaction,
  reviseTransaction,
  type LegRole,
  type NewTransaction,
  type Transaction,
  type TransactionType,
} from "@/api/transactions";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatQuantity, formatTimestamp } from "@/lib/format";

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
  staking_reward: { label: "Staking reward", group: "Income" },
  lending_interest: { label: "Lending interest", group: "Income" },
  mining_reward: { label: "Mining reward", group: "Income" },
  airdrop: { label: "Airdrop", group: "Income" },
  dividend: { label: "Dividend", group: "Income" },
  distribution: { label: "Distribution", group: "Income" },
  interest: { label: "Interest", group: "Income" },
  fee: { label: "Fee", group: "Costs" },
};

const TYPE_ORDER = Object.keys(TYPE_VOCABULARY) as TransactionType[];

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

export function TransactionsPage() {
  const transactions = useQuery({ queryKey: ["transactions"], queryFn: fetchTransactions });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: fetchInstruments });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });
  const [recording, setRecording] = useState(false);

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

      {recording && loaded && (
        <TransactionForm
          instruments={instruments.data}
          platforms={platforms.data}
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

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
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
          />
        ))}
      </tbody>
    </table>
  );
}

function LedgerRow({
  transaction,
  instruments,
  platforms,
  instrumentById,
  accountName,
  index,
}: {
  transaction: Transaction;
  instruments: Instrument[];
  platforms: Platform[];
  instrumentById: Map<number, Instrument>;
  accountName: Map<number, string>;
  index: number;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <>
      <tr
        className="rise border-b border-border align-top"
        style={{ animationDelay: `${120 + index * 40}ms` }}
        aria-label={`${TYPE_VOCABULARY[transaction.type].label} on ${transaction.occurred_at}`}
      >
        <td className="py-3 pr-4 font-mono text-xs tabular-nums text-muted-foreground">
          {formatTimestamp(Date.parse(transaction.occurred_at))}
        </td>
        <td className="py-3 pr-4">
          <span className="font-medium">{TYPE_VOCABULARY[transaction.type].label}</span>
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
          <td colSpan={4} className="py-4">
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
  onDone,
}: {
  instruments: Instrument[];
  platforms: Platform[];
  revising?: Transaction;
  onDone: () => void;
}) {
  const [type, setType] = useState<TransactionType>(revising?.type ?? "trade");
  const [occurredAt, setOccurredAt] = useState(
    revising ? toInput(revising.occurred_at) : nowForInput(),
  );
  const [note, setNote] = useState(revising?.note ?? "");
  const [legs, setLegs] = useState<DraftLeg[]>(
    revising ? draftsOf(revising) : legTemplate("trade").map(freshLeg),
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

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({
      type,
      occurred_at: new Date(occurredAt).toISOString(),
      note: note.trim() || null,
      legs: legs.map((leg) => ({
        account_id: Number(leg.accountId),
        instrument_id: Number(leg.instrumentId),
        role: leg.role,
        quantity: leg.quantity,
        charged_against: leg.role === "fee" ? leg.chargedAgainst : null,
      })),
    });
  }

  const incomplete =
    legs.length === 0 ||
    legs.some(
      (leg) => !leg.accountId || !leg.instrumentId || !isPositiveDecimal(leg.quantity),
    );

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
            Occurred at
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
