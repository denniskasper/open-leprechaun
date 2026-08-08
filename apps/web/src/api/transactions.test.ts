import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchTransactions,
  recordTransaction,
  removeTransaction,
  reviseTransaction,
  type NewTransaction,
} from "./transactions";

const buy = {
  id: 1,
  type: "trade",
  occurred_at: "2026-03-14T12:00:00Z",
  note: "First buy",
  legs: [
    {
      id: 10,
      account_id: 3,
      instrument_id: 5,
      role: "out",
      quantity: "100.00",
      charged_against_leg_id: null,
    },
    {
      id: 11,
      account_id: 3,
      instrument_id: 6,
      role: "in",
      quantity: "0.005",
      charged_against_leg_id: null,
    },
    {
      id: 12,
      account_id: 3,
      instrument_id: 5,
      role: "fee",
      quantity: "0.40",
      charged_against_leg_id: 11,
    },
  ],
};

const drafted: NewTransaction = {
  type: "fee",
  occurred_at: "2026-03-14T12:00:00.000Z",
  note: null,
  legs: [
    { account_id: 3, instrument_id: 5, role: "fee", quantity: "4.90", charged_against: null },
  ],
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

describe("fetchTransactions", () => {
  it("reads the ledger from the API's own origin", async () => {
    respondWith(200, []);

    await fetchTransactions();

    expect(fetch).toHaveBeenCalledWith("/api/transactions");
  });

  it("returns transactions with their legs nested, quantities as strings", async () => {
    respondWith(200, [buy]);

    const transactions = await fetchTransactions();

    expect(transactions).toEqual([buy]);
    expect(transactions[0]?.legs.every((leg) => typeof leg.quantity === "string")).toBe(true);
  });

  it("rejects a quantity that arrives as a JSON number", async () => {
    // Fixed-point end to end: a number in the JSON means something has been
    // through a float, and the client refuses to pretend otherwise.
    const drifted = { ...buy, legs: [{ ...buy.legs[0], quantity: 100.0 }] };
    respondWith(200, [drifted]);

    await expect(fetchTransactions()).rejects.toThrow();
  });

  it("rejects a type outside the vocabulary", async () => {
    respondWith(200, [{ ...buy, type: "barter" }]);

    await expect(fetchTransactions()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchTransactions()).rejects.toThrow("500");
  });
});

describe("recordTransaction", () => {
  it("posts the event with its legs", async () => {
    respondWith(201, { id: 7 });

    await recordTransaction(drafted);

    expect(fetch).toHaveBeenCalledWith("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(drafted),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(422, { detail: "A trade records what arrived, and this one is missing it." });

    await expect(recordTransaction(drafted)).rejects.toThrow(
      "A trade records what arrived, and this one is missing it.",
    );
  });
});

describe("reviseTransaction", () => {
  it("puts the whole event at its own address", async () => {
    respondWith(204);

    await reviseTransaction(7, drafted);

    expect(fetch).toHaveBeenCalledWith("/api/transactions/7", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(drafted),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(404, { detail: "No such Transaction." });

    await expect(reviseTransaction(7, drafted)).rejects.toThrow("No such Transaction.");
  });
});

describe("removeTransaction", () => {
  it("deletes at the event's own address", async () => {
    respondWith(204);

    await removeTransaction(7);

    expect(fetch).toHaveBeenCalledWith("/api/transactions/7", { method: "DELETE" });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(404, { detail: "No such Transaction." });

    await expect(removeTransaction(7)).rejects.toThrow("No such Transaction.");
  });
});
