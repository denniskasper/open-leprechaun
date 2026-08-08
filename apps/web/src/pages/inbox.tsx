import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, EyeOff, Inbox, ShieldAlert } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { classifyInstrument, fetchInbox, type Classification, type InboxItem } from "@/api/inbox";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { formatNumber, formatQuantity, formatTimestamp } from "@/lib/format";
import { identityOf } from "@/pages/instruments";

/**
 * The unsolicited inflows a keep decision would settle, in one line — or the
 * honest admission that the pair only ever arrived through deliberate records,
 * so there is nothing for the counter-performance question to settle.
 */
export function describeArrivals(item: InboxItem, locale?: string): string {
  if (item.unclassified_inflow_count === 0) {
    return "No unclassified inflows — recorded by hand, awaiting only the stance.";
  }
  const inflows = item.unclassified_inflow_count === 1 ? "inflow" : "inflows";
  return (
    `${formatNumber(item.unclassified_inflow_count, locale)} unclassified ${inflows} · ` +
    `${formatQuantity(item.unclassified_quantity, locale)} ${item.symbol}`
  );
}

export function InboxPage() {
  const { data, error, refetch } = useQuery({ queryKey: ["inbox"], queryFn: fetchInbox });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Inbox"
        description="Anything that arrived unclassified waits here — recorded, so the ledger still reconciles, but minting no lot until a decision. The default is deny: never a holding silently valued at zero."
      />

      {error ? (
        <ErrorState
          title="The inbox could not be loaded"
          detail="The API did not answer with the unacknowledged arrivals."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="Nothing awaits a decision"
          description="Every Instrument that has arrived carries a stance. New arrivals of anything unacknowledged will wait here."
        />
      ) : data ? (
        <ul className="space-y-4">
          {data.map((item, index) => (
            <ArrivalCard key={`${item.instrument_id}:${item.account_id}`} item={item} index={index} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ArrivalCard({ item, index }: { item: InboxItem; index: number }) {
  const [keeping, setKeeping] = useState(false);

  return (
    <li
      className="rise rounded-xl border border-border p-5"
      style={{ animationDelay: `${120 + index * 40}ms` }}
      aria-label={`${item.symbol} at ${item.platform_name} · ${item.account_name}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-base tabular-nums">
            {item.symbol}
            <span className="microlabel ml-2 text-caution">unacknowledged</span>
          </p>
          <p className="mt-0.5 text-sm">{item.name}</p>
          <p
            className="mt-1 font-mono text-xs tabular-nums text-muted-foreground"
            title={item.contract_address ?? undefined}
          >
            {identityOf(item)}
          </p>
        </div>
        <div className="text-right">
          <p className="microlabel text-muted-foreground">Arrived at</p>
          <p className="mt-0.5 text-sm">
            {item.platform_name} · {item.account_name}
          </p>
          <p className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
            last {formatTimestamp(Date.parse(item.last_inflow_at))}
          </p>
        </div>
      </div>

      <p className="mt-3 border-t border-border pt-3 text-sm text-muted-foreground">
        {describeArrivals(item)}
      </p>

      {keeping ? (
        <KeepForm item={item} onDone={() => setKeeping(false)} />
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setKeeping(true)}>
            <Check aria-hidden />
            Keep
          </Button>
          <IgnoreButton item={item} />
          <DangerousButton item={item} />
        </div>
      )}
    </li>
  );
}

/** Invalidate everything a classification can change, whatever the outcome. */
function useClassify(item: InboxItem) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (classification: Classification) =>
      classifyInstrument(item.instrument_id, classification),
    onSuccess: () =>
      Promise.all(
        ["inbox", "instruments", "transactions"].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      ),
  });
}

function KeepForm({ item, onDone }: { item: InboxItem; onDone: () => void }) {
  // The question acknowledging asks, defaulting to no (ADR-0012).
  const [counterPerformance, setCounterPerformance] = useState(false);
  const classify = useClassify(item);
  const id = useId();

  function submit(event: FormEvent) {
    event.preventDefault();
    classify.mutate({
      stance: "kept",
      account_id: item.account_id,
      received_for_counter_performance: counterPerformance,
    });
  }

  const asksTheQuestion = item.unclassified_inflow_count > 0;

  return (
    <form
      onSubmit={submit}
      className="mt-4 rounded-md border border-border p-4"
      aria-label={`Keep ${item.symbol} at ${item.account_name}`}
    >
      {asksTheQuestion && (
        <fieldset>
          <legend className="text-sm font-medium">
            Was this received for a counter-performance?
          </legend>
          <div className="mt-2 space-y-2">
            <label htmlFor={`${id}-no`} className="flex items-baseline gap-2 text-sm">
              <input
                id={`${id}-no`}
                type="radio"
                name={`${id}-question`}
                className="accent-signal"
                checked={!counterPerformance}
                onChange={() => setCounterPerformance(false)}
              />
              <span>
                No — a windfall.{" "}
                <span className="text-muted-foreground">
                  Nothing was given for it, so it is no income and settles at zero basis.
                </span>
              </span>
            </label>
            <label htmlFor={`${id}-yes`} className="flex items-baseline gap-2 text-sm">
              <input
                id={`${id}-yes`}
                type="radio"
                name={`${id}-question`}
                className="accent-signal"
                checked={counterPerformance}
                onChange={() => setCounterPerformance(true)}
              />
              <span>
                Yes — an airdrop for a Leistung.{" "}
                <span className="text-muted-foreground">
                  §22 EStG income, valued at market value on receipt.
                </span>
              </span>
            </label>
          </div>
        </fieldset>
      )}
      {classify.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {classify.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit" size="sm" disabled={classify.isPending}>
          {classify.isPending ? "Keeping…" : `Keep at ${item.account_name}`}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function IgnoreButton({ item }: { item: InboxItem }) {
  const classify = useClassify(item);

  return (
    <Button
      variant="ghost"
      size="sm"
      className="text-muted-foreground"
      disabled={classify.isPending}
      title="Ignored at this Account only: the position stays visible with a warning, mints no lot, and while ignored everywhere the Instrument can never acquire a price source."
      onClick={() => classify.mutate({ stance: "ignored", account_id: item.account_id })}
    >
      <EyeOff aria-hidden />
      {classify.isPending ? "Ignoring…" : "Ignore"}
    </Button>
  );
}

function DangerousButton({ item }: { item: InboxItem }) {
  // Global and severe, so it asks once, inline: the first press arms the
  // button, the second one acts — the same gesture as removing a Transaction.
  const [armed, setArmed] = useState(false);
  const classify = useClassify(item);

  return (
    <Button
      variant="ghost"
      size="sm"
      className={armed ? "text-alarm" : "text-muted-foreground"}
      disabled={classify.isPending}
      onBlur={() => setArmed(false)}
      title="Dangerous everywhere, not just here: a token whose approval drains a wallet is dangerous at every Account. Stays visible, mints no lot, never acquires a price source."
      onClick={() => {
        if (armed) {
          classify.mutate({ stance: "dangerous" });
        } else {
          setArmed(true);
        }
      }}
    >
      <ShieldAlert aria-hidden />
      {classify.isPending ? "Marking…" : armed ? "Confirm — dangerous everywhere" : "Dangerous"}
    </Button>
  );
}
