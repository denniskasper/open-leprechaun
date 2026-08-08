import { afterEach, describe, expect, it, vi } from "vitest";
import { classifyInstrument, fetchInbox } from "./inbox";

const arrival = {
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
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchInbox", () => {
  it("reads the inbox from the API's own origin", async () => {
    respondWith(200, []);

    await fetchInbox();

    expect(fetch).toHaveBeenCalledWith("/api/inbox");
  });

  it("returns arrivals with their identity, whereabouts and pending inflows", async () => {
    respondWith(200, [arrival]);

    await expect(fetchInbox()).resolves.toEqual([arrival]);
  });

  it("rejects a quantity that is not a fixed-point decimal string", async () => {
    respondWith(200, [{ ...arrival, unclassified_quantity: 1999.75 }]);

    await expect(fetchInbox()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchInbox()).rejects.toThrow("500");
  });
});

describe("classifyInstrument", () => {
  it("puts the classification and answers the settled transaction ids", async () => {
    respondWith(200, { settled_transaction_ids: [41] });

    const settled = await classifyInstrument(7, {
      stance: "kept",
      account_id: 3,
      received_for_counter_performance: false,
    });

    expect(settled).toEqual([41]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/instruments/7/stance",
      expect.objectContaining({ method: "PUT" }),
    );
  });

  it("carries the API's own words for a refusal", async () => {
    respondWith(422, { detail: "A kept stance is a decision about one Account." });

    await expect(classifyInstrument(7, { stance: "kept" })).rejects.toThrow(
      "A kept stance is a decision about one Account.",
    );
  });
});
