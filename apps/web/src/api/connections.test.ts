import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchConnections,
  fetchVenues,
  registerConnection,
  removeConnection,
} from "./connections";

const okxVenue = {
  venue: "okx",
  name: "OKX",
  required_scope: "Create the API key with the Read permission only — no Trade, no Withdraw.",
  requires_secret: true,
  requires_passphrase: true,
  adapter_kinds: [],
};

const connection = {
  id: 1,
  platform_id: 2,
  venue: "okx",
  label: "Main account",
  fingerprint: "a1b2c3d4e5f6",
  last_used_at: null,
  statuses: [
    {
      adapter_kind: "spot",
      last_success_at: "2026-08-10T09:00:00Z",
      last_error_at: null,
      last_error: null,
    },
  ],
  pairings: [{ adapter_kind: "spot", account_id: 3 }],
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    // 204 carries no body, and Response refuses one for it.
    vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchVenues", () => {
  it("reads the venue registry from the API's own origin", async () => {
    respondWith(200, [okxVenue]);

    await expect(fetchVenues()).resolves.toEqual([okxVenue]);

    expect(fetch).toHaveBeenCalledWith("/api/connections/venues");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchVenues()).rejects.toThrow("500");
  });
});

describe("fetchConnections", () => {
  it("returns connections with their per-kind statuses", async () => {
    respondWith(200, [connection]);

    await expect(fetchConnections()).resolves.toEqual([connection]);

    expect(fetch).toHaveBeenCalledWith("/api/connections");
  });

  it("rejects a connection that carries anything besides the known shape", async () => {
    respondWith(200, [{ ...connection, fingerprint: 42 }]);

    await expect(fetchConnections()).rejects.toThrow();
  });
});

describe("registerConnection", () => {
  it("posts the whole credential set once", async () => {
    respondWith(201, { id: 7 });

    await registerConnection({
      platform_id: 2,
      venue: "okx",
      label: "Main account",
      key: "the-key",
      secret: "the-secret",
      passphrase: "the-passphrase",
    });

    expect(fetch).toHaveBeenCalledWith("/api/connections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform_id: 2,
        venue: "okx",
        label: "Main account",
        key: "the-key",
        secret: "the-secret",
        passphrase: "the-passphrase",
      }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "'Main account' already exists under this Platform." });

    await expect(
      registerConnection({
        platform_id: 2,
        venue: "okx",
        label: "Main account",
        key: "the-key",
        secret: "the-secret",
        passphrase: "the-passphrase",
      }),
    ).rejects.toThrow("'Main account' already exists under this Platform.");
  });
});

describe("removeConnection", () => {
  it("deletes by id", async () => {
    respondWith(204, undefined);

    await removeConnection(7);

    expect(fetch).toHaveBeenCalledWith("/api/connections/7", { method: "DELETE" });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(404, { detail: "No such Connection." });

    await expect(removeConnection(7)).rejects.toThrow("No such Connection.");
  });
});
