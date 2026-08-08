import { useQuery } from "@tanstack/react-query";
import { Shapes } from "lucide-react";
import { fetchInstruments, type Instrument } from "@/api/instruments";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";

/**
 * The one line that tells two same-symbol rows apart: the family's identifying
 * attributes, never the symbol. A token is its chain and contract, a native
 * coin its chain, a security its ISIN, cash its currency code.
 */
export function identityOf(instrument: Instrument): string {
  if (instrument.contract_address) {
    return `${instrument.chain} · ${abbreviate(instrument.contract_address)}`;
  }
  if (instrument.family === "crypto") {
    return `${instrument.chain} · native`;
  }
  return instrument.isin ?? instrument.symbol;
}

/** Symbols displayed by more than one Instrument — legitimate, and worth a flag. */
export function sharedSymbols(instruments: Instrument[]): Set<string> {
  const seen = new Set<string>();
  const shared = new Set<string>();
  for (const { symbol } of instruments) {
    (seen.has(symbol) ? shared : seen).add(symbol);
  }
  return shared;
}

function abbreviate(contractAddress: string): string {
  return `${contractAddress.slice(0, 6)}…${contractAddress.slice(-4)}`;
}

const FAMILY_LABEL: Record<Instrument["family"], string> = {
  crypto: "Crypto",
  security: "Security",
  cash: "Cash",
};

export function InstrumentsPage() {
  const { data, error, refetch } = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Ledger"
        title="Instruments"
        description="Everything tradable, one concept: crypto keyed on chain and contract, securities on ISIN, cash by currency. A symbol is only a label."
      />

      {error ? (
        <ErrorState
          title="The instruments could not be loaded"
          detail="The API did not answer with the instrument list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          icon={Shapes}
          title="No Instruments yet"
          description="Instruments appear here as imports and later tickets create them — nothing has minted one so far."
        />
      ) : data ? (
        <InstrumentTable instruments={data} />
      ) : null}
    </div>
  );
}

function InstrumentTable({ instruments }: { instruments: Instrument[] }) {
  const shared = sharedSymbols(instruments);

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-border text-left">
          {["Symbol", "Name", "Family", "Identity", "Listings"].map((column) => (
            <th key={column} scope="col" className="microlabel py-2.5 pr-4 text-muted-foreground">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {instruments.map((instrument, index) => (
          <tr
            key={instrument.id}
            className="rise border-b border-border"
            style={{ animationDelay: `${120 + index * 40}ms` }}
          >
            <td className="py-3 pr-4 font-mono tabular-nums">
              {instrument.symbol}
              {shared.has(instrument.symbol) && (
                // Two Instruments legitimately share this label; the identity
                // column is what tells them apart.
                <span className="microlabel ml-2 text-caution">shared</span>
              )}
            </td>
            <td className="py-3 pr-4">{instrument.name}</td>
            <td className="py-3 pr-4 text-muted-foreground">
              {FAMILY_LABEL[instrument.family]} · {instrument.type}
            </td>
            <td
              className="py-3 pr-4 font-mono tabular-nums"
              title={instrument.contract_address ?? undefined}
            >
              {identityOf(instrument)}
            </td>
            <td className="py-3 font-mono tabular-nums text-muted-foreground">
              {instrument.listings.length === 0
                ? "—"
                : instrument.listings
                    .map((listing) => `${listing.venue} · ${listing.quote_currency}`)
                    .join(", ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
