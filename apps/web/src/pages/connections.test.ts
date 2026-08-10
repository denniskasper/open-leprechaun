import { describe, expect, it } from "vitest";
import type { AdapterStatus, Connection } from "@/api/connections";
import type { Platform } from "@/api/platforms";
import { describeLastUse, groupByPlatform, READ_ONLY_RULE, statusTone } from "./connections";

function connection(overrides: Partial<Connection>): Connection {
  return {
    id: 1,
    platform_id: 1,
    venue: "okx",
    label: "Main account",
    fingerprint: "a1b2c3d4e5f6",
    last_used_at: null,
    statuses: [],
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
