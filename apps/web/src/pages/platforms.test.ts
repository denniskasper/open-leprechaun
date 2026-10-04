import { describe, expect, it } from "vitest";
import type { Connection } from "@/api/connections";
import type { Account, Platform } from "@/api/platforms";
import {
  accountCount,
  effectiveWithholding,
  groupByKind,
  KIND_VOCABULARY,
  servedBy,
  SERVED_BY_WORDS,
  WITHHOLDING_LABEL,
} from "./platforms";

function platform(overrides: Partial<Platform>): Platform {
  return {
    id: 1,
    name: "Kraken",
    kind: "exchange",
    withholding: null,
    exemption_order_eur: null,
    accounts: [],
    ...overrides,
  };
}

function account(overrides: Partial<Account>): Account {
  return {
    id: 1,
    name: "Depot",
    chain: null,
    external_reference: null,
    access_software: null,
    authoritative_source: null,
    withholding_override: null,
    base_currency: null,
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

describe("effectiveWithholding", () => {
  it("lets the Platform's word stand where the Account states no exception", () => {
    expect(
      effectiveWithholding(platform({ kind: "broker", withholding: "at_source" }), account({})),
    ).toBe("at_source");
  });

  it("prefers the Account's own override", () => {
    expect(
      effectiveWithholding(
        platform({ kind: "broker", withholding: "at_source" }),
        account({ withholding_override: "none" }),
      ),
    ).toBe("none");
  });

  it("answers null while nothing has been declared", () => {
    expect(effectiveWithholding(platform({ kind: "broker" }), account({}))).toBeNull();
  });
});

describe("servedBy", () => {
  const connection: Connection = {
    id: 9,
    platform_id: 1,
    venue: "trading_212",
    label: "Invest",
    fingerprint: "abc",
    last_used_at: null,
    statuses: [],
    pairings: [{ adapter_kind: "securities", account_id: 1 }],
  };

  it("does not call a broker synced whose Connection has no kind paired yet", () => {
    const broker = platform({ id: 1, kind: "broker", accounts: [account({})] });

    expect(servedBy(broker, [{ ...connection, pairings: [] }])).toBe("manual");
  });

  it("says sync where a Connection's kind lands in one of its Depots", () => {
    const broker = platform({ id: 1, kind: "broker", accounts: [account({})] });

    expect(servedBy(broker, [connection])).toBe("sync");
    expect(SERVED_BY_WORDS.sync.label).toBe("Served by sync");
  });

  it("says import where only a statement import writes into one of its Depots", () => {
    const broker = platform({
      id: 2,
      kind: "broker",
      accounts: [account({ authoritative_source: "csv:etoro" })],
    });

    expect(servedBy(broker, [connection])).toBe("import");
  });

  it("says manual entry where nothing feeds it", () => {
    expect(servedBy(platform({ id: 2, kind: "broker", accounts: [account({})] }), [])).toBe(
      "manual",
    );
  });
});

describe("WITHHOLDING_LABEL", () => {
  it("names both behaviours without the word Depot leaking into other kinds", () => {
    expect(WITHHOLDING_LABEL.at_source).toBe("Withholds at source");
    expect(WITHHOLDING_LABEL.none).toBe("No withholding at source");
  });
});
