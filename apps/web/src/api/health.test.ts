import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchHealth } from "./health";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchHealth", () => {
  it("reads the health report from the API's own origin", async () => {
    respondWith(200, { status: "ok", database: "up" });

    await fetchHealth();

    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/health");
  });

  it("returns the report when the service is healthy", async () => {
    respondWith(200, { status: "ok", database: "up" });

    await expect(fetchHealth()).resolves.toEqual({ status: "ok", database: "up" });
  });

  it("returns the report when the service is degraded, which arrives as a 503", async () => {
    respondWith(503, { status: "degraded", database: "down" });

    await expect(fetchHealth()).resolves.toEqual({ status: "degraded", database: "down" });
  });

  it("rejects a response that is not a health report", async () => {
    respondWith(200, { status: "fine" });

    await expect(fetchHealth()).rejects.toThrow();
  });

  it("rejects a response that carries no report at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>gateway error</html>", { status: 502 })),
    );

    await expect(fetchHealth()).rejects.toThrow("502");
  });
});
