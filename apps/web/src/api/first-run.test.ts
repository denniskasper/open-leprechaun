import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchFirstRunChecklist } from "./first-run";

const checklist = {
  complete: false,
  items: [
    {
      key: "password",
      done: true,
      optional: false,
      detail: "The Admin password is set.",
      resolve_path: "/setup",
    },
    {
      key: "two_factor",
      done: false,
      optional: true,
      detail: "Two-factor is off — the password alone opens a Session.",
      resolve_path: "/settings/security",
    },
  ],
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

describe("fetchFirstRunChecklist", () => {
  it("reads every step with its state, its reason and where it is completed", async () => {
    respondWith(200, checklist);

    await expect(fetchFirstRunChecklist()).resolves.toEqual(checklist);

    expect(fetch).toHaveBeenCalledWith("/api/first-run-checklist");
  });

  it("rejects an error status, naming what was not answered", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchFirstRunChecklist()).rejects.toThrow(
      "The API answered 500 instead of the first-run checklist.",
    );
  });

  it("rejects a step this screen has no words for", async () => {
    respondWith(200, { ...checklist, items: [{ ...checklist.items[0], key: "tick_a_box" }] });

    await expect(fetchFirstRunChecklist()).rejects.toThrow();
  });
});
