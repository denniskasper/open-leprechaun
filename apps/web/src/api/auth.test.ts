import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRefusal, fetchSession, fetchSetupStatus, logIn, runSetup } from "./auth";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchSetupStatus", () => {
  it("reports that a fresh instance still needs its admin", async () => {
    respondWith(200, { required: true });

    await expect(fetchSetupStatus()).resolves.toEqual({ required: true });
    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/auth/setup");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchSetupStatus()).rejects.toThrow("500");
  });
});

describe("runSetup", () => {
  it("posts the password as JSON to the setup endpoint", async () => {
    respondWith(201, null);

    await runSetup("correct horse battery staple");

    expect(fetch).toHaveBeenCalledWith("/api/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: "correct horse battery staple" }),
    });
  });

  it("surfaces the API's own words when setup is refused", async () => {
    respondWith(409, { detail: "Setup has already run; this instance has its admin." });

    await expect(runSetup("correct horse battery staple")).rejects.toThrow(
      "Setup has already run; this instance has its admin.",
    );
  });
});

describe("logIn", () => {
  it("resolves without exposing the token to the caller", async () => {
    respondWith(200, { token: "should-never-surface", expires_at: "2026-09-07T00:00:00Z" });

    await expect(logIn("correct horse battery staple")).resolves.toBeUndefined();
  });

  it("surfaces a wrong password as the API's refusal", async () => {
    respondWith(401, { detail: "Wrong password." });

    const attempt = logIn("not the password");

    await expect(attempt).rejects.toThrow("Wrong password.");
    await expect(attempt).rejects.toBeInstanceOf(ApiRefusal);
  });
});

describe("fetchSession", () => {
  it("names the caller when a session is live", async () => {
    respondWith(200, { subject: "admin" });

    await expect(fetchSession()).resolves.toEqual({ subject: "admin" });
  });

  it("answers null, not an error, when nobody is logged in", async () => {
    respondWith(401, { detail: "Authentication required." });

    await expect(fetchSession()).resolves.toBeNull();
  });

  it("rejects an unexpected status", async () => {
    respondWith(503, { detail: "down" });

    await expect(fetchSession()).rejects.toThrow("503");
  });
});
