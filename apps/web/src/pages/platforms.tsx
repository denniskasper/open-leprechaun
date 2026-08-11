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
  setWithholding,
  setWithholdingOverride,
  type Account,
  type Platform,
  type PlatformKind,
  type Withholding,
} from "@/api/platforms";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatMoneyExact } from "@/lib/format";

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

/** The two behaviours a broker can have, in the Admin's words. */
export const WITHHOLDING_LABEL: Record<Withholding, string> = {
  at_source: "Withholds at source",
  none: "No withholding at source",
};

/**
 * What actually applies to one Depot: the Account's own override first, the
 * Platform's word second — null while nothing has been declared, which is
 * the state in which the Depot may hold no position.
 */
export function effectiveWithholding(platform: Platform, account: Account): Withholding | null {
  return account.withholding_override ?? platform.withholding;
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

      {platform.kind === "broker" && <WithholdingLine platform={platform} />}

      {platform.accounts.length > 0 && (
        <ul className="mt-3 space-y-2">
          {platform.accounts.map((account) => (
            <AccountLine key={account.id} account={account} platform={platform} />
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

function WithholdingLine({ platform }: { platform: Platform }) {
  const [editing, setEditing] = useState(false);

  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        {platform.withholding ? (
          <>
            <span className="text-muted-foreground">
              {WITHHOLDING_LABEL[platform.withholding]}
            </span>
            {platform.exemption_order_eur !== null && (
              <span
                className="font-mono text-xs tabular-nums text-muted-foreground"
                title="Exemption order (Freistellungsauftrag) lodged with this broker — income passes untaxed until this slice of the saver's allowance is used up."
              >
                {formatMoneyExact(platform.exemption_order_eur, "EUR")} exemption order
              </span>
            )}
          </>
        ) : (
          <span className="text-caution">
            Withholding not set — its Depots cannot hold positions until it is.
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => setEditing((open) => !open)}
        >
          {platform.withholding ? "Edit withholding" : "Set withholding"}
        </Button>
      </div>
      {editing && <WithholdingForm platform={platform} onDone={() => setEditing(false)} />}
    </div>
  );
}

function WithholdingForm({ platform, onDone }: { platform: Platform; onDone: () => void }) {
  const [behaviour, setBehaviour] = useState<Withholding>(platform.withholding ?? "at_source");
  const [order, setOrder] = useState(platform.exemption_order_eur ?? "");
  const behaviourId = useId();
  const orderId = useId();
  const queryClient = useQueryClient();

  const record = useMutation({
    mutationFn: () =>
      setWithholding(platform.id, {
        behaviour,
        exemption_order_eur: behaviour === "at_source" && order.trim() ? order.trim() : null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platforms"] });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    record.mutate();
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 rounded-xl border border-border p-4"
      aria-label={`Set withholding for ${platform.name}`}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor={behaviourId} className="microlabel block text-muted-foreground">
            Behaviour
          </label>
          <NativeSelect
            id={behaviourId}
            value={behaviour}
            onChange={(event) => setBehaviour(event.target.value as Withholding)}
          >
            {(Object.keys(WITHHOLDING_LABEL) as Withholding[]).map((value) => (
              <option key={value} value={value} className="bg-background text-foreground">
                {WITHHOLDING_LABEL[value]}
              </option>
            ))}
          </NativeSelect>
        </div>
        {behaviour === "at_source" && (
          <div className="space-y-2">
            <label htmlFor={orderId} className="microlabel block text-muted-foreground">
              Exemption order (EUR)
            </label>
            <Input
              id={orderId}
              value={order}
              onChange={(event) => setOrder(event.target.value)}
              inputMode="decimal"
              pattern="[0-9]+([.][0-9]+)?"
              placeholder="1000"
              className="w-36 font-mono tabular-nums"
              aria-describedby={`${orderId}-hint`}
            />
          </div>
        )}
        <Button type="submit" size="sm" disabled={record.isPending}>
          {record.isPending ? "Recording…" : "Record"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {behaviour === "at_source" && (
        <p id={`${orderId}-hint`} className="mt-2 text-xs text-muted-foreground">
          The Freistellungsauftrag lodged with this broker — leave empty for none.
        </p>
      )}
      {record.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {record.error.message}
        </p>
      )}
    </form>
  );
}

function AccountLine({ account, platform }: { account: Account; platform: Platform }) {
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
      {account.base_currency && (
        <span
          className="font-mono text-xs text-muted-foreground"
          title="The currency this Depot keeps its cash reporting in."
        >
          {account.base_currency}
        </span>
      )}
      {platform.kind === "broker" && <OverrideSelect account={account} />}
    </li>
  );
}

function OverrideSelect({ account }: { account: Account }) {
  const queryClient = useQueryClient();

  const record = useMutation({
    mutationFn: (behaviour: Withholding | null) => setWithholdingOverride(account.id, behaviour),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["platforms"] }),
  });

  return (
    <span className="ml-auto flex items-center gap-2">
      {record.isError && (
        <span role="alert" className="text-xs text-alarm">
          {record.error.message}
        </span>
      )}
      <NativeSelect
        className="h-7 px-2 text-xs"
        value={account.withholding_override ?? ""}
        onChange={(event) =>
          record.mutate(event.target.value === "" ? null : (event.target.value as Withholding))
        }
        aria-label={`Withholding override for ${account.name}`}
        title="This one Depot's exception — for a brand operating through several entities with different tax status."
      >
        <option value="" className="bg-background text-foreground">
          Broker&apos;s withholding
        </option>
        {(Object.keys(WITHHOLDING_LABEL) as Withholding[]).map((value) => (
          <option key={value} value={value} className="bg-background text-foreground">
            Override: {WITHHOLDING_LABEL[value]}
          </option>
        ))}
      </NativeSelect>
    </span>
  );
}

function AddAccountForm({ platform, onDone }: { platform: Platform; onDone: () => void }) {
  const noun = KIND_VOCABULARY[platform.kind].account;
  const [name, setName] = useState("");
  const [chain, setChain] = useState("");
  const [reference, setReference] = useState("");
  const [software, setSoftware] = useState("");
  const [baseCurrency, setBaseCurrency] = useState("");
  const id = useId();
  const queryClient = useQueryClient();

  const add = useMutation({
    mutationFn: () =>
      addAccount(platform.id, {
        name: name.trim(),
        chain: chain.trim() || null,
        external_reference: reference.trim() || null,
        access_software: software.trim() || null,
        base_currency: baseCurrency.trim() || null,
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
    // A Depot records its base currency (ticket 43); other kinds have none.
    ...(platform.kind === "broker"
      ? [
          {
            key: "base-currency",
            label: "Base currency",
            value: baseCurrency,
            onChange: (value: string) => setBaseCurrency(value.toUpperCase()),
            placeholder: "EUR",
            hint: "The currency this Depot keeps its cash reporting in.",
          },
        ]
      : []),
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
