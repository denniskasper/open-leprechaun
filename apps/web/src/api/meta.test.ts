import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchMeta } from "./meta";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMeta", () => {
  it("reads the instance identity from the API's own origin", async () => {
    respondWith(200, { environment: "development", version: "a17a9a2" });

    await fetchMeta();

    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/meta");
  });

  it("returns the identity of a development instance", async () => {
    respondWith(200, { environment: "development", version: "a17a9a2" });

    await expect(fetchMeta()).resolves.toEqual({ environment: "development", version: "a17a9a2" });
  });

  it("returns the identity of a production instance", async () => {
    respondWith(200, { environment: "production", version: "2026.08.1" });

    await expect(fetchMeta()).resolves.toEqual({ environment: "production", version: "2026.08.1" });
  });

  it("rejects an environment it does not know", async () => {
    respondWith(200, { environment: "staging", version: "a17a9a2" });

    await expect(fetchMeta()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchMeta()).rejects.toThrow("500");
  });
});
