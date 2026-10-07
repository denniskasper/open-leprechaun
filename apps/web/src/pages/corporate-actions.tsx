import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Eye, Split, Undo2 } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { Link } from "react-router";
import {
  applyCorporateAction,
  type CorporateAction,
  type CorporateActionKind,
  fetchCorporateActions,
  type LotEffect,
  type LotState,
  markCorporateActionReviewed,
  type NewCorporateAction,
  previewCorporateAction,
  removeCorporateAction,
} from "@/api/corporate-actions";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import { fetchPlatforms } from "@/api/platforms";
import { DECIMAL_PATTERN } from "@/api/transactions";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Amount } from "@/components/patterns/figure";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatMoneyExact, formatQuantity, formatTimestamp } from "@/lib/format";
import { trimDecimal } from "@/pages/transfers";

/** Each kind as the Admin reads it, with the one sentence of what it does. */
export const KIND_WORDS: Record<CorporateActionKind, { label: string; effect: string }> = {
  split: {
    label: "Split or reverse split",
    effect:
      "Rescales the quantity of every open lot; total basis and acquisition dates stand, and nothing taxable happens.",
  },
  capital_return: {
    label: "Capital return",
    effect:
      "Takes the amount per unit off the basis of every open lot instead of booking income. Flagged for manual review where it exceeds a lot's basis, or meets one still awaiting valuation.",
  },
  spin_off: {
    label: "Spin-off",
    effect:
      "Mints lots of the spun-off Instrument carrying the share of basis you supply, under the original acquisition dates. Flagged for manual review.",
  },
  merger: {
    label: "Merger",
    effect:
      "Moves every open lot into the target Instrument at the exchange ratio you supply, basis and acquisition dates carried. Flagged for manual review.",
  },
};

/** What the form holds while the Admin states an event — every field as typed. */
export interface ActionDraft {
  kind: CorporateActionKind;
  instrumentId: string;
  effectiveOn: string;
  unitsNew: string;
  unitsOld: string;
  targetInstrumentId: string;
  basisShare: string;
  amountPerUnit: string;
  note: string;
}

function positive(value: string): boolean {
  return DECIMAL_PATTERN.test(value) && /[1-9]/.test(value);
}

/**
 * The request a draft states, carrying exactly its kind's fields — or null
 * while something its kind needs is missing or malformed. The effective day
 * opens at local midnight: a sale on that day is already in the new units.
 */
export function statedAction(draft: ActionDraft): NewCorporateAction | null {
  if (!draft.instrumentId || !draft.effectiveOn) {
    return null;
  }
  const effectiveAt = new Date(`${draft.effectiveOn}T00:00:00`);
  if (Number.isNaN(effectiveAt.getTime())) {
    return null;
  }
  const action: NewCorporateAction = {
    kind: draft.kind,
    instrument_id: Number(draft.instrumentId),
    effective_at: effectiveAt.toISOString(),
    ...(draft.note.trim() && { note: draft.note.trim() }),
  };
  if (draft.kind === "capital_return") {
    return positive(draft.amountPerUnit)
      ? { ...action, amount_per_unit_eur: draft.amountPerUnit }
      : null;
  }
  if (!positive(draft.unitsNew) || !positive(draft.unitsOld)) {
    return null;
  }
  action.units_new = draft.unitsNew;
  action.units_old = draft.unitsOld;
  if (draft.kind === "split") {
    return action;
  }
  if (!draft.targetInstrumentId || draft.targetInstrumentId === draft.instrumentId) {
    return null;
  }
  action.target_instrument_id = Number(draft.targetInstrumentId);
  if (draft.kind === "merger") {
    return action;
  }
  // A share of nothing is no spin-off, and a share of everything is a merger.
  if (!positive(draft.basisShare) || !/^0\.\d+$/.test(draft.basisShare)) {
    return null;
  }
  return { ...action, basis_share: draft.basisShare };
}

/** Whether a split's ratio shrinks the unit count — a reverse split. */
function shrinks(unitsNew: string, unitsOld: string): boolean {
  return Number(unitsNew) < Number(unitsOld);
}

/** A ratio side or share as stated, through the one quantity format. */
function stated(value: string | null): string {
  return formatQuantity(trimDecimal(value ?? "0"));
}

/** "2 for 1 split", "1 SHL for every 4 held · share of basis 0.2" — the event in a line. */
export function termsOf(action: CorporateAction, symbolOf: (id: number) => string): string {
  const ratio = `${stated(action.units_new)} for ${stated(action.units_old)}`;
  switch (action.kind) {
    case "split":
      return shrinks(action.units_new ?? "", action.units_old ?? "")
        ? `${ratio} reverse split`
        : `${ratio} split`;
    case "capital_return":
      return `${formatMoneyExact(action.amount_per_unit_eur ?? "0", "EUR")} per unit off the basis`;
    case "merger":
      return `${ratio} into ${symbolOf(action.target_instrument_id ?? 0)}`;
    case "spin_off":
      return (
        `${stated(action.units_new)} ${symbolOf(action.target_instrument_id ?? 0)}` +
        ` for every ${stated(action.units_old)} held · share of basis ` +
        stated(action.basis_share)
      );
  }
}

const EMPTY_DRAFT: ActionDraft = {
  kind: "split",
  instrumentId: "",
  effectiveOn: "",
  unitsNew: "",
  unitsOld: "",
  targetInstrumentId: "",
  basisShare: "",
  amountPerUnit: "",
  note: "",
};

/** Everything a Corporate Action can change on another screen. */
const AFFECTED_QUERIES = ["corporate-actions", "holdings", "instruments"];

export function CorporateActionsPage() {
  const actions = useQuery({ queryKey: ["corporate-actions"], queryFn: fetchCorporateActions });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: fetchInstruments });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });

  const symbols = new Map(instruments.data?.map((entry) => [entry.id, entry.symbol]));
  const symbolOf = (id: number) => symbols.get(id) ?? `instrument:${id}`;
  const places = new Map(
    platforms.data?.flatMap((platform) =>
      platform.accounts.map((account) => [account.id, `${platform.name} · ${account.name}`]),
    ),
  );
  const placeOf = (id: number) => places.get(id) ?? `account:${id}`;
  // An issuer event acts on a security or a crypto asset — never on cash.
  const holdable = instruments.data?.filter((entry) => entry.family !== "cash") ?? [];
  const failed = actions.error ?? instruments.error ?? platforms.error;

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Corporate actions"
        description="Issuer events that change a holding without a trade. Each one is recorded as an event, never as an edit to lots: preview what it does to the lots open on its day, apply it, and reverse it by removing it — the lots rebuild from the ledger."
      />

      {failed ? (
        <ErrorState
          title="Corporate actions could not be loaded"
          detail="The API did not answer with the recorded events, the Instruments they act on and the Accounts that hold them."
          onRetry={() => {
            void actions.refetch();
            void instruments.refetch();
            void platforms.refetch();
          }}
        />
      ) : actions.data && instruments.data && platforms.data ? (
        <>
          {holdable.length === 0 && (
            <p role="status" className="measure-prose text-sm text-muted-foreground">
              No Instrument is in the ledger yet, so there is nothing for an event to act on —{" "}
              <Link to="/instruments" className="underline underline-offset-2">
                add the share or fund on Instruments
              </Link>{" "}
              first.
            </p>
          )}
          <RecordForm instruments={holdable} symbolOf={symbolOf} placeOf={placeOf} />

          <section aria-label="Recorded events">
            <h2 className="microlabel text-muted-foreground">Recorded events</h2>
            <p className="mt-1 measure-prose text-sm text-muted-foreground">
              Newest effect first, each with the lots it touched as they stood on its day.
            </p>
            <div className="mt-4 measure-list">
              {actions.data.length === 0 ? (
                <EmptyState
                  icon={Split}
                  title="No corporate actions recorded"
                  description="When an issuer splits a share, returns capital, spins a business off or merges, state the event above — share counts and cost basis follow without editing a lot by hand."
                />
              ) : (
                <ul className="space-y-4">
                  {actions.data.map((action, index) => (
                    <ActionCard
                      key={action.id}
                      action={action}
                      index={index}
                      symbolOf={symbolOf}
                      placeOf={placeOf}
                    />
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function useInvalidateAffected() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      AFFECTED_QUERIES.map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    );
}

function Field({
  id,
  label,
  className,
  children,
}: {
  id: string;
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`space-y-2 ${className ?? ""}`}>
      <label htmlFor={id} className="microlabel block text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

function RecordForm({
  instruments,
  symbolOf,
  placeOf,
}: {
  instruments: Instrument[];
  symbolOf: (id: number) => string;
  placeOf: (id: number) => string;
}) {
  const id = useId();
  const [draft, setDraft] = useState<ActionDraft>(EMPTY_DRAFT);
  const invalidate = useInvalidateAffected();
  const preview = useMutation({ mutationFn: previewCorporateAction });
  const apply = useMutation({
    mutationFn: applyCorporateAction,
    onSuccess: () => {
      setDraft(EMPTY_DRAFT);
      preview.reset();
      return invalidate();
    },
  });

  const request = statedAction(draft);
  const changesUnits = draft.kind !== "capital_return";
  const namesTarget = draft.kind === "spin_off" || draft.kind === "merger";
  const decimal = { inputMode: "decimal" as const, pattern: DECIMAL_PATTERN.source, required: true };

  // A preview answers for the event as it was stated; any change to the
  // draft makes it stale, so it goes rather than vouch for something else.
  function edit(change: Partial<ActionDraft>) {
    setDraft((current) => ({ ...current, ...change }));
    preview.reset();
    apply.reset();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (request) {
      preview.mutate(request);
    }
  }

  return (
    <section aria-label="Record an event" className="rise" style={{ animationDelay: "80ms" }}>
      <h2 className="microlabel text-muted-foreground">Record an event</h2>
      <p className="mt-1 measure-prose text-sm text-muted-foreground">{KIND_WORDS[draft.kind].effect}</p>

      <form onSubmit={submit} className="mt-4 measure-form rounded-xl border border-border p-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field id={`${id}-kind`} label="Kind">
            <NativeSelect
              id={`${id}-kind`}
              value={draft.kind}
              onChange={(event) => edit({ kind: event.target.value as CorporateActionKind })}
            >
              {Object.entries(KIND_WORDS).map(([kind, words]) => (
                <option key={kind} value={kind} className="bg-background">
                  {words.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={`${id}-instrument`} label="Instrument" className="min-w-48 flex-1">
            <InstrumentSelect
              id={`${id}-instrument`}
              value={draft.instrumentId}
              instruments={instruments}
              onChange={(instrumentId) => edit({ instrumentId })}
            />
          </Field>
          <Field id={`${id}-effective`} label="Effective on">
            <Input
              id={`${id}-effective`}
              type="date"
              required
              value={draft.effectiveOn}
              onChange={(event) => edit({ effectiveOn: event.target.value })}
              className="font-mono tabular-nums"
            />
          </Field>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          {changesUnits && (
            <>
              <Field
                id={`${id}-new`}
                label={namesTarget ? "Target units received" : "New units"}
                className="w-40"
              >
                <Input
                  id={`${id}-new`}
                  {...decimal}
                  value={draft.unitsNew}
                  onChange={(event) => edit({ unitsNew: event.target.value })}
                  className="font-mono tabular-nums"
                />
              </Field>
              <Field id={`${id}-old`} label="For every units held" className="w-40">
                <Input
                  id={`${id}-old`}
                  {...decimal}
                  value={draft.unitsOld}
                  onChange={(event) => edit({ unitsOld: event.target.value })}
                  className="font-mono tabular-nums"
                />
              </Field>
            </>
          )}
          {namesTarget && (
            <Field id={`${id}-target`} label="Target Instrument" className="min-w-48 flex-1">
              <InstrumentSelect
                id={`${id}-target`}
                value={draft.targetInstrumentId}
                instruments={instruments.filter((entry) => String(entry.id) !== draft.instrumentId)}
                onChange={(targetInstrumentId) => edit({ targetInstrumentId })}
              />
            </Field>
          )}
          {draft.kind === "spin_off" && (
            <Field id={`${id}-share`} label="Share of basis moved (fraction of one)" className="w-56">
              <Input
                id={`${id}-share`}
                {...decimal}
                placeholder="0.2"
                value={draft.basisShare}
                onChange={(event) => edit({ basisShare: event.target.value })}
                className="font-mono tabular-nums"
              />
            </Field>
          )}
          {draft.kind === "capital_return" && (
            <Field id={`${id}-amount`} label="Amount per unit (EUR)" className="w-48">
              <Input
                id={`${id}-amount`}
                {...decimal}
                value={draft.amountPerUnit}
                onChange={(event) => edit({ amountPerUnit: event.target.value })}
                className="font-mono tabular-nums"
              />
            </Field>
          )}
          <Field id={`${id}-note`} label="Note" className="min-w-48 flex-1">
            <Input
              id={`${id}-note`}
              value={draft.note}
              onChange={(event) => edit({ note: event.target.value })}
            />
          </Field>
        </div>

        <MutationAlert mutation={preview} />

        <div className="mt-4">
          <Button type="submit" variant="outline" size="sm" disabled={!request || preview.isPending}>
            <Eye aria-hidden />
            {preview.isPending ? "Previewing…" : "Preview affected lots"}
          </Button>
        </div>

        {preview.data && request && (
          <div className="mt-5 border-t border-border pt-5" aria-live="polite">
            <p className="microlabel text-muted-foreground">Preview — nothing is applied yet</p>
            <p className="mt-1 font-mono text-sm tabular-nums">
              {symbolOf(preview.data.instrument_id)} · {termsOf(preview.data, symbolOf)}
            </p>
            {preview.data.needs_review && <ReviewNotice />}
            <LotTable lots={preview.data.lots} symbolOf={symbolOf} placeOf={placeOf} />
            <MutationAlert mutation={apply} />
            <div className="mt-4">
              <Button size="sm" disabled={apply.isPending} onClick={() => apply.mutate(request)}>
                <Check aria-hidden />
                {apply.isPending ? "Applying…" : "Apply"}
              </Button>
            </div>
          </div>
        )}
      </form>
    </section>
  );
}

function InstrumentSelect({
  id,
  value,
  instruments,
  onChange,
}: {
  id: string;
  value: string;
  instruments: Instrument[];
  onChange: (value: string) => void;
}) {
  return (
    <NativeSelect
      id={id}
      required
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full"
    >
      <option value="" className="bg-background">
        Choose…
      </option>
      {instruments.map((entry) => (
        <option key={entry.id} value={entry.id} className="bg-background">
          {entry.symbol} — {entry.name}
          {entry.isin ? ` (${entry.isin})` : ""}
        </option>
      ))}
    </NativeSelect>
  );
}

function ReviewNotice() {
  return (
    <p className="mt-3 text-sm text-caution">
      Flagged for manual review: how this event is taxed turns on facts the ledger does not hold.
      The figures follow the ratio you supplied — the application asserts no treatment of its own.
    </p>
  );
}

function ActionCard({
  action,
  index,
  symbolOf,
  placeOf,
}: {
  action: CorporateAction;
  index: number;
  symbolOf: (id: number) => string;
  placeOf: (id: number) => string;
}) {
  const invalidate = useInvalidateAffected();
  const actionId = action.id ?? 0;
  const review = useMutation({
    mutationFn: () => markCorporateActionReviewed(actionId),
    onSuccess: invalidate,
  });
  const reverse = useMutation({
    mutationFn: () => removeCorporateAction(actionId),
    onSuccess: invalidate,
  });
  // Reversal discards a recorded event, so it asks once: the first press
  // arms the button, the second one acts.
  const [armed, setArmed] = useState(false);

  return (
    <li
      className="rise rounded-xl border border-border p-5"
      style={{ animationDelay: `${160 + index * 40}ms` }}
      aria-label={`${KIND_WORDS[action.kind].label}: ${symbolOf(action.instrument_id)}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="font-medium">{symbolOf(action.instrument_id)}</p>
        <p className="font-mono text-sm tabular-nums">{termsOf(action, symbolOf)}</p>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          {formatTimestamp(Date.parse(action.effective_at))}
        </p>
        {action.needs_review ? (
          <span className="microlabel ml-auto text-caution">manual review</span>
        ) : action.reviewed_at ? (
          <span className="microlabel ml-auto text-signal">reviewed</span>
        ) : null}
      </div>
      {action.note && <p className="mt-1 text-sm text-muted-foreground">{action.note}</p>}
      {action.needs_review && <ReviewNotice />}

      <LotTable lots={action.lots} symbolOf={symbolOf} placeOf={placeOf} />

      <MutationAlert mutation={review} />
      <MutationAlert mutation={reverse} />

      <div className="mt-4 flex flex-wrap gap-2">
        {action.needs_review && (
          <Button
            variant="outline"
            size="sm"
            disabled={review.isPending}
            title="You have checked the event against the issuer's or broker's statement and stand by the ratio. No figure changes."
            onClick={() => review.mutate()}
          >
            <Check aria-hidden />
            {review.isPending ? "Marking…" : "Mark reviewed"}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className={armed ? "text-alarm" : "text-muted-foreground"}
          disabled={reverse.isPending}
          onBlur={() => setArmed(false)}
          title="Removes the event: every lot is rebuilt from the ledger as if it had never been recorded."
          onClick={() => {
            if (armed) {
              reverse.mutate();
            } else {
              setArmed(true);
            }
          }}
        >
          <Undo2 aria-hidden />
          {reverse.isPending ? "Reversing…" : armed ? "Confirm reversal" : "Reverse"}
        </Button>
      </div>
    </li>
  );
}

/** One lot's holding at one moment: quantity of what, at which basis. */
function StateCell({ state, symbolOf }: { state: LotState; symbolOf: (id: number) => string }) {
  return (
    <p className="font-mono text-sm tabular-nums">
      <Amount value={state.quantity} symbol={symbolOf(state.instrument_id)} />
      <span className="ml-3 text-muted-foreground">
        {state.basis_eur === null ? "basis awaiting valuation" : formatMoneyExact(state.basis_eur, "EUR")}
      </span>
    </p>
  );
}

/** The before and after of every lot an event touches. */
function LotTable({
  lots,
  symbolOf,
  placeOf,
}: {
  lots: LotEffect[];
  symbolOf: (id: number) => string;
  placeOf: (id: number) => string;
}) {
  if (lots.length === 0) {
    return (
      <p className="mt-4 border-t border-border pt-3 text-sm text-muted-foreground">
        No lot was open on that day — the event touches nothing as the ledger stands. Check the
        Instrument and the effective date, or record the purchase that opens the lot first.
      </p>
    );
  }
  return (
    <ul className="mt-4" aria-label="Affected lots">
      {lots.map((lot) => (
        <li
          key={`${lot.account_id}:${lot.acquired_at}:${lot.before.quantity}:${lot.before.basis_eur}`}
          className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto_minmax(0,1.3fr)] items-center gap-x-4 gap-y-1 border-b border-border py-3 first:border-t max-md:grid-cols-1"
        >
          <div>
            <p className="text-sm">{placeOf(lot.account_id)}</p>
            <p className="font-mono text-xs tabular-nums text-muted-foreground">
              acquired {formatTimestamp(Date.parse(lot.acquired_at))}
            </p>
          </div>
          <StateCell state={lot.before} symbolOf={symbolOf} />
          <ArrowRight aria-label="becomes" className="size-4 text-muted-foreground max-md:hidden" />
          <div className="space-y-1">
            {lot.after.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Leaves the cost basis — the target stands ignored or dangerous here.
              </p>
            ) : (
              lot.after.map((state) => (
                <StateCell key={state.instrument_id} state={state} symbolOf={symbolOf} />
              ))
            )}
            {/[1-9]/.test(lot.excess_eur) && (
              <p className="text-xs text-caution">
                {formatMoneyExact(lot.excess_eur, "EUR")} returned beyond this lot's basis
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function MutationAlert({ mutation }: { mutation: { isError: boolean; error: Error | null } }) {
  return mutation.isError ? (
    <p role="alert" className="mt-3 text-sm text-alarm">
      {mutation.error?.message}
    </p>
  ) : null;
}
