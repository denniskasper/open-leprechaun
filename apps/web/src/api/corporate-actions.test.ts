import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyCorporateAction,
  fetchCorporateActions,
  markCorporateActionReviewed,
  previewCorporateAction,
  removeCorporateAction,
} from "./corporate-actions";

const split = {
  id: 4,
  kind: "split",
  instrument_id: 7,
  effective_at: "2031-05-02T00:00:00Z",
  units_new: "2",
  units_old: "1",
  target_instrument_id: null,
  basis_share: null,
  amount_per_unit_eur: null,
  note: null,
  reviewed_at: null,
  needs_review: false,
  lots: [
    {
      account_id: 1,
      acquired_at: "2031-02-10T12:00:00Z",
      basis_source: "cost",
      before: { instrument_id: 7, quantity: "10", basis_eur: "1000" },
      after: [{ instrument_id: 7, quantity: "20", basis_eur: "1000" }],
      excess_eur: "0",
    },
  ],
};

const stated = {
  kind: "split" as const,
  instrument_id: 7,
  effective_at: "2031-05-02T00:00:00Z",
  units_new: "2",
  units_old: "1",
};

function respondWith(status: number, body?: unknown) {
  const fetchMock = vi.fn(
    async (_url: string, _init?: RequestInit) =>
      new Response(body === undefined ? null : JSON.stringify(body), { status }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchCorporateActions", () => {
  it("parses each event with the lots it touched", async () => {
    respondWith(200, [split]);

    const [action] = await fetchCorporateActions();

    expect(action?.lots[0]?.after[0]?.quantity).toBe("20");
  });

  it("refuses a quantity that crossed JSON as a number", async () => {
    const lot = { ...split.lots[0], before: { instrument_id: 7, quantity: 10, basis_eur: "1000" } };
    respondWith(200, [{ ...split, lots: [lot] }]);

    await expect(fetchCorporateActions()).rejects.toThrow();
  });

  it("names the status when the API does not answer", async () => {
    respondWith(500);

    await expect(fetchCorporateActions()).rejects.toThrow("500");
  });
});

describe("previewCorporateAction", () => {
  it("posts the event to the preview and answers it without an id", async () => {
    const fetchMock = respondWith(200, { ...split, id: null });

    const preview = await previewCorporateAction(stated);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/corporate-actions/preview");
    expect(preview.id).toBeNull();
  });

  it("carries the API's own words for a refusal", async () => {
    respondWith(422, { detail: "EUR is cash — a Corporate Action acts on a security." });

    await expect(previewCorporateAction(stated)).rejects.toThrow("EUR is cash");
  });
});

describe("applyCorporateAction", () => {
  it("answers the recorded event's id", async () => {
    respondWith(201, { id: 4 });

    await expect(applyCorporateAction(stated)).resolves.toBe(4);
  });
});

describe("markCorporateActionReviewed and removeCorporateAction", () => {
  it("address the event by id", async () => {
    const fetchMock = respondWith(204);

    await markCorporateActionReviewed(4);
    await removeCorporateAction(4);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/corporate-actions/4/review");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/corporate-actions/4");
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("DELETE");
  });

  it("say so when there is no such event", async () => {
    respondWith(404, { detail: "No such Corporate Action." });

    await expect(removeCorporateAction(9)).rejects.toThrow("No such Corporate Action.");
  });
});
