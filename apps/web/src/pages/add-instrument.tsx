import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { addInstrument, type Instrument, type NewInstrument } from "@/api/instruments";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type AddKind = NewInstrument["kind"];

const KINDS: { kind: AddKind; label: string; says: string; keyedOn: string }[] = [
  {
    kind: "token",
    label: "Token",
    says: "A coin issued by a contract on a chain, like USDC. The chain and contract address are its identity.",
    keyedOn: "A token is its chain and contract address",
  },
  {
    kind: "native",
    label: "Native coin",
    says: "A chain's own coin, like BTC or ETH. It has no contract; its symbol is its identity.",
    keyedOn: "A native coin is its symbol",
  },
  {
    kind: "cash",
    label: "Currency",
    says: "A fiat currency, like USD. Its three-letter code is its identity.",
    keyedOn: "A currency is its code",
  },
];

/** Offered, never required: a chain not listed here is typed out. */
const KNOWN_CHAINS = [
  "ethereum",
  "bitcoin",
  "solana",
  "arbitrum",
  "base",
  "optimism",
  "polygon",
  "bnb",
  "avalanche",
  "tron",
];

const HEX_ADDRESS = /^0x[0-9a-fA-F]{40}$/;

/**
 * What is wrong with a contract address, judged by form alone — nothing is
 * looked up on a chain. A hex address has one length; any other chain's is
 * taken as written. Null while there is nothing to say.
 */
export function addressProblem(address: string): string | null {
  const typed = address.trim();
  if (typed.slice(0, 2).toLowerCase() === "0x" && !HEX_ADDRESS.test(typed)) {
    return "An address starting with 0x is 40 hex characters after it.";
  }
  return null;
}

export interface AddFields {
  symbol: string;
  name: string;
  chain: string;
  contractAddress: string;
  peggedCurrency: string;
}

const CURRENCY_CODE = /^[A-Za-z]{3}$/;
const NOT_THREE_LETTERS = "A currency code is three letters, like USD.";

/** A field typed into but holding only spaces — `required` lets those through. */
function blankProblem(typed: string, what: string): string | null {
  return typed !== "" && typed.trim() === "" ? `${what} cannot be blank.` : null;
}

/**
 * What is wrong with each field of one kind, by the rules the API holds the
 * request to and in its words — so every refusal is named beside its field
 * before anything is sent. A field still empty is left to the form's own
 * `required`; only the fields the kind is made of are judged.
 */
export function fieldProblems(
  kind: AddKind,
  fields: AddFields,
): Partial<Record<keyof AddFields, string>> {
  const code = fields.symbol.trim();
  const peg = fields.peggedCurrency.trim();
  const problems = {
    symbol:
      kind === "cash"
        ? fields.symbol !== "" && !CURRENCY_CODE.test(code)
          ? NOT_THREE_LETTERS
          : null
        : blankProblem(fields.symbol, "A symbol"),
    name: blankProblem(fields.name, "A name"),
    chain: kind === "cash" ? null : blankProblem(fields.chain, "A chain"),
    contractAddress:
      kind === "token"
        ? (blankProblem(fields.contractAddress, "A contract address") ??
          addressProblem(fields.contractAddress))
        : null,
    peggedCurrency:
      kind === "token" && peg !== "" && !CURRENCY_CODE.test(peg) ? NOT_THREE_LETTERS : null,
  };
  return Object.fromEntries(Object.entries(problems).filter(([, problem]) => problem !== null));
}

/** The request for one kind: only the fields that kind's identity is made of. */
export function instrumentPayload(kind: AddKind, fields: AddFields): NewInstrument {
  const name = fields.name.trim();
  if (kind === "cash") {
    return { kind, symbol: fields.symbol.trim().toUpperCase(), name };
  }
  const symbol = fields.symbol.trim();
  const chain = fields.chain.trim();
  if (kind === "native") return { kind, symbol, name, chain };
  return {
    kind,
    symbol,
    name,
    chain,
    contract_address: fields.contractAddress.trim(),
    pegged_currency: fields.peggedCurrency.trim().toUpperCase() || null,
  };
}

/**
 * The coins and currencies already wearing a symbol — what a venue stating
 * only that symbol would have to choose among.
 */
export function wearing(instruments: Instrument[], symbol: string): Instrument[] {
  const typed = symbol.trim();
  if (typed === "") return [];
  return instruments.filter(
    (instrument) => instrument.family !== "security" && instrument.symbol === typed,
  );
}

/**
 * The Instrument already holding the identity being typed (ADR-0010) — a
 * native coin's symbol, a currency's code, a token's chain and contract. The
 * API refuses a second one, so the form says so before anything is sent.
 * Null where the identity is free, or not yet typed.
 */
export function alreadyKeyed(
  instruments: Instrument[],
  kind: AddKind,
  fields: AddFields,
): Instrument | null {
  const stated = instrumentPayload(kind, fields);
  const held = (instrument: Instrument): boolean => {
    if (stated.kind === "cash") {
      return instrument.family === "cash" && instrument.symbol === stated.symbol;
    }
    if (instrument.family !== "crypto" || instrument.type !== stated.kind) return false;
    if (stated.kind === "native") return instrument.symbol === stated.symbol;
    return (
      instrument.chain === stated.chain.toLowerCase() &&
      instrument.contract_address?.toLowerCase() === stated.contract_address.toLowerCase()
    );
  };
  return instruments.find(held) ?? null;
}

/**
 * Where a screen sends the Admin to add the symbol a sync could not resolve
 * — on the kind that will answer to it, where the sync said only one does.
 */
export function addInstrumentHref(symbol: string, kind: AddKind | null = null): string {
  const href = `/instruments?add=${encodeURIComponent(symbol)}`;
  return kind === null ? href : `${href}&kind=${kind}`;
}

/** The kind such a link asks the form to open on: a token unless it names another. */
export function requestedKind(named: string | null): AddKind {
  return KINDS.find((entry) => entry.kind === named)?.kind ?? "token";
}

/**
 * The add-by-hand flow for what no provider search covers: a token, a native
 * coin or a currency, stated by the identity the ledger keys it on. A venue's
 * sync resolves it by symbol from then on.
 */
export function AddInstrumentPanel({
  instruments,
  symbol: suggested = "",
  kind: opensOn = "token",
  onDone,
}: {
  instruments: Instrument[];
  /** The symbol a refused sync named, where the Admin arrived from one. */
  symbol?: string;
  /** The kind that sync said will answer to it. */
  kind?: AddKind;
  onDone: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<AddKind>(opensOn);
  const [symbol, setSymbol] = useState(suggested);
  const [name, setName] = useState("");
  const [chain, setChain] = useState("");
  const [contractAddress, setContractAddress] = useState("");
  const [peggedCurrency, setPeggedCurrency] = useState("");

  const fields: AddFields = { symbol, name, chain, contractAddress, peggedCurrency };

  const add = useMutation({
    mutationFn: () => addInstrument(instrumentPayload(kind, fields)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["instruments"] });
      onDone();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };

  const chosen = KINDS.find((entry) => entry.kind === kind);
  const problems = fieldProblems(kind, fields);
  const held = alreadyKeyed(instruments, kind, fields);
  // The Instrument holding the identity is no second wearer of the symbol:
  // it is the one being typed, and nothing more can be added.
  const worn =
    held === null ? wearing(instruments, kind === "cash" ? symbol.toUpperCase() : symbol) : [];
  const refused = held !== null || Object.keys(problems).length > 0;
  // What a field's input points at while its entry is refused.
  const problemOf = (field: keyof AddFields, hint?: string) =>
    problems[field] === undefined
      ? { "aria-describedby": hint }
      : {
          "aria-invalid": true,
          "aria-describedby": [hint, `${id}-${field}-problem`].filter(Boolean).join(" "),
        };
  const problem = (field: keyof AddFields) =>
    problems[field] !== undefined && (
      <p id={`${id}-${field}-problem`} className="text-sm text-caution">
        {problems[field]}
      </p>
    );

  return (
    <section
      className="rise measure-form rounded-xl border border-border p-5"
      aria-label="Add coin or currency"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <p className="microlabel text-muted-foreground">New coin or currency</p>
        <div role="group" aria-label="Kind" className="flex gap-1">
          {KINDS.map((entry) => (
            <Button
              key={entry.kind}
              type="button"
              size="sm"
              variant={entry.kind === kind ? "secondary" : "ghost"}
              aria-pressed={entry.kind === kind}
              onClick={() => setKind(entry.kind)}
            >
              {entry.label}
            </Button>
          ))}
        </div>
      </div>
      <p className="mt-2 measure-prose text-sm text-muted-foreground">{chosen?.says}</p>

      <form onSubmit={submit} className="mt-4 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor={`${id}-symbol`} className="microlabel block text-muted-foreground">
              {kind === "cash" ? "Code" : "Symbol"}
            </label>
            <Input
              id={`${id}-symbol`}
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder={kind === "cash" ? "USD" : kind === "native" ? "BTC" : "USDC"}
              maxLength={kind === "cash" ? 3 : undefined}
              className={kind === "cash" ? "font-mono uppercase" : "font-mono"}
              autoFocus={suggested === ""}
              required
              {...problemOf("symbol")}
            />
            {problem("symbol")}
          </div>
          <div className="space-y-1.5">
            <label htmlFor={`${id}-name`} className="microlabel block text-muted-foreground">
              Name
            </label>
            <Input
              id={`${id}-name`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={
                kind === "cash" ? "US Dollar" : kind === "native" ? "Bitcoin" : "USD Coin"
              }
              autoFocus={suggested !== ""}
              required
              {...problemOf("name")}
            />
            {problem("name")}
          </div>
          {kind !== "cash" && (
            <div className="space-y-1.5">
              <label htmlFor={`${id}-chain`} className="microlabel block text-muted-foreground">
                Chain
              </label>
              <Input
                id={`${id}-chain`}
                value={chain}
                onChange={(event) => setChain(event.target.value)}
                list={`${id}-chains`}
                placeholder={kind === "native" ? "bitcoin" : "ethereum"}
                className="font-mono lowercase"
                required
                {...problemOf("chain")}
              />
              {problem("chain")}
              <datalist id={`${id}-chains`}>
                {KNOWN_CHAINS.map((known) => (
                  <option key={known} value={known} />
                ))}
              </datalist>
            </div>
          )}
          {kind === "token" && (
            <>
              <div className="space-y-1.5">
                <label
                  htmlFor={`${id}-peg`}
                  className="microlabel block text-muted-foreground"
                >
                  Pegged to (optional)
                </label>
                <Input
                  id={`${id}-peg`}
                  value={peggedCurrency}
                  onChange={(event) => setPeggedCurrency(event.target.value)}
                  placeholder="USD"
                  maxLength={3}
                  className="font-mono uppercase"
                  {...problemOf("peggedCurrency", `${id}-peg-hint`)}
                />
                {problem("peggedCurrency")}
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <label
                  htmlFor={`${id}-contract`}
                  className="microlabel block text-muted-foreground"
                >
                  Contract address
                </label>
                <Input
                  id={`${id}-contract`}
                  value={contractAddress}
                  onChange={(event) => setContractAddress(event.target.value)}
                  className="font-mono"
                  autoComplete="off"
                  spellCheck={false}
                  required
                  {...problemOf("contractAddress")}
                />
                {problem("contractAddress")}
              </div>
            </>
          )}
        </div>

        {kind === "token" && (
          <p id={`${id}-peg-hint`} className="measure-prose text-sm text-muted-foreground">
            For a stablecoin, name the currency it follows. Its EUR value then comes from that
            currency's daily reference rate; without one it is priced like any other coin. The
            address is checked for its form only — nothing is looked up on the chain.
          </p>
        )}
        {held && (
          <p className="measure-prose text-sm text-caution">
            {held.name} ({held.symbol}) already holds this identity. {chosen?.keyedOn}, so there is
            no second one to add.
          </p>
        )}
        {worn.length > 0 && (
          <p className="measure-prose text-sm text-caution">
            {worn.map((entry) => entry.name).join(", ")} already{" "}
            {worn.length === 1 ? "wears" : "wear"} the symbol {worn[0]?.symbol}. A second one is
            allowed, but a sync that states only the symbol can then no longer choose and will
            refuse it.
          </p>
        )}
        {add.error != null && (
          <p role="alert" className="text-sm text-alarm">
            {add.error.message}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" disabled={add.isPending || refused}>
            {add.isPending ? "Adding…" : `Add ${chosen?.label.toLowerCase()}`}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}
