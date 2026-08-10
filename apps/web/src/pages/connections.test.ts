import { describe, expect, it } from "vitest";
import type { AdapterStatus, Connection, KindSyncResult, Venue } from "@/api/connections";
import type { Platform } from "@/api/platforms";
import {
  describeLastUse,
  describeSyncResult,
  describeTestResult,
  groupByPlatform,
  kindsOf,
  READ_ONLY_RULE,
  statusTone,
} from "./connections";

function connection(overrides: Partial<Connection>): Connection {
  return {
    id: 1,
    platform_id: 1,
    venue: "okx",
    label: "Main account",
    fingerprint: "a1b2c3d4e5f6",
    last_used_at: null,
    statuses: [],
    pairings: [],
    ...overrides,
  };
}

function platform(overrides: Partial<Platform>): Platform {
  return { id: 1, name: "OKX", kind: "exchange", accounts: [], ...overrides };
}

function status(overrides: Partial<AdapterStatus>): AdapterStatus {
  return {
    adapter_kind: "spot",
    last_success_at: null,
    last_error_at: null,
    last_error: null,
    ...overrides,
  };
}

function venue(overrides: Partial<Venue>): Venue {
  return {
    venue: "pionex",
    name: "Pionex",
    required_scope: "Read only.",
    requires_secret: true,
    requires_passphrase: false,
    adapter_kinds: [],
    ...overrides,
  };
}

function syncResult(overrides: Partial<KindSyncResult>): KindSyncResult {
  return {
    adapter_kind: "futures",
    ok: true,
    error: null,
    futures: null,
    imported: null,
    covered_days: null,
    ...overrides,
  };
}

describe("groupByPlatform", () => {
  it("groups connections under their platform, in the platform list's order", () => {
    const groups = groupByPlatform(
      [
        connection({ id: 1, platform_id: 2, label: "Invest" }),
        connection({ id: 2, platform_id: 1, label: "Main account" }),
        connection({ id: 3, platform_id: 1, label: "Bot subaccount" }),
      ],
      [platform({ id: 1, name: "OKX" }), platform({ id: 2, name: "Trading 212", kind: "broker" })],
    );

    expect(groups.map((group) => group.platform.name)).toEqual(["OKX", "Trading 212"]);
    expect(groups[0]?.connections.map((entry) => entry.label)).toEqual([
      "Main account",
      "Bot subaccount",
    ]);
  });

  it("omits a platform without connections — the platforms screen already shows it", () => {
    const groups = groupByPlatform(
      [connection({ platform_id: 1 })],
      [platform({ id: 1 }), platform({ id: 2, name: "Sparkasse", kind: "bank" })],
    );

    expect(groups.map((group) => group.platform.id)).toEqual([1]);
  });
});

describe("describeLastUse", () => {
  it("says a fresh credential has never been used", () => {
    expect(describeLastUse(null)).toBe("Never used yet");
  });

  it("states when the credential last opened the venue", () => {
    expect(describeLastUse("2026-08-10T09:00:00Z", "de-DE")).toContain("Last used");
    expect(describeLastUse("2026-08-10T09:00:00Z", "de-DE")).toContain("2026");
  });
});

describe("statusTone", () => {
  it("shows the signal colour for a kind whose last outcome succeeded", () => {
    expect(statusTone(status({ last_success_at: "2026-08-10T09:00:00Z" }))).toBe("signal");
  });

  it("shows the alarm colour for a kind that has failed since it last worked", () => {
    expect(
      statusTone(
        status({
          last_success_at: "2026-08-09T09:00:00Z",
          last_error_at: "2026-08-10T09:00:00Z",
          last_error: "401 from the venue",
        }),
      ),
    ).toBe("alarm");
  });
});

describe("READ_ONLY_RULE", () => {
  it("states that access must be read-only", () => {
    expect(READ_ONLY_RULE.toLowerCase()).toContain("read-only");
  });
});

describe("kindsOf", () => {
  it("offers the kinds the venue's adapters serve, before anything has run", () => {
    expect(kindsOf(connection({}), venue({ adapter_kinds: ["futures"] }))).toEqual(["futures"]);
  });

  it("keeps a kind a status or pairing already names, even off the registry", () => {
    const recorded = connection({
      statuses: [status({ adapter_kind: "spot" })],
      pairings: [{ adapter_kind: "margin", account_id: 4 }],
    });

    expect(kindsOf(recorded, venue({ adapter_kinds: ["futures"] }))).toEqual([
      "futures",
      "spot",
      "margin",
    ]);
  });

  it("shows nothing for a venue whose adapters have not shipped", () => {
    expect(kindsOf(connection({}), venue({}))).toEqual([]);
    expect(kindsOf(connection({}), undefined)).toEqual([]);
  });
});

describe("describeTestResult", () => {
  it("answers the venue's own sentence on success and the error otherwise", () => {
    expect(
      describeTestResult({ adapter_kind: "futures", ok: true, detail: "Authenticated.", error: null }),
    ).toBe("Authenticated.");
    expect(
      describeTestResult({ adapter_kind: "futures", ok: false, detail: null, error: "401." }),
    ).toBe("401.");
  });
});

describe("describeSyncResult", () => {
  it("counts what the futures pipeline stored, singular and plural", () => {
    expect(
      describeSyncResult(syncResult({ futures: { new_fills: 1, new_funding: 2 } })),
    ).toBe("1 new fill · 2 new funding payments");
  });

  it("counts what the import framework created and what it already knew", () => {
    expect(
      describeSyncResult(
        syncResult({ imported: { batch_id: 5, created: 3, duplicates: 2, skipped: 1 } }),
      ),
    ).toBe("3 rows imported · 2 already known · 1 skipped");
  });

  it("says so when a kind had nothing to pull", () => {
    expect(describeSyncResult(syncResult({}))).toBe("Nothing to pull for this kind.");
  });

  it("states the period the pull covered beside what landed", () => {
    expect(
      describeSyncResult(
        syncResult({ futures: { new_fills: 1, new_funding: 2 }, covered_days: 90 }),
      ),
    ).toBe("1 new fill · 2 new funding payments · covering the last 90 days");
  });

  it("names the covered period when it held nothing, so empty is never ambiguous", () => {
    expect(describeSyncResult(syncResult({ covered_days: 90 }))).toBe(
      "Nothing to pull — the last 90 days are covered.",
    );
  });

  it("keeps what landed visible beside the error that followed it", () => {
    const partial = syncResult({
      ok: false,
      error: "Another source is authoritative.",
      futures: { new_fills: 2, new_funding: 0 },
    });

    expect(describeSyncResult(partial)).toBe(
      "Another source is authoritative. (2 new fills · 0 new funding payments before the refusal)",
    );
  });
});
