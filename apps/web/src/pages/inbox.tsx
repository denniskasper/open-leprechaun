import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, EyeOff, Inbox, Link2, ShieldAlert } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  classifyInstrument,
  fetchInbox,
  type Classification,
  type InboxItem,
  type WaitingInflow,
} from "@/api/inbox";
import { fetchInstruments, settleAsDeploymentOf, type Deployment } from "@/api/instruments";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { formatNumber, formatRoundedAssetAmount, formatTimestamp } from "@/lib/format";
import { deploymentCandidates, identityOf } from "@/pages/instruments";

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
    formatRoundedAssetAmount(item.unclassified_quantity, item.symbol, locale)
  );
}

/** Where each chain the ledger names shows one of its transactions. */
const EXPLORERS: Record<string, string> = {
  ethereum: "https://etherscan.io/tx/",
  solana: "https://solscan.io/tx/",
  base: "https://basescan.org/tx/",
  bitcoin: "https://mempool.space/tx/",
  bsc: "https://bscscan.com/tx/",
  polygon: "https://polygonscan.com/tx/",
  arbitrum: "https://arbiscan.io/tx/",
  optimism: "https://optimistic.etherscan.io/tx/",
  avalanche: "https://snowtrace.io/tx/",
  tron: "https://tronscan.org/#/transaction/",
};

/** The public page of a chain transaction, or null where the chain or hash is not known. */
export function explorerUrl(
  chain: string | null,
  txHash: string | null,
): string | null {
  if (chain === null || txHash === null) return null;
  const base = EXPLORERS[chain];
  return base ? `${base}${encodeURIComponent(txHash)}` : null;
}

/**
 * The chain an inflow came on where the token has no Deployment there — worth
 * a look: either the issuer mints it there too and the Deployment is missing,
 * or what arrived is a different token wearing the symbol (ADR-0032).
 */
export function undeployedChain(
  chain: string | null,
  type: string,
  deployments: Deployment[],
): string | null {
  if (chain === null || type !== "token") return null;
  return deployments.some((deployment) => deployment.chain === chain)
    ? null
    : chain;
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
        <ul className="measure-list space-y-4">
          {data.map((item, index) => (
            <ArrivalCard key={`${item.instrument_id}:${item.account_id}`} item={item} index={index} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ArrivalCard({ item, index }: { item: InboxItem; index: number }) {
  const [settling, setSettling] = useState<"keep" | "deployment" | null>(null);
  const [showingInflows, setShowingInflows] = useState(false);

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

      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 border-t border-border pt-3">
        <p className="text-sm text-muted-foreground">
          {describeArrivals(item)}
        </p>
        {item.inflows.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="-my-1 h-7 px-2 text-muted-foreground"
            aria-expanded={showingInflows}
            onClick={() => setShowingInflows(!showingInflows)}
          >
            {showingInflows ? "Hide inflows" : "Show inflows"}
          </Button>
        )}
      </div>
      {showingInflows && <InflowList item={item} />}

      {settling === "keep" ? (
        <KeepForm item={item} onDone={() => setSettling(null)} />
      ) : settling === "deployment" ? (
        <DeploymentOfForm item={item} onDone={() => setSettling(null)} />
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSettling("keep")}
          >
            <Check aria-hidden />
            Keep
          </Button>
          {item.type === "token" && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              title="This contract is a token the ledger already holds, minted by its issuer on this chain too."
              onClick={() => setSettling("deployment")}
            >
              <Link2 aria-hidden />
              Same as another token
            </Button>
          )}
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

/**
 * The answer that this unfamiliar contract is a token the ledger already
 * holds, on another chain (ADR-0032). Its inflows then wait under that token,
 * here, for a Keep or a confirmed self-transfer — nothing is settled yet.
 */
function DeploymentOfForm({
  item,
  onDone,
}: {
  item: InboxItem;
  onDone: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const instruments = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });
  const candidates = deploymentCandidates(
    { id: item.instrument_id, symbol: item.symbol },
    instruments.data ?? [],
  );
  const [chosen, setChosen] = useState<number | null>(null);
  const target = chosen ?? candidates[0]?.id ?? null;
  const settle = useMutation({
    mutationFn: (older: number) =>
      settleAsDeploymentOf(item.instrument_id, older),
    onSuccess: () =>
      Promise.all(
        ["inbox", "instruments", "transactions"].map((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        ),
      ),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (target !== null) settle.mutate(target);
  }

  return (
    <form
      onSubmit={submit}
      className="mt-4 rounded-md border border-border p-4"
      aria-label={`Settle ${item.symbol} as a Deployment of another token`}
    >
      <p className="measure-prose text-sm text-muted-foreground">
        Its contract becomes another chain of the token you pick, and these
        inflows wait under that token at {item.account_name}. Only where the
        issuer itself mints it on this chain — a bridged or wrapped version
        stays its own Instrument.
      </p>
      {instruments.error ? (
        <p role="alert" className="mt-3 text-sm text-alarm">
          The tokens could not be loaded to choose from.
        </p>
      ) : instruments.data && candidates.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          No other token is in the ledger yet — add the one this is, then settle
          it here.
        </p>
      ) : (
        <div className="mt-3 space-y-1.5">
          <label
            htmlFor={`${id}-token`}
            className="microlabel block text-muted-foreground"
          >
            Token
          </label>
          <NativeSelect
            id={`${id}-token`}
            value={target ?? ""}
            onChange={(event) => setChosen(Number(event.target.value))}
            disabled={!instruments.data}
          >
            {candidates.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.symbol} · {candidate.name} · {identityOf(candidate)}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      {settle.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {settle.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={settle.isPending || target === null}
        >
          {settle.isPending ? "Settling…" : "Settle as a Deployment"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/**
 * Each inflow a keep would settle, with what its source said about where it
 * came from: when, how much, the chain, the sender, and the transaction on
 * the chain's own explorer. A chain the token has no Deployment on is
 * flagged, never refused.
 */
function InflowList({ item }: { item: InboxItem }) {
  const instruments = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });
  const deployments =
    instruments.data?.find((instrument) => instrument.id === item.instrument_id)
      ?.deployments ?? null;

  return (
    <ul
      className="mt-3 divide-y divide-border border-y border-border"
      aria-label={`Inflows of ${item.symbol} at ${item.account_name}`}
    >
      {item.inflows.map((inflow) => (
        <InflowRow
          key={inflow.transaction_id}
          inflow={inflow}
          symbol={item.symbol}
          undeployed={
            deployments === null
              ? null
              : undeployedChain(inflow.chain, item.type, deployments)
          }
        />
      ))}
    </ul>
  );
}

function InflowRow({
  inflow,
  symbol,
  undeployed,
}: {
  inflow: WaitingInflow;
  symbol: string;
  undeployed: string | null;
}) {
  const link = explorerUrl(inflow.chain, inflow.tx_hash);
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2 text-sm">
      <span className="font-mono text-xs text-muted-foreground tabular-nums">
        {formatTimestamp(Date.parse(inflow.occurred_at))}
      </span>
      <span
        className="font-mono tabular-nums"
        title={`${inflow.quantity} ${symbol}`}
      >
        {formatRoundedAssetAmount(inflow.quantity, symbol)}
      </span>
      <span className="text-muted-foreground">
        {inflow.chain ? `on ${inflow.chain}` : "chain not stated"}
      </span>
      {undeployed && (
        <span
          className="microlabel text-caution"
          title={`This token has no ${undeployed} Deployment. If its issuer mints it there, add the Deployment on Instruments; if not, what arrived is a different token.`}
        >
          no {undeployed} deployment
        </span>
      )}
      {inflow.counterparty_address && (
        <span
          className="font-mono text-xs text-muted-foreground tabular-nums"
          title={inflow.counterparty_address}
        >
          from {abbreviated(inflow.counterparty_address)}
        </span>
      )}
      {link ? (
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          className="ml-auto inline-flex items-center gap-1 underline decoration-muted-foreground/40 underline-offset-4 hover:decoration-foreground"
        >
          View transaction
          <ExternalLink aria-hidden className="size-3.5" />
        </a>
      ) : (
        inflow.tx_hash && (
          <span
            className="ml-auto font-mono text-xs text-muted-foreground tabular-nums"
            title={inflow.tx_hash}
          >
            tx {abbreviated(inflow.tx_hash)}
          </span>
        )
      )}
    </li>
  );
}

function abbreviated(value: string): string {
  return value.length > 14 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
}
