import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, KeyRound, Plus, RefreshCw, ShieldCheck, Trash2, Zap } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  fetchConnections,
  fetchVenues,
  pairAccount,
  registerConnection,
  removeConnection,
  syncConnection,
  testConnection,
  type AdapterStatus,
  type Connection,
  type KindSyncResult,
  type KindTestResult,
  type Venue,
} from "@/api/connections";
import { fetchPlatforms, type Account, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatNumber, formatTimestamp } from "@/lib/format";

/**
 * The standing rule, stated wherever a credential is entered: every scope in
 * the venue registry is read-only, and the application never holds a
 * credential that could move funds.
 */
export const READ_ONLY_RULE =
  "Read-only, always. Open Leprechaun never trades and never withdraws, so the key must not be able to either.";

export interface PlatformGroup {
  platform: Platform;
  connections: Connection[];
}

/**
 * Connections grouped under the Platform they link to, in the platform list's
 * own order; a Platform without any is omitted — the platforms screen already
 * shows it.
 */
export function groupByPlatform(
  connections: Connection[],
  platforms: Platform[],
): PlatformGroup[] {
  return platforms
    .map((platform) => ({
      platform,
      connections: connections.filter((connection) => connection.platform_id === platform.id),
    }))
    .filter((group) => group.connections.length > 0);
}

/** "Never used yet", or when the credential last opened the venue. */
export function describeLastUse(lastUsedAt: string | null, locale?: string): string {
  return lastUsedAt === null
    ? "Never used yet"
    : `Last used ${formatTimestamp(Date.parse(lastUsedAt), locale)}`;
}

/** A kind that has failed since it last worked wears the alarm colour. */
export function statusTone(status: AdapterStatus): "signal" | "alarm" {
  return status.last_error === null ? "signal" : "alarm";
}

/**
 * Every adapter kind a Connection shows a line for: the kinds the venue's
 * adapters serve, then any further kind a recorded status or pairing already
 * names — nothing recorded is ever hidden, even for a kind that no longer
 * ships.
 */
export function kindsOf(connection: Connection, venue: Venue | undefined): string[] {
  const kinds = [...(venue?.adapter_kinds ?? [])];
  for (const named of [
    ...connection.statuses.map((status) => status.adapter_kind),
    ...connection.pairings.map((pairing) => pairing.adapter_kind),
  ]) {
    if (!kinds.includes(named)) kinds.push(named);
  }
  return kinds;
}

function count(quantity: number, noun: string, locale?: string): string {
  return `${formatNumber(quantity, locale)} ${quantity === 1 ? noun : `${noun}s`}`;
}

/** One kind's test outcome as the line under the kind states it. */
export function describeTestResult(result: KindTestResult): string {
  return result.error ?? result.detail ?? "Tested.";
}

/**
 * One kind's sync outcome in words: what was new, what was already known —
 * and beside an error, whatever still landed before the refusal.
 */
export function describeSyncResult(result: KindSyncResult, locale?: string): string {
  const parts: string[] = [];
  if (result.futures) {
    parts.push(count(result.futures.new_fills, "new fill", locale));
    parts.push(count(result.futures.new_funding, "new funding payment", locale));
  }
  if (result.imported) {
    parts.push(count(result.imported.created, "row", locale) + " imported");
    if (result.imported.duplicates > 0) {
      parts.push(`${formatNumber(result.imported.duplicates, locale)} already known`);
    }
    if (result.imported.skipped > 0) {
      parts.push(`${formatNumber(result.imported.skipped, locale)} skipped`);
    }
  }
  const landed = parts.join(" · ");
  if (result.error) {
    return landed ? `${result.error} (${landed} before the refusal)` : result.error;
  }
  if (result.covered_days !== null) {
    return landed
      ? `${landed} · covering the last ${count(result.covered_days, "day", locale)}`
      : `Nothing to pull — the last ${count(result.covered_days, "day", locale)} are covered.`;
  }
  return landed || "Nothing to pull for this kind.";
}

export function ConnectionsPage() {
  const connections = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const venues = useQuery({ queryKey: ["connection-venues"], queryFn: fetchVenues });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: fetchPlatforms });
  const [adding, setAdding] = useState(false);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Settings"
        title="Connections"
        description="The credentialed link to each venue account. A credential is encrypted the moment it arrives and is never shown again — what remains is a label, a fingerprint and when it was last used."
        actions={
          <Button onClick={() => setAdding((open) => !open)}>
            <Plus aria-hidden />
            Add Connection
          </Button>
        }
      />

      {adding &&
        venues.data &&
        platforms.data &&
        (platforms.data.length > 0 ? (
          <AddConnectionForm
            venues={venues.data}
            platforms={platforms.data}
            onDone={() => setAdding(false)}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            A Connection links to a Platform — register the venue as a Platform first.
          </p>
        ))}

      {connections.error || venues.error || platforms.error ? (
        <ErrorState
          title="The connections could not be loaded"
          detail="The API did not answer with the connections, venues or platforms."
          onRetry={() => {
            for (const query of [connections, venues, platforms]) {
              if (query.error) void query.refetch();
            }
          }}
        />
      ) : connections.data && connections.data.length === 0 && !adding ? (
        <EmptyState
          icon={KeyRound}
          title="No Connections yet"
          description="Enter a venue account's API credentials once — encrypted at rest, never displayed again — and every kind of data that venue serves syncs through the one Connection."
          action={
            <Button variant="outline" onClick={() => setAdding(true)}>
              <Plus aria-hidden />
              Add the first Connection
            </Button>
          }
        />
      ) : connections.data && platforms.data && venues.data ? (
        <div className="space-y-12">
          {groupByPlatform(connections.data, platforms.data).map((group, index) => (
            <PlatformSection
              key={group.platform.id}
              group={group}
              venues={venues.data}
              index={index}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PlatformSection({
  group,
  venues,
  index,
}: {
  group: PlatformGroup;
  venues: Venue[];
  index: number;
}) {
  return (
    <section
      className="rise"
      style={{ animationDelay: `${120 + index * 60}ms` }}
      aria-label={group.platform.name}
    >
      <div className="flex items-center gap-2.5 border-b border-border pb-2.5">
        <h2 className="microlabel text-muted-foreground">{group.platform.name}</h2>
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
          {group.connections.length}
        </span>
      </div>
      <div className="divide-y divide-border">
        {group.connections.map((connection) => (
          <ConnectionRow
            key={connection.id}
            connection={connection}
            accounts={group.platform.accounts}
            venue={venues.find((venue) => venue.venue === connection.venue)}
          />
        ))}
      </div>
    </section>
  );
}

function ConnectionRow({
  connection,
  accounts,
  venue,
}: {
  connection: Connection;
  accounts: Account[];
  venue: Venue | undefined;
}) {
  const [confirming, setConfirming] = useState(false);
  const [outcomes, setOutcomes] = useState<Record<string, { ok: boolean; text: string }>>({});
  const queryClient = useQueryClient();
  const kinds = kindsOf(connection, venue);

  const remove = useMutation({
    mutationFn: () => removeConnection(connection.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  function recordOutcomes<Result extends { adapter_kind: string; ok: boolean }>(
    describe: (result: Result) => string,
  ) {
    return (results: Result[]) => {
      setOutcomes(
        Object.fromEntries(
          results.map((result) => [
            result.adapter_kind,
            { ok: result.ok, text: describe(result) },
          ]),
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    };
  }

  const test = useMutation({
    mutationFn: () => testConnection(connection.id),
    onSuccess: recordOutcomes(describeTestResult),
  });

  const sync = useMutation({
    mutationFn: () => syncConnection(connection.id),
    onSuccess: recordOutcomes((result: KindSyncResult) => describeSyncResult(result)),
  });

  const busy = test.isPending || sync.isPending;

  return (
    <article className="py-4" aria-label={connection.label}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h3 className="text-base font-medium">{connection.label}</h3>
        <span
          className="inline-flex items-baseline gap-1.5 font-mono text-xs tabular-nums text-muted-foreground"
          title="A digest of the API key — all that is ever shown of it."
        >
          <Fingerprint aria-hidden className="size-3.5 self-center" />
          {connection.fingerprint}
        </span>
        <span className="text-xs text-muted-foreground">{describeLastUse(connection.last_used_at)}</span>
        <span className="ml-auto flex gap-2">
          {kinds.length > 0 && (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                disabled={busy}
                onClick={() => test.mutate()}
              >
                <Zap aria-hidden />
                {test.isPending ? "Testing…" : "Test"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                disabled={busy}
                onClick={() => sync.mutate()}
              >
                <RefreshCw aria-hidden className={sync.isPending ? "animate-spin" : undefined} />
                {sync.isPending ? "Syncing…" : "Sync"}
              </Button>
            </>
          )}
          {confirming ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="text-alarm"
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "Removing…" : "Remove for good"}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setConfirming(true)}
            >
              <Trash2 aria-hidden />
              Remove
            </Button>
          )}
        </span>
      </div>

      {kinds.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {kinds.map((kind) => (
            <KindLine
              key={kind}
              kind={kind}
              connection={connection}
              accounts={accounts}
              outcome={outcomes[kind]}
            />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">
          No adapter ships for this venue yet — testing and syncing arrive with it.
        </p>
      )}
      {(remove.error || test.error || sync.error) && (
        <p role="alert" className="mt-2 text-sm text-alarm">
          {(remove.error ?? test.error ?? sync.error)?.message}
        </p>
      )}
    </article>
  );
}

/**
 * One adapter kind: its tone dot, the Account it writes into, and its latest
 * outcome — the just-answered test or sync where there is one, the recorded
 * status otherwise.
 */
function KindLine({
  kind,
  connection,
  accounts,
  outcome,
}: {
  kind: string;
  connection: Connection;
  accounts: Account[];
  outcome: { ok: boolean; text: string } | undefined;
}) {
  const queryClient = useQueryClient();
  const status = connection.statuses.find((entry) => entry.adapter_kind === kind);
  const pairing = connection.pairings.find((entry) => entry.adapter_kind === kind);

  const pair = useMutation({
    mutationFn: (accountId: number) => pairAccount(connection.id, kind, accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  const tone = outcome ? (outcome.ok ? "signal" : "alarm") : status ? statusTone(status) : null;

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs">
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${
          tone === "signal" ? "bg-signal" : tone === "alarm" ? "bg-alarm" : "bg-border"
        }`}
      />
      <span className="w-16">{kind}</span>
      {accounts.length > 0 ? (
        <NativeSelect
          aria-label={`Account for ${kind}`}
          className="h-7 w-auto min-w-36 text-xs"
          value={pairing?.account_id ?? ""}
          disabled={pair.isPending}
          onChange={(event) => pair.mutate(Number(event.target.value))}
        >
          <option value="" disabled className="bg-background text-foreground">
            Pair an Account…
          </option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id} className="bg-background text-foreground">
              {account.name}
            </option>
          ))}
        </NativeSelect>
      ) : (
        <span className="text-muted-foreground">Add an Account to this Platform first.</span>
      )}
      {pair.error && (
        <span role="alert" className="text-alarm">
          {pair.error.message}
        </span>
      )}
      {outcome ? (
        <span className={outcome.ok ? "text-muted-foreground" : "text-alarm"}>{outcome.text}</span>
      ) : status ? (
        statusTone(status) === "alarm" ? (
          <span className="text-alarm">{status.last_error}</span>
        ) : (
          status.last_success_at && (
            <span className="text-muted-foreground">
              {formatTimestamp(Date.parse(status.last_success_at))}
            </span>
          )
        )
      ) : null}
    </li>
  );
}

function AddConnectionForm({
  venues,
  platforms,
  onDone,
}: {
  venues: Venue[];
  platforms: Platform[];
  onDone: () => void;
}) {
  const [platformId, setPlatformId] = useState(platforms[0]?.id ?? 0);
  const [venueKey, setVenueKey] = useState(venues[0]?.venue ?? "");
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const id = useId();
  const queryClient = useQueryClient();
  const venue = venues.find((entry) => entry.venue === venueKey);

  const register = useMutation({
    mutationFn: () =>
      registerConnection({
        platform_id: platformId,
        venue: venueKey,
        label: label.trim(),
        key: key.trim(),
        secret: venue?.requires_secret ? secret : null,
        passphrase: venue?.requires_passphrase ? passphrase : null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    register.mutate();
  }

  return (
    <form
      onSubmit={submit}
      className="rise rounded-xl border border-border p-5"
      aria-label="Add a Connection"
    >
      <p className="microlabel mb-4 text-muted-foreground">New Connection</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor={`${id}-platform`} className="microlabel block text-muted-foreground">
            Platform
          </label>
          <NativeSelect
            id={`${id}-platform`}
            value={platformId}
            onChange={(event) => setPlatformId(Number(event.target.value))}
          >
            {platforms.map((platform) => (
              <option
                key={platform.id}
                value={platform.id}
                className="bg-background text-foreground"
              >
                {platform.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-venue`} className="microlabel block text-muted-foreground">
            Venue
          </label>
          <NativeSelect
            id={`${id}-venue`}
            value={venueKey}
            onChange={(event) => setVenueKey(event.target.value)}
          >
            {venues.map((entry) => (
              <option
                key={entry.venue}
                value={entry.venue}
                className="bg-background text-foreground"
              >
                {entry.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      {venue && (
        <aside
          className="mt-4 flex gap-2.5 rounded-lg border border-border p-3.5 text-sm"
          aria-label={`Required scope at ${venue.name}`}
        >
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-signal" />
          <div className="space-y-1">
            <p>{venue.required_scope}</p>
            <p className="text-xs text-muted-foreground">{READ_ONLY_RULE}</p>
          </div>
        </aside>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor={`${id}-label`} className="microlabel block text-muted-foreground">
            Label
          </label>
          <Input
            id={`${id}-label`}
            required
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="Main account, Bot subaccount…"
            autoFocus
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-key`} className="microlabel block text-muted-foreground">
            API key
          </label>
          <Input
            id={`${id}-key`}
            required
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoComplete="off"
            className="font-mono"
          />
        </div>
        {venue?.requires_secret && (
          <div className="space-y-2">
            <label htmlFor={`${id}-secret`} className="microlabel block text-muted-foreground">
              Secret
            </label>
            <Input
              id={`${id}-secret`}
              type="password"
              required
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              autoComplete="new-password"
              className="font-mono"
            />
          </div>
        )}
        {venue?.requires_passphrase && (
          <div className="space-y-2">
            <label htmlFor={`${id}-passphrase`} className="microlabel block text-muted-foreground">
              Passphrase
            </label>
            <Input
              id={`${id}-passphrase`}
              type="password"
              required
              value={passphrase}
              onChange={(event) => setPassphrase(event.target.value)}
              autoComplete="new-password"
              className="font-mono"
            />
          </div>
        )}
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        Stored encrypted, never displayed again — a mistyped credential shows up when the
        Connection is tested, not by reading it back.
      </p>

      {register.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {register.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={register.isPending}>
          {register.isPending ? "Storing…" : "Store Connection"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
