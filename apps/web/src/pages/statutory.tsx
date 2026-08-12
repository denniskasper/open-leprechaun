import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Pencil, Plus } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  chooseElection,
  enterValue,
  fetchStatutory,
  unsetValue,
  type ChurchTax,
  type Election,
  type FilingStatus,
  type StatutoryKey,
  type StatutoryKeyDefinition,
  type StatutoryValue,
  type StatutoryYear,
} from "@/api/statutory";
import { DECIMAL_PATTERN } from "@/api/transactions";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/patterns/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatMoneyExact, formatQuantity } from "@/lib/format";

/**
 * The words each statutory constant is spoken in — the German term the law
 * and the glossary use, kept beside a plain-English gloss. The value's own
 * citation rides on the row as its source. An optional key also says what
 * its absence means, because absence is an answer, never a gap.
 */
export const KEY_WORDS: Record<
  StatutoryKey,
  { label: string; gloss: string; absent?: string }
> = {
  private_sale_exemption_limit: {
    label: "Freigrenze — private sales",
    gloss: "All-or-nothing annual limit on §23 private-sale gains",
  },
  other_income_exemption_limit: {
    label: "Freigrenze — Sonstige Einkünfte",
    gloss: "All-or-nothing annual limit on §22 income, phrased as “less than”",
  },
  saver_allowance_single: {
    label: "Sparerpauschbetrag — single",
    gloss: "Capital-income deduction, single assessment",
  },
  saver_allowance_joint: {
    label: "Sparerpauschbetrag — joint",
    gloss: "Capital-income deduction, married filing jointly",
  },
  flat_rate: {
    label: "Abgeltungsteuer rate",
    gloss: "Flat rate on capital income",
  },
  solidarity_surcharge_rate: {
    label: "Solidarity surcharge",
    gloss: "Levied on the flat-rate tax",
  },
  church_tax_rate_bavaria_bw: {
    label: "Church tax — Bavaria, Baden-Württemberg",
    gloss: "Applies where the election names these Länder",
  },
  church_tax_rate_other_laender: {
    label: "Church tax — other Länder",
    gloss: "Applies where the election names the other Länder",
  },
  advance_lump_sum_base_rate: {
    label: "Basiszins",
    gloss: "Drives the Vorabpauschale; published each January",
  },
  loss_cap_aktien: {
    label: "Loss cap — Aktien",
    gloss: "Per-year cap on the share-sale loss pot",
    absent: "not set — uncapped",
  },
  loss_cap_sonstige: {
    label: "Loss cap — Sonstige",
    gloss: "Per-year cap on the other-capital-income loss pot",
    absent: "not set — uncapped",
  },
  loss_cap_termingeschaefte: {
    label: "Loss cap — Termingeschäfte",
    gloss: "Per-year cap on the futures loss pot",
    absent: "not set — uncapped",
  },
  opening_carryforward_aktien: {
    label: "Opening carryforward — Aktien",
    gloss: "Share-sale loss carried into this year from an assessment predating the ledger",
    absent: "not set — none carried",
  },
  opening_carryforward_sonstige: {
    label: "Opening carryforward — Sonstige",
    gloss: "Other-capital-income loss carried into this year from an assessment predating the ledger",
    absent: "not set — none carried",
  },
  opening_carryforward_termingeschaefte: {
    label: "Opening carryforward — Termingeschäfte",
    gloss: "Futures loss carried into this year from an assessment predating the ledger",
    absent: "not set — none carried",
  },
  partial_exemption_aktienfonds: {
    label: "Teilfreistellung — Aktienfonds",
    gloss: "Share of an equity fund's gains and distributions exempted",
  },
  partial_exemption_mischfonds: {
    label: "Teilfreistellung — Mischfonds",
    gloss: "Share of a mixed fund's gains and distributions exempted",
  },
  partial_exemption_immobilienfonds: {
    label: "Teilfreistellung — Immobilienfonds",
    gloss: "Share of a real-estate fund's gains and distributions exempted",
  },
  partial_exemption_auslands_immobilienfonds: {
    label: "Teilfreistellung — Auslands-Immobilienfonds",
    gloss: "Share of a foreign-real-estate fund's gains and distributions exempted",
  },
  partial_exemption_sonstige: {
    label: "Teilfreistellung — sonstige Fonds",
    gloss: "Share exempted for funds outside the named categories — the statute says none",
  },
};

export const FILING_WORDS: Record<FilingStatus, string> = {
  single: "Single",
  joint: "Married, filing jointly",
};

export const CHURCH_WORDS: Record<ChurchTax, string> = {
  none: "None",
  bavaria_bw: "Bavaria or Baden-Württemberg",
  other_laender: "Other Länder",
};

/**
 * A rate crosses the API as a fraction of one; people read percentages. The
 * decimal point moves two places by string surgery — the digits never pass
 * through a float.
 */
export function percentWords(value: string): string {
  const [integer, fraction = ""] = value.split(".");
  const shiftedInteger = (integer + fraction.slice(0, 2).padEnd(2, "0")).replace(/^0+(?=\d)/, "");
  const shiftedFraction = fraction.slice(2).replace(/0+$/, "");
  return shiftedFraction ? `${shiftedInteger}.${shiftedFraction}` : shiftedInteger;
}

/** A stored value rendered for its unit: EUR with the currency adjacent, a rate as a percentage. */
export function displayValue(unit: "eur" | "rate", value: string, locale?: string): string {
  if (unit === "rate") {
    return `${formatQuantity(percentWords(value), locale)} %`;
  }
  return formatMoneyExact(value, "EUR", locale);
}

export type RowState = "set" | "missing" | "absent";

export interface KeyRow {
  definition: StatutoryKeyDefinition;
  value: StatutoryValue | null;
  state: RowState;
}

/**
 * Every key of the vocabulary as one row for a year: set with its value, or
 * honestly absent — a caution where the year requires it, and where the key
 * is optional the row says what absence means (uncapped, none carried).
 */
export function rowsForYear(keys: StatutoryKeyDefinition[], year: StatutoryYear): KeyRow[] {
  const valueOf = new Map(year.values.map((value) => [value.key, value]));
  return keys.map((definition) => {
    const value = valueOf.get(definition.key) ?? null;
    return {
      definition,
      value,
      state: value ? "set" : definition.required ? "missing" : "absent",
    };
  });
}

export function StatutoryPage() {
  const { data, error, refetch } = useQuery({ queryKey: ["statutory"], queryFn: fetchStatutory });
  const [draftYear, setDraftYear] = useState<number | null>(null);

  const years = data ? [...data.years] : [];
  if (data && draftYear !== null && !years.some((year) => year.year === draftYear)) {
    years.unshift({ year: draftYear, values: [], missing: data.keys.filter((key) => key.required).map((key) => key.key) });
    years.sort((a, b) => b.year - a.year);
  }

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Settings"
        title="Statutory configuration"
        description="Every constant the tax engines read — per year, with the source it came from. A rule change is an edit here, never a code change, and a year missing a required value refuses to compute rather than guessing."
        actions={<AddYearControl onAdd={setDraftYear} />}
      />

      {error ? (
        <ErrorState
          title="The statutory configuration could not be loaded"
          detail="The API did not answer with the per-year values."
          onRetry={() => void refetch()}
        />
      ) : data ? (
        <div className="space-y-12">
          <ElectionPanel election={data} />
          {years.map((year, index) => (
            <YearSection key={year.year} keys={data.keys} year={year} index={index} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AddYearControl({ onAdd }: { onAdd: (year: number) => void }) {
  const [adding, setAdding] = useState(false);
  const [year, setYear] = useState("");
  const id = useId();

  if (!adding) {
    return (
      <Button variant="outline" onClick={() => setAdding(true)}>
        <Plus aria-hidden />
        Add year
      </Button>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const chosen = Number(year);
    if (Number.isInteger(chosen)) {
      onAdd(chosen);
      setAdding(false);
      setYear("");
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-end justify-end gap-2"
      aria-label="Add a year"
    >
      <div className="space-y-2">
        <label htmlFor={id} className="microlabel block text-muted-foreground">
          Year
        </label>
        <Input
          id={id}
          type="number"
          // Mirrors the API's regime bounds (services/statutory.py
          // FIRST_YEAR/LAST_YEAR); the API's own refusal is the arbiter.
          min={2009}
          max={2100}
          required
          value={year}
          onChange={(event) => setYear(event.target.value)}
          className="w-24"
          autoFocus
        />
      </div>
      <Button type="submit" size="sm">
        Add
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>
        Cancel
      </Button>
      <p className="basis-full text-right text-xs text-muted-foreground">
        A year is kept once its first value is stored.
      </p>
    </form>
  );
}

function ElectionPanel({ election }: { election: Election }) {
  const queryClient = useQueryClient();
  const id = useId();
  const choose = useMutation({
    mutationFn: chooseElection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["statutory"] }),
  });

  function change(changed: Partial<Election>) {
    choose.mutate({
      filing_status: election.filing_status,
      church_tax: election.church_tax,
      ...changed,
    });
  }

  return (
    <section className="rise rounded-xl border border-border p-5" aria-label="Elections">
      <p className="microlabel text-muted-foreground">Elections</p>
      <p className="mt-1 text-sm text-muted-foreground">
        These choices select which of the per-year values apply — the saver-allowance variant and
        the church-tax rate. No engine doubles an amount or picks a rate in logic.
      </p>
      <div className="mt-4 flex flex-wrap gap-6">
        <div className="space-y-2">
          <label htmlFor={`${id}-filing`} className="microlabel block text-muted-foreground">
            Filing status
          </label>
          <ElectionSelect
            id={`${id}-filing`}
            value={election.filing_status}
            words={FILING_WORDS}
            onChange={(filing_status) => change({ filing_status })}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-church`} className="microlabel block text-muted-foreground">
            Church tax
          </label>
          <ElectionSelect
            id={`${id}-church`}
            value={election.church_tax}
            words={CHURCH_WORDS}
            onChange={(church_tax) => change({ church_tax })}
          />
        </div>
      </div>
      {choose.isError && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {choose.error.message}
        </p>
      )}
    </section>
  );
}

function ElectionSelect<Choice extends string>({
  id,
  value,
  words,
  onChange,
}: {
  id: string;
  value: Choice;
  words: Record<Choice, string>;
  onChange: (choice: Choice) => void;
}) {
  return (
    <NativeSelect
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value as Choice)}
    >
      {(Object.entries(words) as [Choice, string][]).map(([choice, label]) => (
        <option key={choice} value={choice} className="bg-background text-foreground">
          {label}
        </option>
      ))}
    </NativeSelect>
  );
}

function YearSection({
  keys,
  year,
  index,
}: {
  keys: StatutoryKeyDefinition[];
  year: StatutoryYear;
  index: number;
}) {
  return (
    <section
      className="rise"
      style={{ animationDelay: `${120 + index * 60}ms` }}
      aria-label={`Statutory values ${year.year}`}
    >
      <div className="flex items-baseline gap-3 border-b border-border pb-2.5">
        <h2 className="font-mono text-base tabular-nums">{year.year}</h2>
        {year.missing.length === 0 ? (
          <span className="microlabel inline-flex items-center gap-1 text-signal">
            <CircleCheck aria-hidden className="size-3" />
            complete
          </span>
        ) : (
          <span className="microlabel text-caution">
            {year.missing.length} required {year.missing.length === 1 ? "value" : "values"} unset
          </span>
        )}
      </div>
      <div className="divide-y divide-border">
        {rowsForYear(keys, year).map((row) => (
          <ValueRow key={row.definition.key} year={year.year} row={row} />
        ))}
      </div>
    </section>
  );
}

function ValueRow({ year, row }: { year: number; row: KeyRow }) {
  const [editing, setEditing] = useState(false);
  const words = KEY_WORDS[row.definition.key];

  return (
    <article className="py-3" aria-label={`${words.label} ${year}`}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <div className="min-w-64 flex-1">
          <p className="text-sm font-medium">{words.label}</p>
          <p className="text-xs text-muted-foreground">{words.gloss}</p>
        </div>
        {row.state === "set" && row.value ? (
          <>
            <span className="w-28 text-right font-mono text-sm tabular-nums">
              {displayValue(row.definition.unit, row.value.value)}
            </span>
            <span
              className="w-64 truncate text-right text-xs text-muted-foreground"
              title={row.value.source}
            >
              {row.value.source}
            </span>
          </>
        ) : (
          <span
            className={`microlabel w-92 text-right ${
              row.state === "missing" ? "text-caution" : "text-muted-foreground"
            }`}
          >
            {row.state === "missing" ? "not set" : (words.absent ?? "not set")}
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => setEditing((open) => !open)}
        >
          <Pencil aria-hidden />
          {row.state === "set" ? "Edit" : "Set"}
        </Button>
      </div>
      {editing && <EditValueForm year={year} row={row} onDone={() => setEditing(false)} />}
    </article>
  );
}

function EditValueForm({ year, row, onDone }: { year: number; row: KeyRow; onDone: () => void }) {
  const words = KEY_WORDS[row.definition.key];
  const [value, setValue] = useState(row.value?.value ?? "");
  const [source, setSource] = useState(row.value?.source ?? "");
  const id = useId();
  const queryClient = useQueryClient();

  const enter = useMutation({
    mutationFn: () =>
      enterValue(year, row.definition.key, { value: value.trim(), source: source.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["statutory"] });
      onDone();
    },
  });
  const unset = useMutation({
    mutationFn: () => unsetValue(year, row.definition.key),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["statutory"] });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    enter.mutate();
  }

  const failure = enter.error ?? unset.error;

  return (
    <form
      onSubmit={submit}
      className="mt-3 rounded-md border border-border p-4"
      aria-label={`${row.state === "set" ? "Correct" : "Set"} ${words.label} for ${year}`}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor={`${id}-value`} className="microlabel block text-muted-foreground">
            {row.definition.unit === "rate" ? "Value (fraction of one)" : "Value (EUR)"}
          </label>
          <Input
            id={`${id}-value`}
            required
            inputMode="decimal"
            pattern={DECIMAL_PATTERN.source}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={row.definition.unit === "rate" ? "0.25" : "1000"}
            className="w-36 font-mono tabular-nums"
            autoFocus
          />
        </div>
        <div className="min-w-64 flex-1 space-y-2">
          <label htmlFor={`${id}-source`} className="microlabel block text-muted-foreground">
            Source
          </label>
          <Input
            id={`${id}-source`}
            required
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder="§ 32d Abs. 1 Satz 1 EStG, BMF-Schreiben v. …"
          />
        </div>
        <Button type="submit" size="sm" disabled={enter.isPending}>
          {enter.isPending ? "Storing…" : "Store"}
        </Button>
        {row.state === "set" && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            disabled={unset.isPending}
            onClick={() => unset.mutate()}
          >
            {unset.isPending ? "Unsetting…" : "Unset"}
          </Button>
        )}
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {row.definition.unit === "rate" && (
        <p className="mt-2 text-xs text-muted-foreground">
          A rate is a fraction of one — 25 % is entered as 0.25.
        </p>
      )}
      {failure && (
        <p role="alert" className="mt-3 text-sm text-alarm">
          {failure.message}
        </p>
      )}
    </form>
  );
}
