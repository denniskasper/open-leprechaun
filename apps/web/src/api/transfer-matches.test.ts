import { afterEach, describe, expect, it, vi } from "vitest";
import { decideMatch, fetchMatching, undoDecision } from "./transfer-matches";

const outgoing = {
  leg_id: 10,
  transaction_id: 3,
  occurred_at: "2026-02-02T18:30:00Z",
  note: "Withdrawn to cold storage",
  quantity: "0.004",
  account_id: 1,
  account_name: "Main",
  platform_name: "Kraken",
  instrument_id: 7,
  instrument_symbol: "BTC",
  instrument_name: "Bitcoin",
};

const incoming = {
  ...outgoing,
  leg_id: 11,
  transaction_id: 4,
  occurred_at: "2026-02-02T18:45:00Z",
  note: "Moved from the exchange",
  account_id: 2,
  account_name: "Savings",
  platform_name: "BitBox02",
};

const overview = {
  unmatched_outgoing: [outgoing],
  unmatched_incoming: [incoming],
  candidates: [{ outgoing, incoming }],
  decisions: [],
};

function respondWith(status: number, body?: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMatching", () => {
  it("parses the matching state", async () => {
    respondWith(200, overview);

    const state = await fetchMatching();

    expect(state.candidates[0]?.outgoing.quantity).toBe("0.004");
    expect(state.unmatched_incoming[0]?.platform_name).toBe("BitBox02");
  });

  it("refuses a quantity that crossed JSON as a number", async () => {
    respondWith(200, {
      ...overview,
      candidates: [],
      decisions: [],
      unmatched_incoming: [],
      unmatched_outgoing: [{ ...outgoing, quantity: 0.004 }],
    });

    await expect(fetchMatching()).rejects.toThrow();
  });

  it("names the status when the API does not answer", async () => {
    respondWith(500);

    await expect(fetchMatching()).rejects.toThrow("500");
  });
});

describe("decideMatch", () => {
  it("answers the decision id", async () => {
    respondWith(201, { id: 5 });

    await expect(
      decideMatch({ out_leg_id: 10, in_leg_id: 11, verdict: "confirmed" }),
    ).resolves.toBe(5);
  });

  it("carries the API's own sentence on a refusal", async () => {
    respondWith(422, { detail: "More arrived than left — that cannot be one self-transfer." });

    await expect(
      decideMatch({ out_leg_id: 10, in_leg_id: 11, verdict: "confirmed" }),
    ).rejects.toThrow("More arrived than left — that cannot be one self-transfer.");
  });
});

describe("undoDecision", () => {
  it("resolves on 204", async () => {
    respondWith(204);

    await expect(undoDecision(5)).resolves.toBeUndefined();
  });

  it("carries the API's own sentence when nothing was there", async () => {
    respondWith(404, { detail: "No such decision." });

    await expect(undoDecision(5)).rejects.toThrow("No such decision.");
  });
});
