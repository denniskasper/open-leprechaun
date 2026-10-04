import { describe, expect, it } from "vitest";
import type { LeftOut } from "@/api/ledger-export";
import { leftOutByReason } from "@/pages/ledger-export";
import { NAV_SECTIONS } from "@/navigation";

function leftOut(overrides: Partial<LeftOut> = {}): LeftOut {
  return {
    transaction_id: 1,
    type: "trade",
    occurred_at: "2031-03-14T12:30:05Z",
    reason: "SAP is a security, and CoinTracking holds only coins and currencies.",
    ...overrides,
  };
}

describe("leftOutByReason", () => {
  it("states each reason once, over the Transactions it covers", () => {
    const spam = "FREE stands ignored at Kraken - Main, outside the cost basis here as well.";
    const groups = leftOutByReason([
      leftOut({ transaction_id: 1 }),
      leftOut({ transaction_id: 2, reason: spam, type: "transfer_in" }),
      leftOut({ transaction_id: 3 }),
    ]);

    expect(groups.map((group) => [group.reason, group.entries.map((e) => e.transaction_id)])).toEqual([
      ["SAP is a security, and CoinTracking holds only coins and currencies.", [1, 3]],
      [spam, [2]],
    ]);
  });

  it("is empty for a ledger the file carries whole", () => {
    expect(leftOutByReason([])).toEqual([]);
  });
});

describe("navigation", () => {
  it("offers the export under Ledger", () => {
    const ledger = NAV_SECTIONS.find((section) => section.label === "Ledger");

    expect(ledger?.items).toContainEqual(
      expect.objectContaining({ to: "/export", label: "Export" }),
    );
  });
});
