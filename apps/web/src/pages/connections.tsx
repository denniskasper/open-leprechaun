import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  fetchConnections,
  fetchVenues,
  registerConnection,
  removeConnection,
  type AdapterStatus,
  type Connection,
  type Venue,
} from "@/api/connections";
import { fetchPlatforms, type Platform } from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatTimestamp } from "@/lib/format";

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
      ) : connections.data && platforms.data ? (
        <div className="space-y-12">
          {groupByPlatform(connections.data, platforms.data).map((group, index) => (
            <PlatformSection key={group.platform.id} group={group} index={index} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PlatformSection({ group, index }: { group: PlatformGroup; index: number }) {
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
          <ConnectionRow key={connection.id} connection={connection} />
        ))}
      </div>
    </section>
  );
}

function ConnectionRow({ connection }: { connection: Connection }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: () => removeConnection(connection.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

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

      {connection.statuses.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
          {connection.statuses.map((status) => (
            <StatusLine key={status.adapter_kind} status={status} />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">
          Not tested yet — nothing has synced through this Connection.
        </p>
      )}
      {remove.isError && (
        <p role="alert" className="mt-2 text-sm text-alarm">
          {remove.error.message}
        </p>
      )}
    </article>
  );
}

function StatusLine({ status }: { status: AdapterStatus }) {
  const tone = statusTone(status);

  return (
    <li className="flex items-baseline gap-1.5 font-mono text-xs">
      <span
        aria-hidden
        className={`size-1.5 self-center rounded-full ${
          tone === "signal" ? "bg-signal" : "bg-alarm"
        }`}
      />
      <span>{status.adapter_kind}</span>
      {tone === "alarm" ? (
        <span className="text-alarm">{status.last_error}</span>
      ) : (
        status.last_success_at && (
          <span className="text-muted-foreground">
            {formatTimestamp(Date.parse(status.last_success_at))}
          </span>
        )
      )}
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
