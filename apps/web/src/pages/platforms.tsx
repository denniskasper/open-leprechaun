import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Landmark,
  type LucideIcon,
  Pencil,
  Plus,
  Briefcase,
  Vault,
  Wallet,
} from "lucide-react";
import { useEffect, useId, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  addAccount,
  clearAllowanceUsed,
  editAccount,
  fetchPlatforms,
  registerPlatform,
  removeAccount,
  removePlatform,
  renamePlatform,
  setAllowanceUsed,
  setWithholding,
  setWithholdingOverride,
  type Account,
  type AllowanceUsed,
  type Platform,
  type PlatformKind,
  type Withholding,
} from "@/api/platforms";
import { fetchConnections, type Connection } from "@/api/connections";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { RemoveButtons, useRemoval } from "@/components/patterns/removal";
import { SettingsGroup, SettingsPanel } from "@/components/patterns/settings-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatEur, formatMoneyExact } from "@/lib/format";

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

/** The kinds a Freistellungsauftrag can stand at, and so use allowance through. */
const ALLOWANCE_KINDS: readonly PlatformKind[] = ["broker", "bank"];

/**
 * The year an added figure most likely belongs to: the last one whose
 * certificate can have arrived — the year before this one — or, where that is
 * entered already, the latest earlier year still without a figure.
 */
export function suggestedYear(used: AllowanceUsed[], today: Date = new Date()): number {
  const entered = new Set(used.map((figure) => figure.year));
  let year = today.getFullYear() - 1;
  while (entered.has(year)) year -= 1;
  return year;
}

/** How a broker's history reaches the ledger, and so what keeping it current takes. */
export type ServedBy = "sync" | "import" | "manual";

/**
 * Which ingestion mode serves a Platform: a Connection with a kind paired to
 * one of its Accounts means its adapters sync it — an unpaired Connection
 * lands nothing; failing that, a Depot some import declared itself authoritative
 * for is kept current by importing; otherwise everything is entered by hand.
 */
export function servedBy(platform: Platform, connections: Connection[]): ServedBy {
  const syncing = connections.some(
    (connection) => connection.platform_id === platform.id && connection.pairings.length > 0,
  );
  if (syncing) return "sync";
  if (platform.accounts.some((account) => account.authoritative_source !== null)) return "import";
  return "manual";
}

export const SERVED_BY_WORDS: Record<ServedBy, { label: string; upkeep: string }> = {
  sync: {
    label: "Served by sync",
    upkeep: "its Connection pulls trades, dividends and cash movements; positions reconcile only.",
  },
  import: {
    label: "Served by import",
    upkeep: "it stays current only as far as the last statement imported.",
  },
  manual: {
    label: "Served by manual entry",
    upkeep: "every event is recorded by hand until a Connection or an import takes over.",
  },
};

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
    <SettingsPanel
      title="Platforms"
      description="Every place that holds value — grouped by kind. An Account under one is a single holding, and the boundary FIFO lot matching works within."
    >
      <SettingsGroup
        title="Registered Platforms"
        description="Grouped by kind, each with the Accounts under it. A Platform is removed only once it holds no Account and no Connection."
        measure="list"
      >
        {error ? (
          <ErrorState
            title="The platforms could not be loaded"
            detail="The API did not answer with the platform list."
            onRetry={() => void refetch()}
          />
        ) : data && data.length === 0 ? (
          <EmptyState
            icon={Vault}
            title="No Platforms yet"
            description="Register the places that hold value — an exchange, a cold-storage device, a software wallet, a broker, a bank — then add each holding under one as an Account."
            action={
              !registering && (
                <Button variant="outline" onClick={() => setRegistering(true)}>
                  <Plus aria-hidden />
                  Register the first Platform
                </Button>
              )
            }
          />
        ) : data ? (
          <div className="measure-list space-y-12">
            {groupByKind(data).map((group) => (
              <KindSection key={group.kind} group={group} />
            ))}
          </div>
        ) : null}
      </SettingsGroup>
      <SettingsGroup
        title="New Platform"
        description="Name the place and say what kind it is. Its Accounts are added under it once it is registered."
      >
        <Button onClick={() => setRegistering((open) => !open)}>
          <Plus aria-hidden />
          Register Platform
        </Button>
        {registering && <RegisterPlatformForm onDone={() => setRegistering(false)} />}
      </SettingsGroup>
    </SettingsPanel>
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
      className="rise measure-form"
      aria-label="Register a Platform"
    >
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

function KindSection({ group }: { group: KindGroup }) {
  const Icon = KIND_ICON[group.kind];

  return (
    <section aria-label={KIND_VOCABULARY[group.kind].plural}>
      <div className="flex items-center gap-2.5 border-b border-border pb-2.5">
        <Icon aria-hidden className="size-4 text-muted-foreground" />
        <h3 className="microlabel text-muted-foreground">
          {KIND_VOCABULARY[group.kind].plural}
        </h3>
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
  const [editing, setEditing] = useState(false);
  const noun = KIND_VOCABULARY[platform.kind].account;
  const removal = useRemoval(() => removePlatform(platform.id), ["platforms"]);

  // A refusal names the Accounts and allowance used in the way; once either
  // list changes it no longer describes this Platform, so it is not left
  // standing.
  const { forget } = removal;
  useEffect(forget, [forget, platform.accounts.length, platform.allowance_used.length]);

  return (
    <article className="py-4" aria-label={platform.name}>
      {editing ? (
        <RenamePlatformForm platform={platform} onDone={() => setEditing(false)} />
      ) : (
        <div className="flex items-center gap-3">
          <h4 className="text-base font-medium">{platform.name}</h4>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {accountCount(platform.kind, platform.accounts.length)}
          </span>
          <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setAdding((open) => !open)}
            >
              <Plus aria-hidden />
              Add {noun}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              aria-label={`Edit ${platform.name}`}
              onClick={() => {
                // The row shows one thing at a time: a removal half asked for,
                // or refused, does not stand beside the edit.
                removal.keep();
                forget();
                setEditing(true);
              }}
            >
              <Pencil aria-hidden />
              Edit
            </Button>
            <RemoveButtons removal={removal} name={platform.name} />
          </span>
        </div>
      )}
      {removal.refusal && (
        <p role="alert" className="mt-1.5 text-sm text-alarm">
          {removal.refusal}
        </p>
      )}

      {platform.kind === "broker" && <WithholdingLine platform={platform} />}
      {ALLOWANCE_KINDS.includes(platform.kind) && <AllowanceUsedList platform={platform} />}
      {platform.kind === "broker" && <ServedByLine platform={platform} />}

      {platform.accounts.length > 0 && (
        <ul className="mt-3 space-y-2">
          {platform.accounts.map((account) => (
            <AccountLine key={account.id} account={account} platform={platform} />
          ))}
        </ul>
      )}
      {platform.accounts.length === 0 && !adding && (
        <p className="mt-2 text-sm text-muted-foreground">
          No {noun}s yet — use Add {noun} above to record the first holding under this Platform.
        </p>
      )}

      {adding && <AddAccountForm platform={platform} onDone={() => setAdding(false)} />}
    </article>
  );
}

/**
 * The row-level edit every row on this screen goes through: the row itself
 * becomes the form, filled with what stands, so a value is changed where it is
 * read. Like a removal, a save is never held back by a guess — the server
 * alone says whether the name is free, and its reason is kept here to be shown
 * at the row.
 */
function useRowEdit(save: () => Promise<void>, onDone: () => void) {
  const refusalId = useId();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: save,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platforms"] });
      onDone();
    },
  });
  // Not while a save is on its way: it would land after being cancelled.
  const cancel = () => {
    if (!mutation.isPending) onDone();
  };

  return {
    pending: mutation.isPending,
    refusal: mutation.error?.message,
    refusalId,
    cancel,
    /** Spread onto the `<form>`: Enter saves, Escape cancels. */
    form: {
      onSubmit: (event: FormEvent) => {
        event.preventDefault();
        mutation.mutate();
      },
      onKeyDown: (event: KeyboardEvent) => {
        if (event.key === "Escape") cancel();
      },
    },
    /** Spread onto the field a refusal is about — the name, the one thing the server refuses. */
    refusedField: {
      "aria-invalid": mutation.isError || undefined,
      "aria-describedby": mutation.isError ? refusalId : undefined,
    },
  };
}

type RowEdit = ReturnType<typeof useRowEdit>;

/** Save / Cancel. `incomplete` holds Save back while the form could not be sent at all. */
function EditButtons({ edit, incomplete }: { edit: RowEdit; incomplete: boolean }) {
  return (
    <span className="ml-auto flex items-center gap-1">
      <Button type="submit" size="sm" disabled={edit.pending || incomplete}>
        {edit.pending ? "Saving…" : "Save"}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={edit.pending}
        onClick={edit.cancel}
      >
        Cancel
      </Button>
    </span>
  );
}

function EditRefusal({ edit }: { edit: RowEdit }) {
  if (!edit.refusal) return null;
  return (
    <p id={edit.refusalId} role="alert" className="mt-1.5 text-sm text-alarm">
      {edit.refusal}
    </p>
  );
}

function RenamePlatformForm({ platform, onDone }: { platform: Platform; onDone: () => void }) {
  const [name, setName] = useState(platform.name);
  const nameId = useId();
  const edit = useRowEdit(() => renamePlatform(platform.id, name.trim()), onDone);

  return (
    <form {...edit.form} aria-label={`Edit ${platform.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={nameId} className="sr-only">
          Name
        </label>
        <Input
          id={nameId}
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="h-8 min-w-48 max-w-sm flex-1 text-base font-medium"
          {...edit.refusedField}
          autoFocus
        />
        <EditButtons edit={edit} incomplete={!name.trim()} />
      </div>
      <EditRefusal edit={edit} />
    </form>
  );
}

/**
 * States what maintaining this broker requires. The Connections it reads are
 * a second query: while they load or if they fail the line stays silent
 * rather than claim "manual entry" for a broker that syncs.
 */
function ServedByLine({ platform }: { platform: Platform }) {
  const { data: connections } = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  if (!connections) return null;
  const served = servedBy(platform, connections);
  const words = SERVED_BY_WORDS[served];
  return (
    <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
      <span className={`microlabel ${served === "sync" ? "text-signal" : "text-muted-foreground"}`}>
        {words.label}
      </span>
      <span className="text-muted-foreground">— {words.upkeep}</span>
    </p>
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
                title="The exemption order (Freistellungsauftrag) lodged with this broker — for information only. What it used each year is what reduces the allowance."
              >
                {formatMoneyExact(platform.exemption_order_eur, "EUR")} order lodged
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
      className="mt-3 measure-form rounded-xl border border-border p-4"
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
              Order lodged (EUR)
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
          The Freistellungsauftrag lodged with this broker, for information only — leave empty
          for none.
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

/**
 * The allowance used at source, year by year, exactly as each annual tax
 * certificate states it. Shown whatever the Platform's withholding is now:
 * a past year's certificate stays true after a change.
 */
function AllowanceUsedList({ platform }: { platform: Platform }) {
  const [adding, setAdding] = useState(false);
  const headingId = useId();

  return (
    <section className="my-3 pl-4" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h5 id={headingId} className="microlabel text-muted-foreground">
          Allowance used at source
        </h5>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-muted-foreground"
          onClick={() => setAdding((open) => !open)}
        >
          <Plus aria-hidden />
          Add year
        </Button>
      </div>
      {platform.allowance_used.length > 0 ? (
        <ul className="mt-1 divide-y divide-border border-y border-border">
          {platform.allowance_used.map((figure) => (
            <AllowanceUsedLine key={figure.year} platform={platform} figure={figure} />
          ))}
        </ul>
      ) : (
        !adding && (
          <p className="mt-1 text-sm text-muted-foreground">
            None entered — add each year as its annual tax certificate states it, 0 included.
          </p>
        )
      )}
      {adding && <AddAllowanceUsedForm platform={platform} onDone={() => setAdding(false)} />}
    </section>
  );
}

function AllowanceUsedLine({ platform, figure }: { platform: Platform; figure: AllowanceUsed }) {
  const [editing, setEditing] = useState(false);
  const removal = useRemoval(() => clearAllowanceUsed(platform.id, figure.year), ["platforms"]);
  const name = `the allowance used at ${platform.name} in ${figure.year}`;

  if (editing) {
    return (
      <li className="py-1.5 text-sm">
        <EditAllowanceUsedForm
          platform={platform}
          figure={figure}
          onDone={() => setEditing(false)}
        />
      </li>
    );
  }

  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-1 py-1 text-sm">
      <span className="w-12 font-mono tabular-nums">{figure.year}</span>
      <span className="w-32 text-right font-mono tabular-nums">{formatEur(figure.amount_eur)}</span>
      <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-muted-foreground"
          aria-label={`Edit ${name}`}
          onClick={() => {
            removal.keep();
            removal.forget();
            setEditing(true);
          }}
        >
          <Pencil aria-hidden />
          Edit
        </Button>
        <RemoveButtons removal={removal} name={name} className="h-7 px-2" />
      </span>
      {removal.refusal && (
        <p role="alert" className="basis-full text-sm text-alarm">
          {removal.refusal}
        </p>
      )}
    </li>
  );
}

/** A year's amount, edited in place; the year is what the row is, so it stays. */
function EditAllowanceUsedForm({
  platform,
  figure,
  onDone,
}: {
  platform: Platform;
  figure: AllowanceUsed;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(figure.amount_eur);
  const amountId = useId();
  const edit = useRowEdit(() => setAllowanceUsed(platform.id, figure.year, amount.trim()), onDone);

  return (
    <form
      {...edit.form}
      aria-label={`Edit the allowance used at ${platform.name} in ${figure.year}`}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span className="w-12 font-mono tabular-nums">{figure.year}</span>
        <label htmlFor={amountId} className="sr-only">
          Amount used (EUR)
        </label>
        <Input
          id={amountId}
          required
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          inputMode="decimal"
          className="h-8 w-32 text-right font-mono tabular-nums"
          {...edit.refusedField}
          autoFocus
        />
        <EditButtons edit={edit} incomplete={!amount.trim()} />
      </div>
      <EditRefusal edit={edit} />
    </form>
  );
}

/** A Tax Year as the add form takes it: four digits, as a certificate prints it. */
const YEAR_PATTERN = "[0-9]{4}";

/**
 * A year and its amount. Saving a year that already has a figure replaces it,
 * as the API does — a correction needs no separate removal.
 */
function AddAllowanceUsedForm({ platform, onDone }: { platform: Platform; onDone: () => void }) {
  const [year, setYear] = useState(() => String(suggestedYear(platform.allowance_used)));
  const [amount, setAmount] = useState("");
  const id = useId();
  const edit = useRowEdit(
    () => setAllowanceUsed(platform.id, Number(year), amount.trim()),
    onDone,
  );

  return (
    <form
      {...edit.form}
      className="mt-2 measure-form rounded-xl border border-border p-4"
      aria-label={`Add a year's allowance used at source for ${platform.name}`}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <label htmlFor={`${id}-year`} className="microlabel block text-muted-foreground">
            Tax year
          </label>
          <Input
            id={`${id}-year`}
            required
            value={year}
            onChange={(event) => setYear(event.target.value)}
            inputMode="numeric"
            pattern={YEAR_PATTERN}
            className="h-8 w-24 font-mono tabular-nums"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${id}-amount`} className="microlabel block text-muted-foreground">
            Amount used (EUR)
          </label>
          <Input
            id={`${id}-amount`}
            required
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            placeholder="0.00"
            className="h-8 w-36 font-mono tabular-nums"
            aria-invalid={edit.refusedField["aria-invalid"]}
            aria-describedby={[`${id}-amount-hint`, edit.refusedField["aria-describedby"]]
              .filter(Boolean)
              .join(" ")}
            autoFocus
          />
        </div>
        <EditButtons
          edit={edit}
          incomplete={!new RegExp(`^${YEAR_PATTERN}$`).test(year) || !amount.trim()}
        />
      </div>
      <p id={`${id}-amount-hint`} className="mt-2 text-xs text-muted-foreground">
        &ldquo;In Anspruch genommener Sparer-Pauschbetrag&rdquo; on the year&apos;s tax
        certificate, to the cent.
      </p>
      <EditRefusal edit={edit} />
    </form>
  );
}

function AccountLine({ account, platform }: { account: Account; platform: Platform }) {
  const [editing, setEditing] = useState(false);
  const removal = useRemoval(() => removeAccount(account.id), ["platforms"]);

  if (editing) {
    return (
      <li className="pl-4 text-sm">
        <EditAccountForm account={account} platform={platform} onDone={() => setEditing(false)} />
      </li>
    );
  }

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
      <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
        {platform.kind === "broker" && <OverrideSelect account={account} />}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-muted-foreground"
          aria-label={`Edit ${account.name}`}
          onClick={() => {
            // As on the Platform's own line: a removal half asked for, or
            // refused, does not stand beside the edit.
            removal.keep();
            removal.forget();
            setEditing(true);
          }}
        >
          <Pencil aria-hidden />
          Edit
        </Button>
        <RemoveButtons removal={removal} name={account.name} className="h-7 px-2" />
      </span>
      {removal.refusal && (
        <p role="alert" className="basis-full text-sm text-alarm">
          {removal.refusal}
        </p>
      )}
    </li>
  );
}

/**
 * An Account's line as a form: its name and the two notes beside it, all three
 * saved in one act. An emptied note is a cleared one. The chain and the base
 * currency are part of what the Account is, so they are not offered.
 */
function EditAccountForm({
  account,
  platform,
  onDone,
}: {
  account: Account;
  platform: Platform;
  onDone: () => void;
}) {
  const noun = KIND_VOCABULARY[platform.kind].account;
  const [name, setName] = useState(account.name);
  const [reference, setReference] = useState(account.external_reference ?? "");
  const [software, setSoftware] = useState(account.access_software ?? "");
  const id = useId();
  const edit = useRowEdit(
    () =>
      editAccount(account.id, {
        name: name.trim(),
        external_reference: reference.trim() || null,
        access_software: software.trim() || null,
      }),
    onDone,
  );

  return (
    <form {...edit.form} aria-label={`Edit the ${noun} ${account.name}`}>
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <div className="min-w-36 flex-1 space-y-1.5">
          <label htmlFor={`${id}-name`} className="microlabel block text-muted-foreground">
            {noun} name
          </label>
          <Input
            id={`${id}-name`}
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-8 font-medium"
            {...edit.refusedField}
            autoFocus
          />
        </div>
        <div className="min-w-48 flex-[2] space-y-1.5">
          <label htmlFor={`${id}-reference`} className="microlabel block text-muted-foreground">
            Address / IBAN / reference
          </label>
          <Input
            id={`${id}-reference`}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            className="h-8 font-mono text-xs tabular-nums"
            title="Identification only — never a data source."
          />
        </div>
        <div className="min-w-36 flex-1 space-y-1.5">
          <label htmlFor={`${id}-software`} className="microlabel block text-muted-foreground">
            Access software
          </label>
          <Input
            id={`${id}-software`}
            value={software}
            onChange={(event) => setSoftware(event.target.value)}
            className="h-8"
          />
        </div>
        <EditButtons edit={edit} incomplete={!name.trim()} />
      </div>
      <EditRefusal edit={edit} />
    </form>
  );
}

function OverrideSelect({ account }: { account: Account }) {
  const queryClient = useQueryClient();

  const record = useMutation({
    mutationFn: (behaviour: Withholding | null) => setWithholdingOverride(account.id, behaviour),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["platforms"] }),
  });

  return (
    <span className="flex items-center gap-2">
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
      className="mt-3 ml-4 measure-form rounded-xl border border-border p-4"
      aria-label={`Add ${noun === "Account" ? "an" : "a"} ${noun} under ${platform.name}`}
    >
      <div className="grid gap-3 @lg:grid-cols-2">
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
