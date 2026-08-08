import { describe, expect, it } from "vitest";
import type { Platform } from "@/api/platforms";
import { accountCount, groupByKind, KIND_VOCABULARY } from "./platforms";

function platform(overrides: Partial<Platform>): Platform {
  return {
    id: 1,
    name: "Kraken",
    kind: "exchange",
    accounts: [],
    ...overrides,
  };
}

describe("groupByKind", () => {
  it("groups platforms under their kind, in the canonical order", () => {
    const groups = groupByKind([
      platform({ id: 1, name: "Sparkasse", kind: "bank" }),
      platform({ id: 2, name: "Kraken", kind: "exchange" }),
      platform({ id: 3, name: "BitBox02", kind: "cold_storage" }),
    ]);

    expect(groups.map((group) => group.kind)).toEqual(["exchange", "cold_storage", "bank"]);
    expect(groups.map((group) => group.platforms.map((entry) => entry.name))).toEqual([
      ["Kraken"],
      ["BitBox02"],
      ["Sparkasse"],
    ]);
  });

  it("omits a kind nothing is registered under", () => {
    expect(groupByKind([platform({})]).map((group) => group.kind)).toEqual(["exchange"]);
  });

  it("keeps several platforms of one kind together", () => {
    const groups = groupByKind([
      platform({ id: 1, name: "Kraken" }),
      platform({ id: 2, name: "OKX" }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.platforms).toHaveLength(2);
  });
});

describe("KIND_VOCABULARY", () => {
  it('says "Exchange" only for the exchange kind', () => {
    const mentions = Object.entries(KIND_VOCABULARY)
      .filter(([, words]) => /exchange/i.test(`${words.singular} ${words.plural} ${words.account}`))
      .map(([kind]) => kind);

    expect(mentions).toEqual(["exchange"]);
  });

  it("calls an Account under a broker a Depot, and everything else an Account", () => {
    expect(KIND_VOCABULARY.broker.account).toBe("Depot");
    expect(
      Object.entries(KIND_VOCABULARY)
        .filter(([kind]) => kind !== "broker")
        .every(([, words]) => words.account === "Account"),
    ).toBe(true);
  });
});

describe("accountCount", () => {
  it("counts holdings in the words that kind uses", () => {
    expect(accountCount("exchange", 1)).toBe("1 Account");
    expect(accountCount("exchange", 2)).toBe("2 Accounts");
  });

  it("counts a broker's holdings as Depots", () => {
    expect(accountCount("broker", 1)).toBe("1 Depot");
    expect(accountCount("broker", 3)).toBe("3 Depots");
  });
});
