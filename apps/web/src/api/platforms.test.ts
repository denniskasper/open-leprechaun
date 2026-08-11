import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addAccount,
  fetchPlatforms,
  registerPlatform,
  setWithholding,
  setWithholdingOverride,
} from "./platforms";

const kraken = {
  id: 1,
  name: "Kraken",
  kind: "exchange",
  withholding: null,
  exemption_order_eur: null,
  accounts: [
    {
      id: 1,
      name: "Main",
      chain: null,
      external_reference: null,
      access_software: null,
      withholding_override: null,
      base_currency: null,
    },
  ],
};

const device = {
  id: 2,
  name: "BitBox02",
  kind: "cold_storage",
  withholding: null,
  exemption_order_eur: null,
  accounts: [
    {
      id: 2,
      name: "Savings",
      chain: "bitcoin",
      external_reference: null,
      access_software: "BitBoxApp",
      withholding_override: null,
      base_currency: null,
    },
  ],
};

const broker = {
  id: 3,
  name: "Scalable Capital",
  kind: "broker",
  withholding: "at_source",
  exemption_order_eur: "801",
  accounts: [
    {
      id: 3,
      name: "Depot",
      chain: null,
      external_reference: "1234567890",
      access_software: null,
      withholding_override: "none",
      base_currency: "EUR",
    },
  ],
};

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    // A 204 carries no body — the Response constructor itself refuses one.
    vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status })),
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

  it("carries a broker's withholding, exemption order and Depot semantics", async () => {
    respondWith(200, [broker]);

    await expect(fetchPlatforms()).resolves.toEqual([broker]);
  });

  it("rejects a kind it does not know", async () => {
    respondWith(200, [{ ...kraken, kind: "hardware" }]);

    await expect(fetchPlatforms()).rejects.toThrow();
  });

  it("rejects a withholding it does not know", async () => {
    respondWith(200, [{ ...broker, withholding: "sometimes" }]);

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
      base_currency: null,
    });

    expect(fetch).toHaveBeenCalledWith("/api/platforms/2/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Savings",
        chain: "bitcoin",
        external_reference: null,
        access_software: "BitBoxApp",
        base_currency: null,
      }),
    });
  });

  it("posts a Depot's base currency", async () => {
    respondWith(201, { id: 4 });

    await addAccount(3, {
      name: "Depot",
      chain: null,
      external_reference: null,
      access_software: null,
      base_currency: "EUR",
    });

    expect(fetch).toHaveBeenCalledWith("/api/platforms/3/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Depot",
        chain: null,
        external_reference: null,
        access_software: null,
        base_currency: "EUR",
      }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "'Savings' already exists under this Platform." });

    await expect(
      addAccount(2, {
        name: "Savings",
        chain: null,
        external_reference: null,
        access_software: null,
        base_currency: null,
      }),
    ).rejects.toThrow("'Savings' already exists under this Platform.");
  });
});

describe("setWithholding", () => {
  it("puts behaviour and exemption order on the platform, money as a string", async () => {
    respondWith(204, null);

    await setWithholding(3, { behaviour: "at_source", exemption_order_eur: "801" });

    expect(fetch).toHaveBeenCalledWith("/api/platforms/3/withholding", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ behaviour: "at_source", exemption_order_eur: "801" }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "Only a broker Platform carries withholding behaviour." });

    await expect(
      setWithholding(1, { behaviour: "at_source", exemption_order_eur: null }),
    ).rejects.toThrow("Only a broker Platform carries withholding behaviour.");
  });
});

describe("setWithholdingOverride", () => {
  it("puts the account's exception, null clearing it", async () => {
    respondWith(204, null);

    await setWithholdingOverride(3, null);

    expect(fetch).toHaveBeenCalledWith("/api/accounts/3/withholding-override", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ behaviour: null }),
    });
  });

  it("surfaces the API's own words for a refusal", async () => {
    respondWith(409, { detail: "Only an Account under a broker carries an override." });

    await expect(setWithholdingOverride(1, "none")).rejects.toThrow(
      "Only an Account under a broker carries an override.",
    );
  });
});
