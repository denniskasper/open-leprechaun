import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Landmark,
  type LucideIcon,
  Plus,
  Briefcase,
  Vault,
  Wallet,
} from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  addAccount,
  fetchPlatforms,
  registerPlatform,
  type Account,
  type Platform,
  type PlatformKind,
} from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";

interface Vocabulary {
  /** The heading a group of these places wears. */
  plural: string;
  /** One such place, as the register form offers it. */
  singular: string;
  /**
   * What an Account under this kind is called. Depot is vocabulary, not a
   * schema entity — it is what the Admin and the broker both call the thing,
   * so it belongs in the copy and nowhere else.
   */
  account: string;
}

/**
 * The canonical order of the five kinds and the words each one is spoken in.
 * This is the one place "Exchange" is allowed to appear — as the name of its
 * own kind, never as the word for every place that holds value.
 */
export const KIND_VOCABULARY: Record<PlatformKind, Vocabulary> = {
  exchange: { plural: "Exchanges", singular: "Exchange", account: "Account" },
  cold_storage: { plural: "Cold storage", singular: "Cold storage", account: "Account" },
  software_wallet: { plural: "Software wallets", singular: "Software wallet", account: "Account" },
  broker: { plural: "Brokers", singular: "Broker", account: "Depot" },
  bank: { plural: "Banks", singular: "Bank", account: "Account" },
};

const KIND_ORDER = Object.keys(KIND_VOCABULARY) as PlatformKind[];

/** "2 Accounts", or "2 Depots" where the Platform is a broker. */
export function accountCount(kind: PlatformKind, held: number): string {
  const noun = KIND_VOCABULARY[kind].account;
  return `${held} ${noun}${held === 1 ? "" : "s"}`;
}

export interface KindGroup {
  kind: PlatformKind;
  platforms: Platform[];
}

/** Settings groups Platforms by kind: canonical order, empty kinds omitted. */
export function groupByKind(platforms: Platform[]): KindGroup[] {
  return KIND_ORDER.map((kind) => ({
    kind,
    platforms: platforms.filter((platform) => platform.kind === kind),
  })).filter((group) => group.platforms.length > 0);
}

const KIND_ICON: Record<PlatformKind, LucideIcon> = {
  exchange: ArrowLeftRight,
  cold_storage: Vault,
  software_wallet: Wallet,
  broker: Briefcase,
  bank: Landmark,
};

export function PlatformsPage() {
  const { data, error, refetch } = useQuery({
    queryKey: ["platforms"],
    queryFn: fetchPlatforms,
  });
  const [registering, setRegistering] = useState(false);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Settings"
        title="Platforms"
        description="Every place that holds value — grouped by kind. An Account under one is a single holding, and the boundary FIFO lot matching works within."
        actions={
          <Button onClick={() => setRegistering((open) => !open)}>
            <Plus aria-hidden />
            Register Platform
          </Button>
        }
      />

      {registering && (
        <RegisterPlatformForm onDone={() => setRegistering(false)} />
      )}

      {error ? (
        <ErrorState
          title="The platforms could not be loaded"
          detail="The API did not answer with the platform list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 && !registering ? (
        <EmptyState
          icon={Vault}
          title="No Platforms yet"
          description="Register the places that hold value — an exchange, a cold-storage device, a software wallet, a broker, a bank — then add each holding under one as an Account."
          action={
            <Button variant="outline" onClick={() => setRegistering(true)}>
              <Plus aria-hidden />
              Register the first Platform
            </Button>
          }
        />
      ) : data ? (
        <div className="space-y-12">
          {groupByKind(data).map((group, index) => (
            <KindSection key={group.kind} group={group} index={index} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RegisterPlatformForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<PlatformKind>("exchange");
  const nameId = useId();
  const kindId = useId();
  const queryClient = useQueryClient();

  const register = useMutation({
    mutationFn: registerPlatform,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platforms"] });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    register.mutate({ name: name.trim(), kind });
  }

  return (
    <form
      onSubmit={submit}
      className="rise rounded-xl border border-border p-5"
      aria-label="Register a Platform"
    >
      <p className="microlabel mb-4 text-muted-foreground">New Platform</p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1 space-y-2">
          <label htmlFor={nameId} className="microlabel block text-muted-foreground">
            Name
          </label>
          <Input
            id={nameId}
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Kraken, BitBox02, Sparkasse…"
            autoFocus
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={kindId} className="microlabel block text-muted-foreground">
            Kind
          </label>
          <KindSelect id={kindId} value={kind} onChange={setKind} />
        </div>
        <Button type="submit" disabled={register.isPending}>
          {register.isPending ? "Registering…" : "Register"}
        </Button>
      </div>
      {register.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {register.error.message}
        </p>
      )}
    </form>
  );
}

function KindSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: PlatformKind;
  onChange: (kind: PlatformKind) => void;
}) {
  return (
    <NativeSelect
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value as PlatformKind)}
    >
      {KIND_ORDER.map((kind) => (
        <option key={kind} value={kind} className="bg-background text-foreground">
          {KIND_VOCABULARY[kind].singular}
        </option>
      ))}
    </NativeSelect>
  );
}

function KindSection({ group, index }: { group: KindGroup; index: number }) {
  const Icon = KIND_ICON[group.kind];

  return (
    <section
      className="rise"
      style={{ animationDelay: `${120 + index * 60}ms` }}
      aria-label={KIND_VOCABULARY[group.kind].plural}
    >
      <div className="flex items-center gap-2.5 border-b border-border pb-2.5">
        <Icon aria-hidden className="size-4 text-muted-foreground" />
        <h2 className="microlabel text-muted-foreground">
          {KIND_VOCABULARY[group.kind].plural}
        </h2>
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
          {group.platforms.length}
        </span>
      </div>
      <div className="divide-y divide-border">
        {group.platforms.map((platform) => (
          <PlatformRow key={platform.id} platform={platform} />
        ))}
      </div>
    </section>
  );
}

function PlatformRow({ platform }: { platform: Platform }) {
  const [adding, setAdding] = useState(false);
  const noun = KIND_VOCABULARY[platform.kind].account;

  return (
    <article className="py-4" aria-label={platform.name}>
      <div className="flex items-center gap-3">
        <h3 className="text-base font-medium">{platform.name}</h3>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {accountCount(platform.kind, platform.accounts.length)}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto text-muted-foreground"
          onClick={() => setAdding((open) => !open)}
        >
          <Plus aria-hidden />
          Add {noun}
        </Button>
      </div>

      {platform.accounts.length > 0 && (
        <ul className="mt-3 space-y-2">
          {platform.accounts.map((account) => (
            <AccountLine key={account.id} account={account} />
          ))}
        </ul>
      )}
      {platform.accounts.length === 0 && !adding && (
        <p className="mt-2 text-sm text-muted-foreground">
          No {noun}s yet — the holdings under this Platform appear here once added.
        </p>
      )}

      {adding && <AddAccountForm platform={platform} onDone={() => setAdding(false)} />}
    </article>
  );
}

function AccountLine({ account }: { account: Account }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-4 gap-y-1 pl-4 text-sm">
      <span className="font-medium">{account.name}</span>
      {account.chain && (
        <span className="font-mono text-xs text-muted-foreground">{account.chain}</span>
      )}
      {account.external_reference && (
        <span
          className="font-mono text-xs tabular-nums text-muted-foreground"
          title="Identification only — never a data source."
        >
          {account.external_reference}
        </span>
      )}
      {account.access_software && (
        <span className="text-xs text-muted-foreground">via {account.access_software}</span>
      )}
    </li>
  );
}

function AddAccountForm({ platform, onDone }: { platform: Platform; onDone: () => void }) {
  const noun = KIND_VOCABULARY[platform.kind].account;
  const [name, setName] = useState("");
  const [chain, setChain] = useState("");
  const [reference, setReference] = useState("");
  const [software, setSoftware] = useState("");
  const id = useId();
  const queryClient = useQueryClient();

  const add = useMutation({
    mutationFn: () =>
      addAccount(platform.id, {
        name: name.trim(),
        chain: chain.trim() || null,
        external_reference: reference.trim() || null,
        access_software: software.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platforms"] });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  const fields: {
    key: string;
    label: string;
    value: string;
    onChange: (value: string) => void;
    required?: boolean;
    focusFirst?: boolean;
    placeholder?: string;
    hint?: string;
  }[] = [
    {
      key: "name",
      label: "Name",
      value: name,
      onChange: setName,
      required: true,
      focusFirst: true,
      placeholder: "Main, Savings, Giro…",
    },
    {
      key: "chain",
      label: "Chain",
      value: chain,
      onChange: setChain,
      placeholder: "bitcoin, solana…",
    },
    {
      key: "reference",
      label: "Address / IBAN / reference",
      value: reference,
      onChange: setReference,
      hint: "Identification only — never a data source.",
    },
    {
      key: "software",
      label: "Access software",
      value: software,
      onChange: setSoftware,
      placeholder: "BitBoxApp, chipTAN app…",
    },
  ];

  return (
    <form
      onSubmit={submit}
      className="mt-3 ml-4 rounded-xl border border-border p-4"
      aria-label={`Add ${noun === "Account" ? "an" : "a"} ${noun} under ${platform.name}`}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <div key={field.key} className="space-y-2">
            <label htmlFor={`${id}-${field.key}`} className="microlabel block text-muted-foreground">
              {field.label}
            </label>
            <Input
              id={`${id}-${field.key}`}
              required={field.required}
              value={field.value}
              onChange={(event) => field.onChange(event.target.value)}
              placeholder={field.placeholder}
              autoFocus={field.focusFirst}
              aria-describedby={field.hint ? `${id}-${field.key}-hint` : undefined}
            />
            {field.hint && (
              <p id={`${id}-${field.key}-hint`} className="text-xs text-muted-foreground">
                {field.hint}
              </p>
            )}
          </div>
        ))}
      </div>
      {add.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {add.error.message}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <Button type="submit" size="sm" disabled={add.isPending}>
          {add.isPending ? "Adding…" : `Add ${noun}`}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
