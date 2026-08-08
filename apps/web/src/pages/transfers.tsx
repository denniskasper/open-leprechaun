import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Link2, Undo2, X } from "lucide-react";
import { useState } from "react";
import {
  decideMatch,
  fetchMatching,
  undoDecision,
  type Candidate,
  type Decision,
  type TransferLeg,
} from "@/api/transfer-matches";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { formatQuantity, formatTimestamp } from "@/lib/format";

/** "Kraken · Main" — one side of a move, as the Admin names it. */
export function placeOf(leg: TransferLeg): string {
  return `${leg.platform_name} · ${leg.account_name}`;
}

/** A decimal string with insignificant trailing fraction zeros dropped. */
export function trimDecimal(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

/**
 * The sentence naming the gap between what left and what arrived, or null
 * when nothing went missing. Compared as decimal strings — a quantity never
 * passes through a float.
 */
export function whatWentMissing(outgoing: TransferLeg, incoming: TransferLeg): string | null {
  if (trimDecimal(outgoing.quantity) === trimDecimal(incoming.quantity)) {
    return null;
  }
  return (
    `${formatQuantity(outgoing.quantity)} ${outgoing.instrument_symbol} left and ` +
    `${formatQuantity(incoming.quantity)} arrived — the difference is what the move consumed.`
  );
}

export function TransfersPage() {
  const { data, error, refetch } = useQuery({ queryKey: ["transfers"], queryFn: fetchMatching });

  const confirmed = data?.decisions.filter((decision) => decision.verdict === "confirmed") ?? [];
  const rejected = data?.decisions.filter((decision) => decision.verdict === "rejected") ?? [];
  const nothingYet =
    data &&
    data.candidates.length === 0 &&
    data.unmatched_outgoing.length === 0 &&
    data.unmatched_incoming.length === 0 &&
    data.decisions.length === 0;

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Transfers"
        description="Moving your own assets between your own Accounts is no sale and no purchase. Candidates are proposed by Instrument, quantity and time window; confirming one carries the original cost basis and acquisition date across, so a self-transfer never restarts the Haltefrist."
      />

      {error ? (
        <ErrorState
          title="The matching state could not be loaded"
          detail="The API did not answer with the transfers and proposals."
          onRetry={() => void refetch()}
        />
      ) : nothingYet ? (
        <EmptyState
          icon={ArrowLeftRight}
          title="No transfers to match"
          description="Record a transfer out where assets left and a transfer in where they arrived, and the pair will be proposed here for your decision."
        />
      ) : data ? (
        <div className="space-y-10">
          {data.candidates.length > 0 && (
            <Section
              title="Proposed matches"
              lede="Nothing links itself — each proposal waits for your confirmation."
            >
              <ul className="space-y-4">
                {data.candidates.map((candidate, index) => (
                  <CandidateCard
                    key={`${candidate.outgoing.leg_id}:${candidate.incoming.leg_id}`}
                    candidate={candidate}
                    index={index}
                  />
                ))}
              </ul>
            </Section>
          )}

          {(data.unmatched_outgoing.length > 0 || data.unmatched_incoming.length > 0) && (
            <Section
              title="Unmatched transfers"
              lede="Visible until matched: an unmatched withdrawal is never quietly treated as a disposal, and an unmatched arrival mints no lot."
            >
              <ul className="space-y-px">
                {[
                  ...data.unmatched_outgoing.map((leg) => ({ leg, direction: "out" as const })),
                  ...data.unmatched_incoming.map((leg) => ({ leg, direction: "in" as const })),
                ]
                  .sort((a, b) => a.leg.occurred_at.localeCompare(b.leg.occurred_at))
                  .map(({ leg, direction }, index) => (
                    <UnmatchedRow
                      key={leg.leg_id}
                      leg={leg}
                      direction={direction}
                      index={index}
                    />
                  ))}
              </ul>
            </Section>
          )}

          {confirmed.length > 0 && (
            <Section
              title="Confirmed self-transfers"
              lede="Each link carries the source lots across with their original acquisition dates and bases."
            >
              <ul className="space-y-4">
                {confirmed.map((decision, index) => (
                  <DecisionCard key={decision.id} decision={decision} index={index} />
                ))}
              </ul>
            </Section>
          )}

          {rejected.length > 0 && (
            <Section
              title="Rejected proposals"
              lede="Never proposed again — unless you reconsider."
            >
              <ul className="space-y-px">
                {rejected.map((decision, index) => (
                  <RejectedRow key={decision.id} decision={decision} index={index} />
                ))}
              </ul>
            </Section>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Section({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title}>
      <h2 className="microlabel text-muted-foreground">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{lede}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Invalidate everything a match decision can change. */
function useInvalidateOnDecision() {
  const queryClient = useQueryClient();
  return {
    onSuccess: () =>
      Promise.all(
        ["transfers", "inbox", "transactions"].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      ),
  };
}

/** One side of a move: where, and when. */
function SideBlock({ leg, label, alignRight }: { leg: TransferLeg; label: string; alignRight?: boolean }) {
  return (
    <div className={alignRight ? "text-right" : undefined}>
      <p className="microlabel text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm">{placeOf(leg)}</p>
      <p className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
        {formatTimestamp(Date.parse(leg.occurred_at))}
      </p>
      {leg.note && <p className="mt-1 text-xs text-muted-foreground">{leg.note}</p>}
    </div>
  );
}

/** The moving parcel, riding the rule between the two sides. */
function ParcelStrip({ incoming }: { incoming: TransferLeg }) {
  return (
    <div className="flex items-center gap-3" aria-hidden>
      <div className="h-px flex-1 bg-border" />
      <p className="font-mono text-sm tabular-nums">
        {formatQuantity(incoming.quantity)} {incoming.instrument_symbol}
        <span className="ml-2 text-muted-foreground">→</span>
      </p>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}

function CandidateCard({ candidate, index }: { candidate: Candidate; index: number }) {
  const { outgoing, incoming } = candidate;
  const invalidate = useInvalidateOnDecision();
  const decide = useMutation({
    mutationFn: (verdict: "confirmed" | "rejected") =>
      decideMatch({ out_leg_id: outgoing.leg_id, in_leg_id: incoming.leg_id, verdict }),
    ...invalidate,
  });
  const missing = whatWentMissing(outgoing, incoming);

  return (
    <li
      className="rise rounded-xl border border-border p-5"
      style={{ animationDelay: `${120 + index * 40}ms` }}
      aria-label={`Proposed match: ${formatQuantity(incoming.quantity)} ${incoming.instrument_symbol} from ${placeOf(outgoing)} to ${placeOf(incoming)}`}
    >
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 max-sm:grid-cols-1">
        <SideBlock leg={outgoing} label="Left" />
        <ParcelStrip incoming={incoming} />
        <SideBlock leg={incoming} label="Arrived" alignRight />
      </div>

      {missing && (
        <p className="mt-3 border-t border-border pt-3 text-sm text-muted-foreground">{missing}</p>
      )}
      <MutationAlert mutation={decide} />

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={decide.isPending}
          title="Links the two sides as one self-transfer: the lots the withdrawal consumed arrive with their original acquisition dates and cost bases — the Haltefrist does not restart."
          onClick={() => decide.mutate("confirmed")}
        >
          <Link2 aria-hidden />
          {decide.isPending ? "Deciding…" : "Confirm match"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          disabled={decide.isPending}
          title="Not the same parcel: the pair is never proposed again, and both transfers stay visibly unmatched."
          onClick={() => decide.mutate("rejected")}
        >
          <X aria-hidden />
          Reject
        </Button>
      </div>
    </li>
  );
}

function UnmatchedRow({
  leg,
  direction,
  index,
}: {
  leg: TransferLeg;
  direction: "out" | "in";
  index: number;
}) {
  const Arrow = direction === "out" ? ArrowUpRight : ArrowDownLeft;
  return (
    <li
      className="rise flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border py-3 first:border-t"
      style={{ animationDelay: `${120 + index * 40}ms` }}
      aria-label={`Unmatched transfer ${direction}: ${formatQuantity(leg.quantity)} ${leg.instrument_symbol} at ${placeOf(leg)}`}
    >
      <Arrow aria-hidden className="size-4 self-center text-muted-foreground" />
      <p className="font-mono text-sm tabular-nums">
        {direction === "out" ? "−" : "+"}
        {formatQuantity(leg.quantity)} {leg.instrument_symbol}
      </p>
      <p className="text-sm">{placeOf(leg)}</p>
      <p className="font-mono text-xs tabular-nums text-muted-foreground">
        {formatTimestamp(Date.parse(leg.occurred_at))}
      </p>
      <span className="microlabel ml-auto text-caution">unmatched</span>
    </li>
  );
}

function DecisionCard({ decision, index }: { decision: Decision; index: number }) {
  const { outgoing, incoming } = decision;
  const invalidate = useInvalidateOnDecision();
  const undo = useMutation({ mutationFn: () => undoDecision(decision.id), ...invalidate });
  // Unlinking discards a standing decision, so it asks once: the first press
  // arms the button, the second one acts.
  const [armed, setArmed] = useState(false);

  return (
    <li
      className="rise rounded-xl border border-border p-5"
      style={{ animationDelay: `${120 + index * 40}ms` }}
      aria-label={`Confirmed self-transfer: ${formatQuantity(incoming.quantity)} ${incoming.instrument_symbol} from ${placeOf(outgoing)} to ${placeOf(incoming)}`}
    >
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 max-sm:grid-cols-1">
        <SideBlock leg={outgoing} label="Left" />
        <div className="text-center">
          <ParcelStrip incoming={incoming} />
          <p className="microlabel mt-1 text-signal">linked</p>
        </div>
        <SideBlock leg={incoming} label="Arrived" alignRight />
      </div>

      <MutationAlert mutation={undo} />

      <div className="mt-4">
        <Button
          variant="ghost"
          size="sm"
          className={armed ? "text-alarm" : "text-muted-foreground"}
          disabled={undo.isPending}
          onBlur={() => setArmed(false)}
          title="Unlinks the pair: the carried lots leave the destination and both transfers return to unmatched."
          onClick={() => {
            if (armed) {
              undo.mutate();
            } else {
              setArmed(true);
            }
          }}
        >
          <Undo2 aria-hidden />
          {undo.isPending ? "Unlinking…" : armed ? "Confirm unlink" : "Unlink"}
        </Button>
      </div>
    </li>
  );
}

function RejectedRow({ decision, index }: { decision: Decision; index: number }) {
  const invalidate = useInvalidateOnDecision();
  const undo = useMutation({ mutationFn: () => undoDecision(decision.id), ...invalidate });

  return (
    <li
      className="rise flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border py-3 text-muted-foreground first:border-t"
      style={{ animationDelay: `${120 + index * 40}ms` }}
      aria-label={`Rejected proposal: ${placeOf(decision.outgoing)} to ${placeOf(decision.incoming)}`}
    >
      <p className="font-mono text-sm tabular-nums">
        {formatQuantity(decision.incoming.quantity)} {decision.incoming.instrument_symbol}
      </p>
      <p className="text-sm">
        {placeOf(decision.outgoing)} → {placeOf(decision.incoming)}
      </p>
      <MutationAlert mutation={undo} />
      <Button
        variant="ghost"
        size="sm"
        className="ml-auto text-muted-foreground"
        disabled={undo.isPending}
        title="Forgets the rejection, so the pair can be proposed again."
        onClick={() => undo.mutate()}
      >
        <Undo2 aria-hidden />
        {undo.isPending ? "Reconsidering…" : "Reconsider"}
      </Button>
    </li>
  );
}

function MutationAlert({ mutation }: { mutation: { isError: boolean; error: Error | null } }) {
  return mutation.isError ? (
    <p role="alert" className="mt-3 text-sm text-alarm">
      {mutation.error?.message}
    </p>
  ) : null;
}
