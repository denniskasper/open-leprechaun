import { describe, expect, it } from "vitest";
import type { InboxItem } from "@/api/inbox";
import { describeArrivals } from "./inbox";

function item(overrides: Partial<InboxItem>): InboxItem {
  return {
    instrument_id: 7,
    family: "crypto",
    type: "token",
    symbol: "USDC",
    name: "USDC Rewards Claim",
    chain: "solana",
    contract_address: "c1aimusdcrewardsexamp1eon1ynotrea1m1nt111111",
    isin: null,
    account_id: 3,
    account_name: "Hot wallet",
    platform_name: "Phantom",
    unclassified_inflow_count: 1,
    unclassified_quantity: "1999.75",
    last_inflow_at: "2026-03-01T09:00:00Z",
    ...overrides,
  };
}

describe("describeArrivals", () => {
  it("sums the unsolicited inflows a keep decision would settle", () => {
    expect(describeArrivals(item({}), "en")).toBe("1 unclassified inflow · 1,999.75 USDC");
  });

  it("pluralises several inflows", () => {
    expect(
      describeArrivals(
        item({ unclassified_inflow_count: 3, unclassified_quantity: "2000.00" }),
        "en",
      ),
    ).toBe("3 unclassified inflows · 2,000.00 USDC");
  });

  it("says when only deliberate records await the stance", () => {
    expect(
      describeArrivals(item({ unclassified_inflow_count: 0, unclassified_quantity: "0" })),
    ).toBe("No unclassified inflows — recorded by hand, awaiting only the stance.");
  });
});
