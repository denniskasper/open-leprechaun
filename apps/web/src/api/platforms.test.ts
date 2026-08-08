import { afterEach, describe, expect, it, vi } from "vitest";
import { addAccount, fetchPlatforms, registerPlatform } from "./platforms";

const kraken = {
  id: 1,
  name: "Kraken",
  kind: "exchange",
  accounts: [
    {
      id: 1,
      name: "Main",
      chain: null,
      external_reference: null,
      access_software: null,
    },
  ],
};

const device = {
  id: 2,
  name: "BitBox02",
  kind: "cold_storage",
  accounts: [
    {
      id: 2,
      name: "Savings",
      chain: "bitcoin",
      external_reference: null,
      access_software: "BitBoxApp",
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

describe("fetchPlatforms", () => {
  it("reads the platforms from the API's own origin", async () => {
    respondWith(200, []);

    await fetchPlatforms();

    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/platforms");
  });

  it("returns platforms with their accounts nested under them", async () => {
    respondWith(200, [kraken, device]);

    await expect(fetchPlatforms()).resolves.toEqual([kraken, device]);
  });

  it("rejects a kind it does not know", async () => {
    respondWith(200, [{ ...kraken, kind: "hardware" }]);

    await expect(fetchPlatforms()).rejects.toThrow();
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchPlatforms()).rejects.toThrow("500");
  });
});

describe("registerPlatform", () => {
  it("posts name and kind", async () => {
    respondWith(201, { id: 7 });

    await registerPlatform({ name: "Kraken", kind: "exchange" });

    expect(fetch).toHaveBeenCalledWith("/api/platforms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Kraken", kind: "exchange" }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "'Kraken' is already registered." });

    await expect(registerPlatform({ name: "Kraken", kind: "exchange" })).rejects.toThrow(
      "'Kraken' is already registered.",
    );
  });
});

describe("addAccount", () => {
  it("posts the account under its platform", async () => {
    respondWith(201, { id: 3 });

    await addAccount(2, {
      name: "Savings",
      chain: "bitcoin",
      external_reference: null,
      access_software: "BitBoxApp",
    });

    expect(fetch).toHaveBeenCalledWith("/api/platforms/2/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Savings",
        chain: "bitcoin",
        external_reference: null,
        access_software: "BitBoxApp",
      }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "'Savings' already exists under this Platform." });

    await expect(
      addAccount(2, { name: "Savings", chain: null, external_reference: null, access_software: null }),
    ).rejects.toThrow("'Savings' already exists under this Platform.");
  });
});
