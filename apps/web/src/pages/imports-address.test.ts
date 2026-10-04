import { describe, expect, it } from "vitest";
import type { Platform } from "@/api/platforms";
import { addressCommittedWords, indexerWords, suggestedAddress } from "./imports-address";

describe("indexerWords", () => {
  it("says the address is all that is asked, and names the fee coin", () => {
    expect(indexerWords({ chain: "solana", name: "Solana", native_symbol: "SOL", lookback_days: null })).toBe(
      "Solana's history is public: the address is all that is asked, and nothing can be moved with it. Network fees are recorded in SOL.",
    );
  });
});

describe("addressCommittedWords", () => {
  const committed = { batch_id: 5, created: 2, duplicates: 0, skipped: 0, instruments_created: 1 };

  it("counts what landed", () => {
    expect(addressCommittedWords(committed, "en")).toBe("2 rows created · 1 Instrument created");
  });

  it("says a re-read changed nothing, about the address", () => {
    expect(addressCommittedWords({ ...committed, batch_id: null, created: 0 }, "en")).toBe(
      "Nothing new — the ledger already knows this address's history.",
    );
  });
});

describe("suggestedAddress", () => {
  const platforms = [
    {
      accounts: [
        { id: 3, chain: "Solana", external_reference: "Wa11etAddr3ss" },
        { id: 4, chain: "bitcoin", external_reference: "bc1qa" },
        { id: 5, chain: "solana", external_reference: null },
      ],
    },
  ] as unknown as Platform[];

  it("offers the address the Account states for this chain", () => {
    expect(suggestedAddress(platforms, "3", "solana")).toBe("Wa11etAddr3ss");
  });

  it("offers nothing for another chain's Account, or one stating no address", () => {
    expect(suggestedAddress(platforms, "4", "solana")).toBeNull();
    expect(suggestedAddress(platforms, "5", "solana")).toBeNull();
    expect(suggestedAddress(platforms, "", "solana")).toBeNull();
  });
});
